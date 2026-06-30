"""Esquemas de ticket."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class TicketCreate(ORMModel):
    parking_id: int
    vehicle_id: int
    parking_space_id: Optional[int] = None
    entry_at: datetime


class TicketClose(ORMModel):
    exit_at: Optional[datetime] = None
    payment_method: Optional[str] = None


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