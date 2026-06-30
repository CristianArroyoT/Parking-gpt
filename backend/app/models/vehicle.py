"""Modelos de vehículo y asociación N:M con usuarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import VehicleRole

if TYPE_CHECKING:
    from app.models.user import User


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    users: Mapped[list["VehicleUser"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )


class VehicleUser(Base, TimestampMixin):
    __tablename__ = "vehicle_users"
    __table_args__ = (UniqueConstraint("vehicle_id", "user_id", "role", name="uq_vehicle_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[VehicleRole] = mapped_column(
        String(16), default=VehicleRole.PROPIETARIO, nullable=False
    )

    vehicle: Mapped[Vehicle] = relationship(back_populates="users")
    user: Mapped["User"] = relationship()