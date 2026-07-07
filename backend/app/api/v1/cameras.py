"""CRUD de cámaras y geocercas."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import parking_context
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking
from app.schemas.parking import (
    CameraCreate,
    CameraHealthRead,
    CameraRead,
    CameraUpdate,
    GeofenceCreate,
    GeofenceRead,
    GeofenceUpdate,
)
from app.schemas.vehicle_detection import (
    DetectVehiclesRequest,
    DetectVehiclesResponse,
)
from app.services.audit import record_audit_from_request
from app.services.endpoint_rate_limit import endpoint_rate_limiter
from app.services.vehicle_detector.client import get_vehicle_detector_client

log = logging.getLogger(__name__)


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:
    """Aplica ``endpoint_rate_limiter.check`` y emite audit + 429 si bloquea.

    Sprint R5 (2026-07-06): misma lógica que ``users.py`` y
    ``vehicles.py`` para que ``POST/PATCH /cameras`` no sean abusables
    por un script autenticado. Bucket por actor (la acción es local al
    parking, no al admin global).
    """
    allowed, bucket, count = endpoint_rate_limiter.check(
        scope=scope, identifiers={"actor": str(actor_id)},
    )
    if not allowed:
        record_audit_from_request(
            request, db,
            action="rate_limited_endpoint",
            payload={"scope": scope, "bucket": bucket, "count": count},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas operaciones. Intenta más tarde.",
        )


router = APIRouter(
    prefix="/parkings/{parking_id}/cameras",
    tags=["cámaras"],
    dependencies=[Depends(parking_context)],
)


@router.get("", response_model=list[CameraRead])
def list_cameras(parking_id: int, db: Session = Depends(get_db)) -> list[Camera]:
    return (
        db.query(Camera)
        .filter(Camera.parking_id == parking_id)
        .order_by(Camera.id)
        .all()
    )


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
@audited("create_camera")
def create_camera(
    parking_id: int,
    payload: CameraCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> Camera:
    # Sprint R5 (2026-07-06): rate-limit por actor.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="cameras_create", actor_id=actor_id,
        )
    if not db.get(Parking, parking_id):
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    camera = Camera(parking_id=parking_id, **payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.patch("/{camera_id}", response_model=CameraRead)
@audited("update_camera", resource_arg="camera_id")
def update_camera(
    parking_id: int,
    camera_id: int,
    payload: CameraUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> Camera:
    # Sprint R5 (2026-07-06): rate-limit por actor.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="cameras_update", actor_id=actor_id,
        )
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(camera, key, value)
    db.commit()
    db.refresh(camera)
    return camera


@router.get("/{camera_id}/geofences", response_model=list[GeofenceRead])
def list_geofences(
    parking_id: int,
    camera_id: int,
    db: Session = Depends(get_db),
) -> list[CameraGeofence]:
    return (
        db.query(CameraGeofence)
        .filter(CameraGeofence.camera_id == camera_id)
        .all()
    )


@router.post(
    "/{camera_id}/geofences",
    response_model=GeofenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_geofence(
    parking_id: int,
    camera_id: int,
    payload: GeofenceCreate,
    db: Session = Depends(get_db),
) -> CameraGeofence:
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    fence = CameraGeofence(camera_id=camera_id, **payload.model_dump())
    db.add(fence)
    db.commit()
    db.refresh(fence)
    return fence


@router.patch("/{camera_id}/geofences/{fence_id}", response_model=GeofenceRead)
def update_geofence(
    parking_id: int,
    camera_id: int,
    fence_id: int,
    payload: GeofenceUpdate,
    db: Session = Depends(get_db),
) -> CameraGeofence:
    fence = (
        db.query(CameraGeofence)
        .filter(
            CameraGeofence.id == fence_id, CameraGeofence.camera_id == camera_id
        )
        .one_or_none()
    )
    if not fence:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(fence, key, value)
    db.commit()
    db.refresh(fence)
    return fence


@router.delete(
    "/{camera_id}/geofences/{fence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@audited("delete_geofence", resource_arg="fence_id")
def delete_geofence(
    parking_id: int,
    camera_id: int,
    fence_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Elimina una geocerca. Validamos que la cámara pertenece al
    ``parking_id`` del path (defensa contra IDs cruzados).

    Sprint Fase 4 (2026-07-01): antes la única forma de "modificar" una
    geocerca era ``PATCH /geofences/{id}`` con un payload nuevo — no
    había forma de borrarla. Con este endpoint, el operador puede
    limpiar geocercas obsoletas desde ``CalibrateView.vue``.

    Sprint R5 (follow-up): paridad con POST/PATCH — un bucle de borrados
    de geocercas degrada la operación igual que un bucle de parches.
    """
    # Rate-limit por actor (gestor/admin). El router ya exige
    # ``parking_context`` como dep, así que el actor siempre existe.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="geofences_delete", actor_id=actor_id,
        )
    fence = (
        db.query(CameraGeofence)
        .filter(
            CameraGeofence.id == fence_id, CameraGeofence.camera_id == camera_id
        )
        .one_or_none()
    )
    if not fence:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")
    # Validación cruzada camera↔parking.
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    db.delete(fence)
    db.commit()
    return None


