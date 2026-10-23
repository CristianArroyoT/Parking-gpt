"""Modelo de ticket (entrada / salida de vehículo)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import TicketOrigin, TicketStatus

if TYPE_CHECKING:
    from app.models.parking import Parking, ParkingSpace
    from app.models.vehicle import Vehicle


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        # T-105 (2026-10-23): un vehiculo **no puede tener dos tickets
        # activos** en la misma sucursal, y una plaza **no puede estar
        # ocupada por dos vehiculos**. El codigo lo comprueba antes de
        # insertar (un SELECT), pero eso es un "comprueba y luego hace":
        # dos pushes de la misma matricula a la vez (dos rondas
        # solapadas, o dos peticiones simultaneas) podian pasar las dos
        # comprobaciones y crear DOS tickets activos -> el cliente
        # cobraba dos veces.
        #
        # Con estos indices, la **base de datos** lo prohibe (es lo
        # unico que una carrera no puede saltar) y el codigo captura el
        # rechazo y devuelve el ticket que ya habia.
        #
        # Son indices PARCIALES: solo miran los tickets activos (un
        # vehiculo puede tener cuantos tickets cerrados haga falta).
        Index(
            "uq_tickets_activo_vehiculo",
            "vehicle_id",
            "parking_id",
            unique=True,
            sqlite_where=text("status = 'activo'"),
            postgresql_where=text("status = 'activo'"),
        ),
        Index(
            "uq_tickets_activo_plaza",
            "parking_space_id",
            unique=True,
            sqlite_where=text("status = 'activo' AND parking_space_id IS NOT NULL"),
            postgresql_where=text("status = 'activo' AND parking_space_id IS NOT NULL"),
        ),
    )

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
    origin: Mapped[TicketOrigin] = mapped_column(
        String(16),
        default=TicketOrigin.AUTOMATIC,
        server_default=TicketOrigin.AUTOMATIC.value,
        nullable=False,
        index=True,
    )

    parking: Mapped["Parking"] = relationship()
    vehicle: Mapped["Vehicle"] = relationship()
    parking_space: Mapped["ParkingSpace | None"] = relationship()
