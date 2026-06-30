"""Esquemas de auditoría y alertas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
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


# ── Incidentes (marcar plaza, reportar robo, rehabilitar) ────────────
class IncidentKind(str, Enum):
    SPACE_BROKEN = "space_broken"
    SPACE_UNBROKEN = "space_unbroken"
    ROBERY_REPORTED = "robery_reported"


class IncidentReason(str, Enum):
    PHYSICAL_DAMAGE = "physical_damage"
    PAINT = "paint"
    SENSOR_FAILURE = "sensor_failure"
    THEFT_ATTEMPT = "theft_attempt"
    SUSPICIOUS_BEHAVIOR = "suspicious_behavior"
    OTHER = "other"


class IncidentCreate(ORMModel):
    """Payload para ``POST /api/v1/parkings/{parking_id}/incidents``.

    - ``space_broken``/``space_unbroken``: requieren ``parking_space_id``.
    - ``robery_reported``: todos los campos opcionales; el operador en vivo
      puede no conocer la matrícula.
    """

    kind: IncidentKind
    parking_space_id: Optional[int] = None
    plate: Optional[str] = Field(default=None, min_length=4, max_length=16)
    reason: IncidentReason
    notes: Optional[str] = Field(default=None, max_length=500)
    photos: list[str] = Field(default_factory=list, max_length=3)


class IncidentRead(AlertRead):
    """Alias semántico sobre AlertRead — un incidente ES un Alert."""
    pass