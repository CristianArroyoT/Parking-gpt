"""Geocercas (rectángulos cámara↔plaza)."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class CameraGeofence(Base, TimestampMixin):
    """Asociación 1-a-N entre cámara y plaza con rectángulo calibrado (en píxeles)."""

    __tablename__ = "camera_geofences"
    __table_args__ = (UniqueConstraint("camera_id", "parking_space_id", name="uq_camera_space"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parking_space_id: Mapped[int] = mapped_column(
        ForeignKey("parking_spaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)