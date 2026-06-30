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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import parking_context
from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected
from app.models.user import User
from app.schemas.plate import (
    PlateDetectedCreate,
    PlateDetectedRead,
    PlateHit,
)

router = APIRouter(
    prefix="/parkings/{parking_id}",
    tags=["placas"],
    dependencies=[Depends(parking_context)],
)


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
    response_model=list[PlateDetectedRead],
    status_code=status.HTTP_201_CREATED,
)
def create_plates_detected(
    parking_id: int,
    camera_id: int,
    payload: PlateDetectedCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(parking_context),
) -> list[PlatesDetected]:
    """Empuja manualmente una lista de hits a la tabla plates_detected.

    Pensado para:
    - tests de integración (smoke test del POST),
    - futuras herramientas de depuración del gestor.
    El worker Celery también usará este flujo, pero vía la sesión
    propia de Celery, no vía HTTP.
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

    now = datetime.now(timezone.utc)
    rows: list[PlatesDetected] = []
    for hit in payload.hits:
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
    return rows