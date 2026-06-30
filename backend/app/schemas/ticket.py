"""Esquemas de ticket."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field

from app.models.enums import ManualEntryReason, TicketOrigin
from app.schemas import ORMModel, TimestampMixinSchema


class TicketCreate(ORMModel):
    parking_id: int
    vehicle_id: int
    parking_space_id: Optional[int] = None
    entry_at: datetime


class TicketClose(ORMModel):
    exit_at: Optional[datetime] = None
    payment_method: Optional[str] = None


class TicketManualCreate(ORMModel):
    """Payload para alta manual del operador.

    El backend resuelve el vehículo a partir de la matrícula (lookup o
    auto-create con manejo de race). La plaza puede omitirse si el parking
    no usa plazas físicas identificadas.
    """

    plate: str = Field(min_length=4, max_length=16, description="Matrícula del vehículo")
    direction: Literal["entry", "exit"]
    parking_id: int
    parking_space_id: Optional[int] = None
    reason: ManualEntryReason
    notes: Optional[str] = Field(default=None, max_length=500)
    camera_id: Optional[int] = None
    occurred_at: Optional[datetime] = None


class TicketRead(TimestampMixinSchema):
    id: int
    parking_id: int
    vehicle_id: int
    parking_space_id: Optional[int]
    status: str
    entry_at: datetime
    exit_at: Optional[datetime]
    amount: Optional[float]
    discount: Optional[float]
    total: Optional[float]
    payment_method: Optional[str]
    pdf_path: Optional[str] = None
    origin: TicketOrigin = TicketOrigin.AUTOMATIC