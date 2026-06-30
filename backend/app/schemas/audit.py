"""Esquemas de auditoría y alertas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class AuditLogCreate(ORMModel):
    user_id: Optional[int] = None
    ip: Optional[str] = None
    action: str = Field(min_length=2, max_length=128)
    resource: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    confidence: Optional[float] = None


class AuditLogRead(AuditLogCreate, TimestampMixinSchema):
    id: int


class AlertCreate(ORMModel):
    parking_id: int
    type: str
    severity: str = "warn"
    message: str
    context: Optional[dict[str, Any]] = None


class AlertRead(AlertCreate, TimestampMixinSchema):
    id: int
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[int] = None