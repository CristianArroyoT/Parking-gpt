"""Cálculo de margen por sucursal (Sprint P1 solidAPP, 2026-07-06).

Aislado del router para que pytest pueda ejercitar la lógica sin
montar el cliente FastAPI completo. Sigue el patrón de
``app/services/ticket_summary.py`` (Fase 4-parte-2).

Decisiones de diseño:

- **Prorrateo por días**: cada coste recurrente (mensual / trimestral /
  anual) se imputa al reporte según los días que su ciclo cae dentro
  del rango ``[from_, to]``. Esto da respuestas estables aunque el
  reporte cubra meses incompletos o varios ciclos a la vez.

- **Aproximación de meses**: usamos duraciones fijas (30 / 90 / 365
  días) en lugar de ``dateutil.relativedelta`` para no añadir una
  dependencia. La imprecisión es despreciable para los KPIs
  operativos del dashboard y deja el código fácil de auditar.

- **PUNTUAL**: si el rango del reporte solapa con ``[period_start,
  period_end]`` del coste, se imputa la fracción ``overlap / total``
  del ``amount``. Sin solape → 0.

- **Ingresos**: ``SUM(ticket.total) WHERE status='cerrado' AND
  exit_at IN [from_, to]``. Tickets sin ``total`` o con ``total=0``
  (anomalía) cuentan como 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cost import Cost
from app.models.enums import CostCategory, CostPeriod, TicketStatus
from app.models.parking import Parking
from app.models.ticket import Ticket
from app.schemas.reports import CostBreakdownEntry, MarginReportRead


# Duraciones en días de cada periodicidad recurrente.
_RECURRING_DAYS: dict[CostPeriod, int] = {
    CostPeriod.MENSUAL: 30,
    CostPeriod.TRIMESTRAL: 90,
    CostPeriod.ANUAL: 365,
}


def _to_aware_utc(dt: datetime) -> datetime:
    """Normaliza un datetime a UTC tz-aware.

    SQLite (BD in-memory de pytest) strip el timezone al guardar un
    ``DateTime(timezone=True)`` y los datetimes vuelven naive. Sin tz
    son incomparables con los ``report_*`` que llegan en UTC aware,
    así que todos los ``cost.*`` los pasamos por aquí antes de
    operar.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _overlap_days(
    cost_start: datetime,
    cost_end: datetime,
    report_start: datetime,
    report_end: datetime,
) -> float:
    """Días solapados entre ``[cost_start, cost_end]`` y ``[report_start,
    report_end]``. Devuelve 0 si no hay solape. Robusto frente a
    rangos vacíos (solape cero)."""
    lo = max(cost_start, report_start)
    hi = min(cost_end, report_end)
    delta = (hi - lo).total_seconds() / 86400.0
    return max(delta, 0.0)


def _shift_days(start: datetime, days: int) -> datetime:
    """Devuelve ``start + days`` días. Wrapper para centralizar conversiones
    y facilitar mocking en tests."""
    return start + timedelta(days=days)


def _cost_applied_to_report(
    cost: Cost,
    report_start: datetime,
    report_end: datetime,
) -> float:
    """Importe del coste que se imputa al reporte, ya prorrateado."""
    # Normalizamos: SQLite strip el tz al guardar DateTime(timezone=True),
    # y los datetimes vuelven naive. Sin tz son incomparables con los
    # ``report_*`` que llegan en UTC aware.
    cost_start = _to_aware_utc(cost.period_start)
    cost_end = (
        _to_aware_utc(cost.period_end) if cost.period_end is not None else None
    )
    if cost.periodicity is CostPeriod.PUNTUAL:
        if cost_end is None:
            # Defensivo: si llega aquí un PUNTUAL sin period_end es un
            # bug en el validador del schema; no imputamos.
            return 0.0
        total_days = (cost_end - cost_start).total_seconds() / 86400.0
        if total_days <= 0:
            return 0.0
        overlap = _overlap_days(
            cost_start, cost_end, report_start, report_end,
        )
        return cost.amount * (overlap / total_days)

    # Recurrente (MENSUAL / TRIMESTRAL / ANUAL): se itera hacia adelante
    # desde period_start sumando el solape de cada ciclo con el rango
    # del reporte. Acotamos por seguridad a 3650 días (10 años × 365)
    # para que un coste mal dado no nos haga iterar al infinito.
    cycle = _RECURRING_DAYS[cost.periodicity]
    per_day = cost.amount / float(cycle)
    cursor = cost_start
    accumulated = 0.0
    for _ in range(3650):
        if cursor >= report_end:
            break
        cycle_end = _shift_days(cursor, cycle)
        overlap = _overlap_days(cursor, cycle_end, report_start, report_end)
        accumulated += per_day * overlap
        cursor = cycle_end
    return accumulated


