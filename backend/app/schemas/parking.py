"""Esquemas de sucursal, plaza, cámara y geocerca."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field

from app.models.enums import GeofenceDirection
from app.schemas import ORMModel, TimestampMixinSchema


class ParkingBase(ORMModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=255)
    address: str = Field(min_length=2, max_length=512)
    city: str = Field(min_length=2, max_length=128)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: bool = True


class ParkingCreate(ParkingBase):
    pass


class ParkingUpdate(ORMModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: Optional[bool] = None


class ParkingRead(ParkingBase, TimestampMixinSchema):
    id: int


class ParkingSpaceCreate(ORMModel):
    lane: str = Field(min_length=1, max_length=8)
    number: str = Field(min_length=1, max_length=16)
    notes: Optional[str] = None


class ParkingSpaceUpdate(ORMModel):
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class ParkingSpaceRead(ORMModel, TimestampMixinSchema):
    id: int
    parking_id: int
    lane: str
    number: str
    is_active: bool
    notes: Optional[str]
    is_broken: bool
    is_broken_at: Optional[datetime]


class CameraCreate(ORMModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=128)
    rtsp_url: str = Field(min_length=8, max_length=1024)
    lane_hint: Optional[str] = None
    fps: int = 10


class CameraUpdate(ORMModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    lane_hint: Optional[str] = None
    fps: Optional[int] = None
    is_active: Optional[bool] = None


class CameraRead(TimestampMixinSchema):
    id: int
    parking_id: int
    code: str
    name: str
    rtsp_url: str
    lane_hint: Optional[str]
    fps: int
    is_active: bool


class GeofenceCreate(ORMModel):
    parking_space_id: int
    x: float
    y: float
    w: float
    h: float
    confidence_threshold: float = 0.85
    direction: GeofenceDirection = GeofenceDirection.ENTRY


class GeofenceUpdate(ORMModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    confidence_threshold: Optional[float] = None
    direction: Optional[GeofenceDirection] = None


class GeofenceRead(GeofenceCreate, TimestampMixinSchema):
    id: int
    camera_id: int


# ── Camera Health (sprint 2026-07-01) ────────────────────────────────
# Estado de salud derivable de ``Camera.last_heartbeat_at`` +
# ``Camera.last_heartbeat_ok`` + ``alerts._redis_client.get(...)``.
# Schema separado (no extiende ``CameraRead``) para evitar acoplar el CRUD
# de cámara al endpoint de monitorización: cualquiera de los dos puede
# evolucionar sin tocar al otro.
class CameraHealthRead(ORMModel):
    """Salud de una cámara: estado derivado de su último probe_heartbeats.

    Estados posibles:
      - ``never_probed``: ambos campos NULL (cámara recién creada o
        desactivada por más de una ronda del beat).
      - ``healthy``: ``last_heartbeat_ok=True`` y la edad del último probe
        ≤ ``stale_threshold_seconds``.
      - ``degraded``: ``last_heartbeat_ok=True`` pero el probe es antiguo
        (probablemente el worker se quedó colgado).
      - ``offline``: ``last_heartbeat_ok=False`` en el último probe.

    ``consecutive_failures`` se lee de Redis con fallback a 0 si Redis
    no responde (no queremos un 500 por monitorización caída).
    """

    camera_id: int
    status: Literal["never_probed", "healthy", "degraded", "offline"]
    last_heartbeat_at: Optional[datetime]
    last_heartbeat_ok: Optional[bool]
    consecutive_failures: int
    stale_threshold_seconds: int