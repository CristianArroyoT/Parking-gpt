"""Cálculo del resumen operativo de tickets por sucursal.

Sprint Fase 4-parte-2 (2026-07-06). Aislado del router para que pytest
pueda ejercitar la lógica sin montar el cliente FastAPI completo.

Decisiones de diseño:

- La ventana móvil es **24 h hacia atrás desde ``now``** (no desde el
  último ticket). Coherente con el placeholder del dashboard.
- ``active_tickets_now`` NO aplica ventana temporal: refleja la ocupación
  en el instante de la consulta (un ticket puede llevar activo 3 días y
  debe contar).
- ``cancelled_tickets_24h`` usa ``updated_at`` porque ``Ticket`` no
  tiene ``cancelled_at``. Aceptable: las cancelaciones siempre
  actualizan el row (status + updated_at) en el mismo commit.
- Si no hay tickets en ventana → revenue y avg devuelven ``None``
  (no 0.0) para que el frontend distinga "sin muestra" de "0 € facturado".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.schemas.ticket_summary import TicketSummaryRead

_WINDOW_HOURS = 24


def _window_start(now: datetime) -> datetime:
    return now - timedelta(hours=_WINDOW_HOURS)


def compute_ticket_summary(db: Session, parking_id: int, *, now: Optional[datetime] = None) -> TicketSummaryRead:
    """Calcula los KPIs de la sucursal en ventana móvil de 24 h.

    Args:
        db: sesión SQLAlchemy.
        parking_id: sucursal sobre la que se agrega.
        now: reloj de referencia (inyectable en tests). Por defecto
            ``datetime.now(timezone.utc)``.

    Returns:
        ``TicketSummaryRead`` con los 7 campos del schema. ``None`` en
        revenue/avg si no hay muestra.
    """
    now = now or datetime.now(timezone.utc)
    window_start = _window_start(now)

    base = db.query(Ticket).filter(Ticket.parking_id == parking_id)

    # 1) Tickets totales creados en últimos 24 h.
    total_24h = base.filter(Ticket.entry_at >= window_start).count()

    # 2) Activos ahora (sin filtro temporal).
    active_now = base.filter(Ticket.status == TicketStatus.ACTIVO).count()

    # 3) Cerrados en últimos 24 h.
    closed_24h = base.filter(
        Ticket.status == TicketStatus.CERRADO,
        Ticket.exit_at >= window_start,
    ).count()

    # 4) Anulados en últimos 24 h (proxy: updated_at en ventana porque el
    # modelo Ticket no tiene ``cancelled_at``; las anulaciones siempre
    # actualizan el row en el mismo commit).
    cancelled_24h = base.filter(
        Ticket.status == TicketStatus.ANULADO,
        Ticket.updated_at >= window_start,
    ).count()

    # 5) Revenue = SUM(total) sobre cerrados en ventana.
    #    Sin muestra → ``None`` (no 0.0) para que el frontend distinga
    #    "0 € facturados" de "sin datos".
    if closed_24h == 0:
        revenue_value: float | None = None
    else:
        revenue = db.query(func.sum(Ticket.total)).filter(
            Ticket.parking_id == parking_id,
            Ticket.status == TicketStatus.CERRADO,
            Ticket.exit_at >= window_start,
        ).scalar()
        revenue_value = float(revenue) if revenue is not None else None

    # 6) Duración media en minutos sobre cerrados en ventana.
    #    Calculamos en segundos vía epoch y luego /60 — evita unidades
    #    ambiguas que dependen del dialect (SQLite vs Postgres).
    duration_seconds = func.strftime("%s", Ticket.exit_at) - func.strftime("%s", Ticket.entry_at)
    avg_row = db.query(func.avg(duration_seconds)).filter(
        Ticket.parking_id == parking_id,
        Ticket.status == TicketStatus.CERRADO,
        Ticket.exit_at >= window_start,
        Ticket.exit_at.isnot(None),
        Ticket.entry_at.isnot(None),
    ).scalar()
    if avg_row is None:
        avg_minutes: float | None = None
    else:
        avg_minutes = round(float(avg_row) / 60.0, 2)

    return TicketSummaryRead(
        total_tickets_24h=total_24h,
        active_tickets_now=active_now,
        closed_tickets_24h=closed_24h,
        cancelled_tickets_24h=cancelled_24h,
        total_revenue_24h=revenue_value,
        average_duration_minutes=avg_minutes,
        window_hours=_WINDOW_HOURS,
    )


__all__ = ["compute_ticket_summary", "_WINDOW_HOURS"]