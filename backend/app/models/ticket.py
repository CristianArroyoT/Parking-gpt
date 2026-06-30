"""Modelo de ticket (entrada / salida de vehículo)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import TicketStatus

if TYPE_CHECKING:
    from app.models.parking import Parking, ParkingSpace
    from app.models.vehicle import Vehicle


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parking_space_id: Mapped[int | None] = mapped_column(
        ForeignKey("parking_spaces.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        String(16), default=TicketStatus.ACTIVO, nullable=False, index=True
    )
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    parking: Mapped["Parking"] = relationship()
    vehicle: Mapped["Vehicle"] = relationship()
    parking_space: Mapped["ParkingSpace | None"] = relationship()