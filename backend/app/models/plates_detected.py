"""Modelo: detecciones de matrículas persistidas tras una llamada a OCR.

Una fila por matrícula encontrada en un frame. Se conserva el `raw_response`
del servicio OCR por si en el futuro hay que recalcular geocercas o depurar
confianzas bajas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.parking import Camera


class PlatesDetected(Base, TimestampMixin):
    """Resultado de una llamada al servicio OCR sobre un frame."""

    __tablename__ = "plates_detected"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plate: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x1: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y1: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_x2: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y2: Mapped[int] = mapped_column(Integer, nullable=False)
    # Momento en que el OCR dijo haber visto la matrícula. Se setea desde
    # la app (no server_default) para que sea determinista en tests y
    # para que coincida con la lógica de negocio, no con el reloj de la BD.
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    camera: Mapped["Camera"] = relationship()