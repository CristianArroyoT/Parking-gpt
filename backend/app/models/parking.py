"""Modelos de sucursal, plaza y cámara."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import CameraKind

if TYPE_CHECKING:
    from app.models.user import ParkingMembership


class Parking(Base, TimestampMixin):
    __tablename__ = "parkings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    city: Mapped[str] = mapped_column(String(128), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    spaces: Mapped[list["ParkingSpace"]] = relationship(
        back_populates="parking", cascade="all, delete-orphan"
    )
    cameras: Mapped[list["Camera"]] = relationship(
        back_populates="parking", cascade="all, delete-orphan"
    )
    members: Mapped[list["ParkingMembership"]] = relationship(
        back_populates="parking", cascade="all, delete-orphan"
    )


class ParkingSpace(Base, TimestampMixin):
    __tablename__ = "parking_spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lane: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_broken: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    is_broken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    parking: Mapped[Parking] = relationship(back_populates="spaces")


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    lane_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fps: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Sprint Fase 4 (2026-07-01): distingue cámaras de fiscalización
    # (``surveillance``) vs cámaras de portería (``gate``). Default
    # ``surveillance`` para mantener back-compat con cámaras existentes.
    kind: Mapped[CameraKind] = mapped_column(
        Enum(CameraKind, name="camerakind"),
        default=CameraKind.SURVEILLANCE,
        server_default=CameraKind.SURVEILLANCE.value,
        nullable=False,
        index=True,
    )
    # Sprint Camera Health (2026-07-01): el último probe_heartbeats() deja
    # aquí su resultado. NULL hasta el primer probe (estado "nunca probada").
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    last_heartbeat_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    parking: Mapped[Parking] = relationship(back_populates="cameras")