"""Endpoints para consultar y registrar matrículas detectadas.

GET  /api/v1/parkings/{parking_id}/plates-detected
POST /api/v1/parkings/{parking_id}/cameras/{camera_id}/plates

Ambos pasan por `parking_context`, así que:
- admin → todas las sucursales.
- gestor / operador → sólo sucursales donde tiene membresía.
- cliente → 403 (no tiene sentido en MVP; si en el futuro quiere ver
  sus propias matrículas, será un endpoint aparte).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import parking_context
from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected
from app.models.user import User
from app.schemas.ingest import IngestResultRead
from app.schemas.plate import (
    PlateDetectedCreate,
    PlateDetectedRead,
    PlateHit,
)
from app.services.ingest_service import process_plate_hits
from app.services.plates import parece_matricula

router = APIRouter(
    prefix="/parkings/{parking_id}",
    tags=["placas"],
    dependencies=[Depends(parking_context)],
)

log = logging.getLogger(__name__)


@router.get("/plates-detected", response_model=list[PlateDetectedRead])
def list_plates_detected(
    parking_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    camera_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    _user: User = Depends(parking_context),
) -> list[PlatesDetected]:
    """Lista las últimas matrículas detectadas en la sucursal.

    `limit` por defecto 50 (suficiente para un panel en vivo; cap 500).
    `camera_id` filtra por cámara concreta.
    """
    q = (
        db.query(PlatesDetected)
        .join(Camera, Camera.id == PlatesDetected.camera_id)
        .filter(Camera.parking_id == parking_id)
        .order_by(PlatesDetected.detected_at.desc())
    )
    if camera_id is not None:
        q = q.filter(PlatesDetected.camera_id == camera_id)
    return q.limit(limit).all()


@router.post(
    "/cameras/{camera_id}/plates",
    response_model=list[IngestResultRead],
    status_code=status.HTTP_201_CREATED,
)
def create_plates_detected(
    parking_id: int,
    camera_id: int,
    payload: PlateDetectedCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(parking_context),
) -> list[IngestResultRead]:
    """Empuja manualmente una lista de hits y dispara el flujo ENTRADA.

    Filtra **antes de persistir**: el OCR devuelve TEXTO, no
    matrículas (el timestamp quemado en la imagen, el rótulo de la
    marca...), y eso no se guarda en ``plates_detected`` (T-166). Antes
    se guardaba todo hit tal cual y el gestor veía la basura en
    ``GET /parkings/{id}/plates-detected``.

    Persiste una fila cruda en ``plates_detected`` por cada hit **que
    sea una matrícula** (registro de auditoría de la lectura OCR) y, a
    continuación, llama a ``process_plate_hits`` para cruzar el bbox con
    las geocercas de la cámara y crear el ticket correspondiente (o
    registrar el skip).

    Pensado para:
    - tests de integración (smoke test del POST),
    - herramientas de depuración del gestor,
    - re-emisión manual de hits cuando el OCR falló en su momento.

    El worker Celery sigue el mismo flujo pero usa su propia sesión de BD
    en lugar de este endpoint HTTP.

    Devuelve ``list[IngestResultRead]`` con el resultado por hit: status
    ``ticket_created`` con sus IDs, o ``skipped_*`` con el motivo. El
    contrato **no** cambia: los hits descartados también aparecen en la
    respuesta, con su motivo ``skipped_not_a_plate`` (lo decide
    ``process_plate_hits``); lo único que cambia es que **no** se
    persisten.
    """
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(
            status_code=404, detail="Cámara no encontrada en esta sucursal"
        )

    # T-166: el filtro va ANTES de tocar la base de datos, igual que en
    # el worker (``ping_camera``). Se descarta lo que no tiene forma de
    # matrícula: es texto quemado en la imagen, no una lectura de
    # matrícula, y en ``plates_detected`` sólo se guarda lo segundo.
    hits_validos: list[PlateHit] = []
    for hit in payload.hits:
        if not parece_matricula(hit.plate):
            log.warning(
                "plates: el OCR no leyó una matrícula (no se persiste): %r",
                hit.plate,
                extra={"camera_id": camera.id},
            )
            continue
        hits_validos.append(hit)
    if len(hits_validos) != len(payload.hits):
        log.info(
            "plates: camera=%s leídos=%s descartados=%s (no eran matrículas)",
            camera.id,
            len(payload.hits),
            len(payload.hits) - len(hits_validos),
            extra={"camera_id": camera.id},
        )

    now = datetime.now(timezone.utc)
    rows: list[PlatesDetected] = []
    for hit in hits_validos:
        rows.append(
            PlatesDetected(
                camera_id=camera.id,
                plate=hit.plate,
                confidence=hit.confidence,
                bbox_x1=hit.bbox[0],
                bbox_y1=hit.bbox[1],
                bbox_x2=hit.bbox[2],
                bbox_y2=hit.bbox[3],
                detected_at=now,
                raw_response=hit.model_dump(),
            )
        )
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)

    # Tras persistir la fila cruda, cruzamos con geocercas. El servicio
    # abre su propia sesión por hit para no acoplar su commit al de este
    # endpoint.
    #
    # OJO: se pasan **todos** los hits (también los descartados): el
    # contrato de la respuesta es uno por hit, y el descartado vuelve con
    # su motivo ``skipped_not_a_plate``.
    ingest = process_plate_hits(payload.hits, camera)
    return [IngestResultRead.model_validate(r) for r in ingest]