# ── Camera Health (sprint 2026-07-01) ──────────────────────────────
@router.get("/{camera_id}/health", response_model=CameraHealthRead)
def camera_health(
    parking_id: int,
    camera_id: int,
    db: Session = Depends(get_db),
) -> CameraHealthRead:
    """Estado de salud derivado del último ``probe_heartbeats``.

    RBAC: ``parking_context`` ya está como dep a nivel de router, así que
    admin pasa gratis, gestor con membresía en ``parking_id`` también,
    cliente/operador sin membresía → 403 (gestionado por la dep).

    La lectura de ``consecutive_failures`` desde Redis se hace de forma
    defensiva (try/except ``RedisError`` con fallback a 0): preferimos
    devolver monitorización incompleta a un 500 cuando Redis está caído.
    """
    cam = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")

    settings = get_settings()
    stale = settings.camera_health_stale_threshold_seconds
    last_at = cam.last_heartbeat_at
    last_ok = cam.last_heartbeat_ok

    # Status derivado de 4 estados posibles (ver docs de ``CameraHealthRead``).
    if last_at is None or last_ok is None:
        status_value = "never_probed"
    elif not last_ok:
        status_value = "offline"
    else:
        age_s = (datetime.now(timezone.utc) - last_at).total_seconds()
        status_value = "healthy" if age_s <= stale else "degraded"

    # Lectura defensiva del contador Redis. Si falla, devolvemos 0: la
    # siguiente ronda del beat actualizará los health fields en BD, y
    # el operador verá que la cámara sigue "offline" / "healthy" /
    # "degraded" en ``status_value``. Sólo pierde granularidad en el
    # número de fallos consecutivos.
    consecutive = 0
    try:
        rds = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        raw = rds.get(f"camera:{cam.id}:consecutive_offline")
        if raw is not None:
            consecutive = int(raw)
    except RedisError as exc:
        log.warning(
            "camera_health: Redis no disponible camera=%s: %s",
            cam.id, exc,
        )
    except (TypeError, ValueError):
        # Clave con valor no numérico (corrupción/legacy). No es crítico.
        log.warning(
            "camera_health: consecutive_offline no numérico camera=%s",
            cam.id,
        )

    return CameraHealthRead(
        camera_id=cam.id,
        status=status_value,
        last_heartbeat_at=last_at,
        last_heartbeat_ok=last_ok,
        consecutive_failures=consecutive,
        stale_threshold_seconds=stale,
    )


@router.post(
    "/{camera_id}/detect-vehicles",
    response_model=DetectVehiclesResponse,
    summary="Detecta vehículos en una imagen capturada (YOLO cenital)",
)
async def detect_vehicles_in_frame(
    parking_id: int,
    camera_id: int,
    payload: DetectVehiclesRequest,
    db: Session = Depends(get_db),
) -> DetectVehiclesResponse:
    """Sprint Vehicle-Detect (2026-07-07): pre-flight check de calibración.

    Recibe la imagen capturada por el gestor en CalibrateView (dataURL
    JPEG o base64 puro) y devuelve la lista de vehículos detectados por
    YOLO, con bbox ya en coordenadas del viewBox 960x540 del SVG.

    El cliente HTTP ``VehicleDetectorClient`` NUNCA lanza excepción:
    si el servicio vehicle-detector está caído, devuelve ``detections=[]``.
    Aquí traducimos eso en un 200 OK silencioso — el caller decide
    qué hacer con la lista vacía.
    """
    # Defensa contra IDs cruzados: la cámara debe pertenecer al parking del path.
    cam = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")

    # Decodificar base64 (acepta dataURL 'data:image/jpeg;base64,...' o puro).
    img_str = payload.image
    if "," in img_str:
        img_str = img_str.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(img_str, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Imagen no válida: {exc}"
        ) from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Imagen vacía")

    # Llamar al cliente (nunca lanza, devuelve [] ante error).
    client = get_vehicle_detector_client()
    detections = await client.detect(
        image_bytes,
        filename="captured.jpg",
        content_type="image/jpeg",
    )

    return DetectVehiclesResponse(detections=detections)