def _revenue_in_window(
    db: Session, parking_id: int, report_start: datetime, report_end: datetime,
) -> tuple[float, int]:
    """Suma de ingresos y nº de tickets cerrados en el rango."""
    q = db.query(func.coalesce(func.sum(Ticket.total), 0.0), func.count(Ticket.id)).filter(
        Ticket.parking_id == parking_id,
        Ticket.status == TicketStatus.CERRADO,
        Ticket.exit_at >= report_start,
        Ticket.exit_at <= report_end,
        Ticket.exit_at.isnot(None),
    )
    total, count = q.one()
    return float(total or 0.0), int(count or 0)


def _costs_breakdown(
    costs: Iterable[Cost],
    report_start: datetime,
    report_end: datetime,
) -> tuple[dict[CostCategory, list[float]], dict[CostCategory, int], float]:
    """Aplica cada coste al reporte y agrupa por categoría.

    Devuelve tres estructuras:
      - ``amounts``: importe aplicado por categoría.
      - ``counts``: nº de costes distintos que aportaron a cada categoría.
      - ``total``: suma global.

    Se itera en Python para mantener el prorrateo simple y porque el
    número de costes por sucursal es bajo (decenas, no miles).
    """
    amounts: dict[CostCategory, list[float]] = {}
    counts: dict[CostCategory, int] = {}
    for cost in costs:
        applied = _cost_applied_to_report(cost, report_start, report_end)
        if applied <= 0:
            continue
        amounts.setdefault(cost.category, []).append(applied)
        counts[cost.category] = counts.get(cost.category, 0) + 1
    total = sum(sum(v) for v in amounts.values())
    return amounts, counts, total


def compute_margin(
    db: Session,
    parking_id: int,
    *,
    from_: datetime,
    to: datetime,
) -> MarginReportRead:
    """Calcula el reporte de margen para una sucursal y un rango.

    Si ``to < from_`` el reporte viene vacío (ingresos y costes a 0).
    Esto evita 500s si el cliente envía filtros sin sentido.
    """
    parking = db.get(Parking, parking_id)
    parking_name = parking.name if parking else ""

    # Normalizamos a UTC para evitar sorpresas si el cliente manda
    # datetimes naive.
    if from_.tzinfo is None:
        from_ = from_.replace(tzinfo=timezone.utc)
    if to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)

    if to < from_:
        return MarginReportRead.model_validate({
            "parking_id": parking_id,
            "parking_name": parking_name,
            "from": from_,
            "to": to,
            "total_revenue": 0.0,
            "closed_tickets": 0,
            "total_costs": 0.0,
            "margin": 0.0,
            "cost_breakdown": [],
        })

    revenue, closed = _revenue_in_window(db, parking_id, from_, to)

    costs = (
        db.query(Cost)
        .filter(Cost.parking_id == parking_id)
        .all()
    )
    amounts, counts, total_costs = _costs_breakdown(costs, from_, to)

    breakdown = [
        CostBreakdownEntry(
            category=cat,
            amount=round(sum(values), 2),
            cost_count=counts[cat],
        )
        for cat, values in sorted(amounts.items(), key=lambda kv: kv[0].value)
    ]

    return MarginReportRead.model_validate({
        "parking_id": parking_id,
        "parking_name": parking_name,
        "from": from_,
        "to": to,
        "total_revenue": round(revenue, 2),
        "closed_tickets": closed,
        "total_costs": round(total_costs, 2),
        "margin": round(revenue - total_costs, 2),
        "cost_breakdown": breakdown,
    })


__all__ = [
    "compute_margin",
    "_cost_applied_to_report",
    "_to_aware_utc",
    "_RECURRING_DAYS",
]