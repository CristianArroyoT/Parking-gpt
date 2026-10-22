"""Esquemas de tarifa, plan y suscripción."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class TariffCreate(ORMModel):
    """Alta de tarifa.

    OJO (T-84, 2026-10-22): los importes se validan a proposito. Antes el
    esquema no ponia ni un limite: se aceptaba ``price_per_hour=-5`` (el
    ticket salia con un importe NEGATIVO), ``fraction_minutes=0`` (cerrar
    un ticket petaba con ``ZeroDivisionError`` -> un 500 y el ticket se
    quedaba abierto) y ``max_daily=-1``.
    """

    parking_id: int
    name: str = Field(min_length=2, max_length=64)
    price_per_hour: float = Field(ge=0)
    price_per_fraction: float = Field(ge=0)
    fraction_minutes: int = Field(default=15, gt=0)
    max_daily: Optional[float] = Field(default=None, gt=0)
    valid_from: datetime
    valid_to: Optional[datetime] = None


class TariffUpdate(ORMModel):
    """Patch parcial de una tarifa (todos los campos opcionales)."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=64)
    price_per_hour: Optional[float] = Field(default=None, ge=0)
    price_per_fraction: Optional[float] = Field(default=None, ge=0)
    fraction_minutes: Optional[int] = Field(default=None, gt=0)
    max_daily: Optional[float] = Field(default=None, gt=0)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class TariffRead(TariffCreate, TimestampMixinSchema):
    id: int


class PlanCreate(ORMModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=64)
    monthly_price: float
    discount_percent: float
    included_vehicles: int


class PlanRead(PlanCreate, TimestampMixinSchema):
    id: int
    is_active: bool


class SubscriptionCreate(ORMModel):
    user_id: int
    plan_id: int
    starts_at: datetime
    ends_at: datetime


class SubscriptionRead(SubscriptionCreate, TimestampMixinSchema):
    id: int
    is_active: bool