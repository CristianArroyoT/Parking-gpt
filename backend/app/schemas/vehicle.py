"""Esquemas de vehículo y asociación."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class VehicleCreate(ORMModel):
    plate: str = Field(min_length=4, max_length=16)
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None


class VehicleUpdate(ORMModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None


class VehicleRead(ORMModel, TimestampMixinSchema):
    id: int
    plate: str
    brand: Optional[str]
    model: Optional[str]
    color: Optional[str]
    vehicle_type: Optional[str]


class VehicleUserCreate(ORMModel):
    user_id: int
    role: str = "propietario"


class VehicleUserRead(TimestampMixinSchema):
    id: int
    vehicle_id: int
    user_id: int
    role: str