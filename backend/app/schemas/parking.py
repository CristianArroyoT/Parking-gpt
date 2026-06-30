"""Esquemas de sucursal, plaza, cámara y geocerca."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

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


class GeofenceUpdate(ORMModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    confidence_threshold: Optional[float] = None


class GeofenceRead(GeofenceCreate, TimestampMixinSchema):
    id: int
    camera_id: int