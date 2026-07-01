"""Alta manual de tickets por el operador (ENTRADA / SALIDA).

Replica la lógica del flujo OCR (``app/services/ingest_service.py``) pero
sin geocercas y con motivo explícito:

- ``direction == "entry"``  → crea Ticket activo con ``origin=MANUAL_ENTRY``.
  Valida que el vehículo no esté ya dentro y que la plaza esté libre.
- ``direction == "exit"``   → cierra el ticket activo del vehículo en la
  sucursal con ``origin=MANUAL_EXIT``. Replica el cierre de
  ``ingest_service._close_ticket_for_exit``: tarifa, PDF, plaza libre.

Todo se persiste en una sola transacción junto con un ``AuditLog`` que
registra quién hizo la alta, motivo, cámara y notas. NO modifica
``ingest_service.py`` — el flujo OCR sigue intacto.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.enums import (
    ManualEntryReason,
    TicketOrigin,
    TicketStatus,
)
from app.models.parking import ParkingSpace
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.ticket import TicketManualCreate
from app.services import record_audit
from app.services.pdf import save_ticket_pdf
from app.services.pricing import PricingError, calculate_ticket_total

log = logging.getLogger(__name__)


def _normalize_plate(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def _resolve_vehicle(db: Session, plate: str) -> Vehicle:
    vehicle = db.query(Vehicle).filter(Vehicle.plate == plate).one_or_none()
    if vehicle is not None:
        return vehicle
    vehicle = Vehicle(plate=plate)
    db.add(vehicle)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        vehicle = db.query(Vehicle).filter(Vehicle.plate == plate).one()
    return vehicle


def _find_active_ticket(db: Session, vehicle_id: int, parking_id: int) -> Ticket | None:
    return (
        db.query(Ticket)
        .filter(
            Ticket.vehicle_id == vehicle_id,
            Ticket.parking_id == parking_id,
            Ticket.status == TicketStatus.ACTIVO,
        )
        .first()
    )


def _space_is_occupied(db: Session, parking_space_id: int) -> bool:
    return (
        db.query(Ticket)
        .filter(
            Ticket.parking_space_id == parking_space_id,
            Ticket.status == TicketStatus.ACTIVO,
        )
        .first()
        is not None
    )


def _close_for_manual_exit(db: Session, ticket: Ticket, exit_at: datetime) -> Ticket:
    ticket.exit_at = exit_at
    total = calculate_ticket_total(
        db,
        parking_id=ticket.parking_id,
        vehicle_id=ticket.vehicle_id,
        entry_at=ticket.entry_at,
        exit_at=exit_at,
    )
    ticket.amount = total.amount
    ticket.discount = total.discount
    ticket.total = total.total
    ticket.status = TicketStatus.CERRADO
    ticket.origin = TicketOrigin.MANUAL_EXIT
    db.commit()
    db.refresh(ticket)

    try:
        vehicle = db.get(Vehicle, ticket.vehicle_id)
        ticket.pdf_path = save_ticket_pdf(ticket, vehicle)
        db.commit()
        db.refresh(ticket)
    except Exception as exc:  # noqa: BLE001
        log.warning("manual_tickets: PDF no generado para ticket %s: %s", ticket.id, exc)

    return ticket


def create_manual_ticket(
    payload: TicketManualCreate,
    *,
    current_user: User,
    ip: str | None = None,
) -> Ticket:
    plate = _normalize_plate(payload.plate)
    if not plate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La matrícula no puede estar vacía",
        )

    now = datetime.now(timezone.utc)
    occurred_at = payload.occurred_at or now

    with SessionLocal() as db:
        vehicle = _resolve_vehicle(db, plate)

        if payload.direction == "entry":
            if _find_active_ticket(db, vehicle.id, payload.parking_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="El vehículo ya tiene un ticket activo en esta sucursal",
                )

            if payload.parking_space_id is not None:
                if _space_is_occupied(db, payload.parking_space_id):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La plaza seleccionada ya está ocupada",
                    )
                space = db.get(ParkingSpace, payload.parking_space_id)
                if space is None or space.parking_id != payload.parking_id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="La plaza no pertenece a la sucursal indicada",
                    )
                if space.is_broken:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La plaza está averiada; rehabilítala antes de asignar tickets",
                    )

            ticket = Ticket(
                parking_id=payload.parking_id,
                vehicle_id=vehicle.id,
                parking_space_id=payload.parking_space_id,
                status=TicketStatus.ACTIVO,
                entry_at=occurred_at,
                origin=TicketOrigin.MANUAL_ENTRY,
            )
            db.add(ticket)
            db.flush()  # asigna ticket.id antes del audit
        else:
            ticket = _find_active_ticket(db, vehicle.id, payload.parking_id)
            if ticket is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "El vehículo no tiene un ticket activo en esta sucursal; "
                        "no se puede registrar la salida"
                    ),
                )
            try:
                ticket = _close_for_manual_exit(db, ticket, occurred_at)
            except PricingError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=str(exc)
                ) from exc

        record_audit(
            db,
            action=f"{payload.direction}_manual",
            user_id=current_user.id,
            ip=ip,
            resource=f"ticket:{ticket.id}",
            parking_id=payload.parking_id,
            result="success",
            payload={
                "plate": plate,
                "reason": payload.reason.value
                if hasattr(payload.reason, "value")
                else str(payload.reason),
                "notes": payload.notes,
                "camera_id": payload.camera_id,
                "parking_space_id": payload.parking_space_id,
                "origin": ticket.origin.value
                if hasattr(ticket.origin, "value")
                else str(ticket.origin),
            },
        )
        db.commit()
        db.refresh(ticket)
        log.info(
            "manual_tickets: %s ticket_id=%s plate=%s reason=%s user_id=%s",
            payload.direction,
            ticket.id,
            plate,
            payload.reason,
            current_user.id,
        )
        return ticket


__all__ = ["create_manual_ticket", "ManualEntryReason"]