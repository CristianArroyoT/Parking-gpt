"""Endpoints REST para incidentes (marcar plaza, reportar robo, rehabilitar).

Un único endpoint: ``POST /api/v1/parkings/{parking_id}/incidents`` con
``kind ∈ {space_broken, space_unbroken, robery_reported}``. RBAC:
admin/gestor/operador con membresía en la sucursal. Cliente → 403.

Devuelve 201 con ``IncidentRead`` si crea una alerta nueva, o 200 con
``{"noop": true, "detail": "..."}`` si la operación era idempotente (la
plaza ya estaba en el estado deseado).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, parking_context, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.audit import IncidentCreate, IncidentRead
from app.services.incidents import create_incident

router = APIRouter(prefix="/incidents", tags=["incidentes"])


@router.post(
    "/parkings/{parking_id}",
    dependencies=[
        Depends(require_role(
            UserRole.ADMIN.value,
            UserRole.GESTOR.value,
            UserRole.OPERADOR.value,
        ))
    ],
)
def create_incident_endpoint(
    parking_id: int,
    payload: IncidentCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parking_context(parking_id, current=current_user, db=db)
    ip = request.client.host if request.client else None
    alert = create_incident(
        payload,
        parking_id=parking_id,
        current_user=current_user,
        ip=ip,
    )
    if alert is None:
        # Idempotente: ya estaba en el estado deseado.
        response.status_code = 200
        return {"noop": True, "detail": "La plaza ya estaba en el estado deseado"}
    response.status_code = 201
    return IncidentRead.model_validate(alert)


__all__ = ["router"]