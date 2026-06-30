"""Endpoints de tickets (Fase 1: CRUD básico, sin OCR ni cálculo de tarifa)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Query as SAQuery
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Ticket
from app.models.user import ParkingMembership, User
from app.schemas.ticket import TicketClose, TicketCreate, TicketRead
from app.services.pricing import PricingError, calculate_ticket_total

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _scoped_query(db: Session, user: User, parking_id: Optional[int]) -> SAQuery[Ticket]:
    query = db.query(Ticket)
    if user.role != UserRole.ADMIN:
        ids = [
            m.parking_id
            for m in db.query(ParkingMembership)
            .filter(ParkingMembership.user_id == user.id)
            .all()
        ]
        query = query.filter(Ticket.parking_id.in_(ids))
    if parking_id is not None:
        query = query.filter(Ticket.parking_id == parking_id)
    return query


@router.get("", response_model=list[TicketRead])
def list_tickets(
    parking_id: Optional[int] = Query(default=None),
    only_active: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Ticket]:
    query = _scoped_query(db, user, parking_id)
    if only_active:
        query = query.filter(Ticket.status == TicketStatus.ACTIVO)
    return query.order_by(Ticket.entry_at.desc()).limit(200).all()


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Ticket:
    if user.role == UserRole.CLIENTE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los clientes no crean tickets manualmente",
        )
    ticket = Ticket(**payload.model_dump(), status=TicketStatus.ACTIVO)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Ticket:
    ticket = _scoped_query(db, user, None).filter(Ticket.id == ticket_id).one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return ticket


@router.post("/{ticket_id}/close", response_model=TicketRead)
def close_ticket(
    ticket_id: int,
    payload: TicketClose,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Ticket:
    ticket = _scoped_query(db, user, None).filter(Ticket.id == ticket_id).one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    if ticket.status != TicketStatus.ACTIVO:
        raise HTTPException(status_code=409, detail="El ticket no está activo")
    ticket.exit_at = payload.exit_at or datetime.now(timezone.utc)
    try:
        total = calculate_ticket_total(
            db,
            parking_id=ticket.parking_id,
            vehicle_id=ticket.vehicle_id,
            entry_at=ticket.entry_at,
            exit_at=ticket.exit_at,
        )
    except PricingError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    ticket.amount = total.amount
    ticket.discount = total.discount
    ticket.total = total.total
    ticket.status = TicketStatus.CERRADO
    ticket.payment_method = payload.payment_method
    db.commit()
    db.refresh(ticket)

    # Generar PDF de justificante. Si ReportLab fallase (raro en prod),
    # dejamos el ticket cerrado igualmente; sólo logueamos.
    try:
        vehicle = db.get(Vehicle, ticket.vehicle_id)
        ticket.pdf_path = save_ticket_pdf(ticket, vehicle)
        db.commit()
        db.refresh(ticket)
    except Exception:  # pragma: no cover - defensivo
        import logging
        logging.getLogger(__name__).exception("No se pudo generar el PDF del ticket %s", ticket.id)

    return ticket