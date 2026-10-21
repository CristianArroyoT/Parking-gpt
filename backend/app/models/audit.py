"""Modelo de auditoría y alertas del sistema."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import AlertSeverity, AlertType

if TYPE_CHECKING:
    from app.models.parking import Parking
    from app.models.user import User


class AuditLog(Base, TimestampMixin):
    """Registro exhaustivo de operaciones sensibles. Retención 1 año."""

    __tablename__ = "audit_logs"

    # Índices que las migraciones 0007 y 0008 crearon a propósito (son
    # consultas de auditoría por usuario y por fecha) y que el modelo no
    # declaraba: ``alembic check`` los veía como índices "de más" en la
    # base de datos y quería borrarlos al autogenerar. Declararlos aquí
    # deja el modelo y el esquema de acuerdo.
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    resource: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Sprint Fase 3A (2026-07-01): 4 columnas para correlación forense y
    # filtrado por sucursal. Registros históricos (anteriores a esta
    # migración) quedan con NULL en estos campos.
    parking_id: Mapped[int | None] = mapped_column(
        ForeignKey("parkings.id", ondelete="SET NULL"), index=True, nullable=True,
    )
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )

    user: Mapped["User | None"] = relationship()


class Alert(Base, TimestampMixin):
    """Alertas operativas: OCR fallido, cámara caída, plaza averiada, etc."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[AlertType] = mapped_column(String(32), index=True, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        String(16), default=AlertSeverity.WARN, nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # T-21 (2026-10-21): usuario que reportó el incidente. Las alertas
    # del sistema (cámara caída, OCR fallido…) lo tienen a NULL.
    # ON DELETE CASCADE: al borrar el usuario se borra su incidente y,
    # en cascada, sus fotos adjuntas (derecho al olvido, LOPDGDD).
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )

    parking: Mapped["Parking"] = relationship()