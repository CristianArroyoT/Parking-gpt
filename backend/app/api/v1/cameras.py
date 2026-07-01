"""CRUD de cámaras y geocercas."""

from __future__ import annotations

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

log = logging.getLogger(__name__)

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
    db: Session = Depends(get_db),
) -> None:
    """Elimina una geocerca. Validamos que la cámara pertenece al
    ``parking_id`` del path (defensa contra IDs cruzados).

    Sprint Fase 4 (2026-07-01): antes la única forma de "modificar" una
    geocerca era ``PATCH /geofences/{id}`` con un payload nuevo — no
    había forma de borrarla. Con este endpoint, el operador puede
    limpiar geocercas obsoletas desde ``CalibrateView.vue``.
    """
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