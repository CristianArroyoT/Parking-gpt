"""Modelos de usuario y asociación a sucursales."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.parking import Parking


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(32), default=UserRole.CLIENTE, nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Sprint hardening R6 (2026-07-06): service accounts (p.ej. cronjobs
    # de carga inicial de datos) pueden saltarse el rate-limit de CRUDs
    # sin tener que cambiar settings globales. Default False.
    no_rate_limit: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
    )

    memberships: Mapped[list["ParkingMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ParkingMembership(Base, TimestampMixin):
    __tablename__ = "parking_memberships"
    __table_args__ = (UniqueConstraint("user_id", "parking_id", name="uq_user_parking"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role_in_parking: Mapped[UserRole] = mapped_column(
        String(32), default=UserRole.GESTOR, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    parking: Mapped["Parking"] = relationship(back_populates="members")