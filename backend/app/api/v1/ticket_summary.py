"""Endpoint de resumen operativo de tickets por sucursal.

Sprint Fase 4-parte-2 (2026-07-06). URL final:

    GET /api/v1/parkings/{parking_id}/tickets/summary

Devuelve los KPIs de 24 h que consume ``DashboardGestor.vue``.

RBAC:
- El ``Depends(parking_context)`` rechaza a usuarios sin membresía
  en la sucursal (gestor/operador). Admin pasa siempre.
- Cliente queda bloqueado en la capa ``parking_context`` (403).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, parking_context
from app.models.user import User
from app.schemas.ticket_summary import TicketSummaryRead
from app.services.ticket_summary import compute_ticket_summary

router = APIRouter(
    prefix="/parkings/{parking_id}/tickets",
    tags=["tickets"],
    dependencies=[Depends(parking_context)],
)


@router.get("/summary", response_model=TicketSummaryRead)
def get_tickets_summary(
    parking_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> TicketSummaryRead:
    """KPIs agregados de los últimos 24 h para la sucursal."""
    return compute_ticket_summary(db, parking_id)