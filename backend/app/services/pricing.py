"""Cálculo de tarifa al cerrar un ticket.

Algoritmo MVP:
 1. Buscar la tarifa vigente de la sucursal en el momento de la entrada.
 2. Sumar horas completas + fracciones extra (redondeo al alza).
 3. Aplicar tope diario (max_daily) si existe.
 4. Si el vehículo está vinculado a un usuario con suscripción activa,
    aplicar el mayor `discount_percent` de entre los planes activos.
 5. Devolver (amount, discount, total).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.pricing import Plan, Subscription, Tariff
from app.models.vehicle import Vehicle, VehicleUser


class PricingError(ValueError):
    """No se puede calcular la tarifa (ej. sin tarifa vigente)."""


@dataclass(frozen=True)
class TicketTotal:
    amount: float
    discount: float
    total: float


def calculate_ticket_total(
    db: Session,
    *,
    parking_id: int,
    vehicle_id: int,
    entry_at: datetime,
    exit_at: datetime,
) -> TicketTotal:
    """Calcula el importe a cobrar al cerrar un ticket.

    Lanza ``PricingError`` si no hay tarifa aplicable o si la salida
    no es posterior a la entrada. Acepta datetimes naive o aware;
    los naive se interpretan como Europe/Madrid (configurado en Celery).
    """
    entry_at = _ensure_aware(entry_at)
    exit_at = _ensure_aware(exit_at)
    if exit_at <= entry_at:
        raise PricingError("La salida debe ser posterior a la entrada")

    tariff = _find_tariff(db, parking_id=parking_id, at=entry_at)
    if tariff is None:
        raise PricingError(
            f"No hay tarifa vigente para la sucursal {parking_id} en {entry_at.isoformat()}"
        )

    amount = _compute_amount(tariff, entry_at, exit_at)
    discount = _compute_discount(db, vehicle_id=vehicle_id, at=exit_at, amount=amount)
    total = round(amount - discount, 2)
    return TicketTotal(amount=round(amount, 2), discount=round(discount, 2), total=total)


# ── Internos ──────────────────────────────────────────────────────────
def _find_tariff(db: Session, *, parking_id: int, at: datetime) -> Tariff | None:
    """Devuelve la tarifa vigente en `at`. Si hay varias, toma la más reciente."""
    return (
        db.query(Tariff)
        .filter(
            Tariff.parking_id == parking_id,
            Tariff.valid_from <= at,
            or_(Tariff.valid_to.is_(None), Tariff.valid_to >= at),
        )
        .order_by(Tariff.valid_from.desc())
        .first()
    )


def _compute_amount(tariff: Tariff, entry_at: datetime, exit_at: datetime) -> float:
    elapsed_min = (exit_at - entry_at).total_seconds() / 60
    if elapsed_min <= 0:
        return 0.0
    full_hours = int(elapsed_min // 60)
    remainder_min = elapsed_min - full_hours * 60
    fractions = math.ceil(remainder_min / tariff.fraction_minutes) if remainder_min > 0 else 0
    amount = full_hours * tariff.price_per_hour + fractions * tariff.price_per_fraction
    if tariff.max_daily is not None:
        # Cap diario MVP: tope por estancia. Multi-día natural se desglosa
        # en Fase 3 cuando llegue la auditoría de tickets.
        amount = min(amount, tariff.max_daily)
    return amount


def _compute_discount(
    db: Session, *, vehicle_id: int, at: datetime, amount: float
) -> float:
    """Mayor porcentaje de descuento entre las suscripciones activas vinculadas al vehículo."""
    rows = (
        db.query(Subscription, Plan)
        .join(VehicleUser, VehicleUser.user_id == Subscription.user_id)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(
            VehicleUser.vehicle_id == vehicle_id,
            Subscription.is_active.is_(True),
            Plan.is_active.is_(True),
            Subscription.starts_at <= at,
            Subscription.ends_at >= at,
        )
        .all()
    )
    if not rows or amount <= 0:
        return 0.0
    best_pct = max(plan.discount_percent for _, plan in rows)
    return amount * (best_pct / 100.0)


def is_vehicle_known(db: Session, vehicle_id: int) -> bool:
    return db.query(Vehicle.id).filter(Vehicle.id == vehicle_id).first() is not None


def _ensure_aware(dt: datetime) -> datetime:
    """Si el datetime es naive, lo marca como UTC.

    Los datetimes persistidos en PostgreSQL llegan como aware (TIMESTAMPTZ),
    pero los payloads Pydantic desde el cliente llegan como ISO strings
    que Pydantic v2 interpreta como naive. Normalizamos aquí.
    """
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


__all__ = [
    "PricingError",
    "TicketTotal",
    "calculate_ticket_total",
    "is_vehicle_known",
    "_ensure_aware",
]


__all__ = [
    "PricingError",
    "TicketTotal",
    "calculate_ticket_total",
    "is_vehicle_known",
]