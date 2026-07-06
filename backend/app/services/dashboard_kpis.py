"""Cálculo de KPIs agregados para el dashboard administrativo.

Sprint UI Costes + Reportería + Dashboard KPIs (2026-07-06).

Aislado del router para que pytest pueda ejercitar la lógica sin
montar el cliente FastAPI completo. Sigue el patrón de
``app/services/ticket_summary.py`` (Fase 4-parte-2) y
``app/services/cost.py`` (Sprint P1).

Decisiones de diseño:

- **``parking_id=None`` = agregado global**. El endpoint expone un
  único KPI de TODAS las sucursales; con ``parking_id`` se filtra a
  una concreta. El cliente siempre recibe el ``parking_id`` efectivo
  en la respuesta para que la UI confirme el alcance.

- **Ventanas móviles hacia atrás desde ``now``** (no desde el último
  ticket). Coherente con ``compute_ticket_summary``. Ventanas
  expuestas: 24 h (día), 7 días (semana), 30 días (mes).

- **``None`` vs ``0``**: para ``revenue``/``costs``, si no hay muestra
  en la ventana → ``None`` (sin datos). Si hay muestra pero la suma
  es 0 → ``0.0``. Mismo patrón que ``TicketSummaryRead``.

- **Plaza "ocupada"**: tickets activos (``status=ACTIVO``) que
  apuntan a una plaza (``parking_space_id IS NOT NULL``). Una plaza
  puede tener varios tickets activos históricos apuntando a ella
  (no debería, pero el esquema lo permite), por eso uso ``DISTINCT``.

- **Costes recurrentes**: reusa ``_cost_applied_to_report`` de
  ``app/services/cost.py`` para mantener una única implementación de
  la regla de prorrateo (Sprint P1). Sin divergencia de fórmula.

- **Performance**: 3 ventanas × 2 métricas × 1 query cada una + 4
  COUNTs simples = ~10 queries en el caso agregado. Para Fase 4-prod
  se cacheará con Redis (sprint I1).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cost import Cost
from app.models.enums import TicketStatus
from app.models.parking import Camera, ParkingSpace
from app.models.ticket import Ticket
from app.schemas.dashboard_kpis import (
    DashboardCamerasRead,
    DashboardKpisRead,
    DashboardMoneyPeriodRead,
    DashboardSpacesRead,
)
from app.services.cost import _cost_applied_to_report


def _money_or_none(amount: float, has_sample: bool) -> float | None:
    """Si hay muestra en la ventana, devuelve ``amount``; si no, ``None``.

    Distingue "0 € facturados con tráfico" de "sin muestra en la
    ventana". El frontend traduce ``None`` como ``—``.
    """
    return amount if has_sample else None


def _revenue_in_window(
    db: Session,
    parking_id: int | None,
    start: datetime,
    end: datetime,
) -> tuple[float, int]:
    """Suma de ingresos y nº de tickets cerrados en el rango.

    Variante de la homónima en ``app/services/cost.py``: esa toma un
    ``parking_id`` obligatorio; aquí se admite ``None`` para el
    agregado global.
    """
    q = db.query(
        func.coalesce(func.sum(Ticket.total), 0.0),
        func.count(Ticket.id),
    ).filter(
        Ticket.status == TicketStatus.CERRADO,
        Ticket.exit_at >= start,
        Ticket.exit_at <= end,
        Ticket.exit_at.isnot(None),
    )
    if parking_id is not None:
        q = q.filter(Ticket.parking_id == parking_id)
    total, count = q.one()
    return float(total or 0.0), int(count or 0)


def _costs_in_window(
    db: Session,
    parking_id: int | None,
    start: datetime,
    end: datetime,
) -> tuple[float, int]:
    """Suma de costes aplicados al rango y nº de costes distintos que
    aportaron al rango.

    Para ``parking_id=None`` agrega TODAS las sucursales.
    """
    q = db.query(Cost)
    if parking_id is not None:
        q = q.filter(Cost.parking_id == parking_id)
    costs = q.all()

    total = 0.0
    contributors = 0
    for cost in costs:
        applied = _cost_applied_to_report(cost, start, end)
        if applied > 0:
            total += applied
            contributors += 1
    return total, contributors


def compute_dashboard_kpis(
    db: Session,
    parking_id: int | None,
    *,
    now: Optional[datetime] = None,
) -> DashboardKpisRead:
    """KPIs administrativos. ``parking_id=None`` agrega TODAS las
    sucursales.

    Args:
        db: sesión SQLAlchemy.
        parking_id: sucursal sobre la que se agrega. ``None`` = global.
        now: reloj de referencia (inyectable en tests). Por defecto
            ``datetime.now(timezone.utc)``.

    Returns:
        ``DashboardKpisRead`` con espacios, cámaras, revenue y costes
        por ventana (día / semana / mes).
    """
    now = now or datetime.now(timezone.utc)
    day_start = now - timedelta(hours=24)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    # ── Spaces ──────────────────────────────────────────────────────
    sp_q = db.query(ParkingSpace)
    if parking_id is not None:
        sp_q = sp_q.filter(ParkingSpace.parking_id == parking_id)
    spaces_total = sp_q.count()
    spaces_broken = (
        sp_q.filter(ParkingSpace.is_broken == True).count()  # noqa: E712
    )

    # Plaza ocupada = ticket activo apuntando a esta plaza. DISTINCT
    # porque el modelo permite (no debería pero puede) varios tickets
    # activos con el mismo parking_space_id.
    occupied_subq = db.query(Ticket.parking_space_id).filter(
        Ticket.status == TicketStatus.ACTIVO,
        Ticket.parking_space_id.isnot(None),
    )
    if parking_id is not None:
        occupied_subq = occupied_subq.filter(Ticket.parking_id == parking_id)
    occupied_subq = occupied_subq.subquery()
    spaces_occupied = (
        db.query(func.count(func.distinct(ParkingSpace.id)))
        .filter(ParkingSpace.id.in_(occupied_subq.select()))
        .scalar()
        or 0
    )
    spaces = DashboardSpacesRead(
        total=spaces_total,
        occupied=int(spaces_occupied),
        free=max(spaces_total - int(spaces_occupied) - spaces_broken, 0),
        broken=spaces_broken,
    )

    # ── Cameras ─────────────────────────────────────────────────────
    cam_q = db.query(Camera)
    if parking_id is not None:
        cam_q = cam_q.filter(Camera.parking_id == parking_id)
    cams_total = cam_q.count()
    cams_op = cam_q.filter(Camera.last_heartbeat_ok == True).count()  # noqa: E712
    cams_alert = cam_q.filter(Camera.last_heartbeat_ok == False).count()  # noqa: E712
    cams_never = cam_q.filter(
        Camera.last_heartbeat_at.is_(None),
        Camera.last_heartbeat_ok.is_(None),
    ).count()
    cameras = DashboardCamerasRead(
        total=cams_total,
        operational=cams_op,
        alert=cams_alert,
        never_probed=cams_never,
    )

    # ── Revenue (3 ventanas) ────────────────────────────────────────
    rev_day, day_count = _revenue_in_window(db, parking_id, day_start, now)
    rev_week, week_count = _revenue_in_window(db, parking_id, week_start, now)
    rev_month, month_count = _revenue_in_window(
        db, parking_id, month_start, now,
    )
    revenue = DashboardMoneyPeriodRead(
        day=_money_or_none(round(rev_day, 2), day_count > 0),
        week=_money_or_none(round(rev_week, 2), week_count > 0),
        month=_money_or_none(round(rev_month, 2), month_count > 0),
    )

    # ── Costs (3 ventanas, prorrateados) ────────────────────────────
    costs_day, day_contrib = _costs_in_window(db, parking_id, day_start, now)
    costs_week, week_contrib = _costs_in_window(db, parking_id, week_start, now)
    costs_month, month_contrib = _costs_in_window(
        db, parking_id, month_start, now,
    )
    costs = DashboardMoneyPeriodRead(
        day=_money_or_none(round(costs_day, 2), day_contrib > 0),
        week=_money_or_none(round(costs_week, 2), week_contrib > 0),
        month=_money_or_none(round(costs_month, 2), month_contrib > 0),
    )

    return DashboardKpisRead(
        parking_id=parking_id,
        spaces=spaces,
        cameras=cameras,
        revenue=revenue,
        costs=costs,
    )


__all__ = ["compute_dashboard_kpis"]