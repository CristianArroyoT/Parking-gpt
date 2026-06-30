"""Esquemas de tarifa, plan y suscripción."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class TariffCreate(ORMModel):
    parking_id: int
    name: str = Field(min_length=2, max_length=64)
    price_per_hour: float
    price_per_fraction: float
    fraction_minutes: int = 15
    max_daily: Optional[float] = None
    valid_from: datetime
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