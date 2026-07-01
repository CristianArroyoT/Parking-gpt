"""Endpoints REST para alertas operativas.

Define dos rutas:

- ``GET  /api/v1/parkings/{parking_id}/alerts`` — listado paginado y
  filtrable (type, severity, acknowledged) para la pantalla de
  "Alertas activas" del gestor.
- ``POST /api/v1/parkings/{parking_id}/alerts/{alert_id}/acknowledge``
  — marca una alerta como reconocida por el usuario actual (set
  ``acknowledged_at`` + ``acknowledged_by``). Sin DELETE en MVP
  (regla coherente con ``CalibrateView``).

RBAC: gestor (vía ``parking_context``) o admin (``parking_context`` lo
admite directamente). Cliente y operador no listan alertas.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import get_current_user, parking_context
from app.models.audit import Alert
from app.models.user import ParkingMembership, User
from app.schemas.audit import AlertRead

router = APIRouter(
    prefix="/parkings/{parking_id}/alerts",
    tags=["alertas"],
)


@router.get("", response_model=list[AlertRead])
def list_parking_alerts(
    parking_id: int,
    type: Optional[str] = Query(
        default=None,
        description="Filtra por tipo (ocr_failed, camera_offline, ...).",
    ),
    severity: Optional[str] = Query(
        default=None,
        description="Filtra por severidad (info, warn, critical).",
    ),
    acknowledged: Optional[bool] = Query(
        default=None,
        description="Si se indica, filtra por estado de reconocimiento.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(parking_context),
) -> list[Alert]:
    """Lista alertas de una sucursal, ordenadas de más reciente a más antigua."""
    q = db.query(Alert).filter(Alert.parking_id == parking_id)
    if type is not None:
        q = q.filter(Alert.type == type)
    if severity is not None:
        q = q.filter(Alert.severity == severity)
    if acknowledged is True:
        q = q.filter(Alert.acknowledged_at.is_not(None))
    elif acknowledged is False:
        q = q.filter(Alert.acknowledged_at.is_(None))
    return q.order_by(desc(Alert.created_at)).offset(offset).limit(limit).all()


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
@audited("acknowledge_alert", resource_arg="alert_id")
def acknowledge_alert(
    parking_id: int,
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Alert:
    """Marca la alerta como reconocida por el usuario actual.

    ``parking_id`` viene del path para validar que la alerta pertenece
    a una sucursal accesible — sin él un atacante podría enumerar IDs.
    La membresía de gestor se valida manualmente para evitar un JOIN
    doble con ``parking_context`` (que ya verifica la sucursal del path).
    """
    alert = db.get(Alert, alert_id)
    if alert is None or alert.parking_id != parking_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )

    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_value != "admin":
        membership = (
            db.query(ParkingMembership)
            .filter(
                ParkingMembership.user_id == user.id,
                ParkingMembership.parking_id == parking_id,
            )
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene acceso a la sucursal de esta alerta",
            )

    if alert.acknowledged_at is not None:
        return alert  # idempotente

    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = user.id
    db.commit()
    db.refresh(alert)
    return alert


__all__ = ["router"]
