"""Esquemas Pydantic para el cliente OCR y la tabla plates_detected."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlateHit(BaseModel):
    """Un solo hit devuelto por el servicio OCR (PaddleOCR)."""

    plate: str = Field(..., min_length=1, max_length=16)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: list[int] = Field(..., min_length=4, max_length=4)


class PlateDetectedRead(BaseModel):
    """Lectura de una fila persistida en plates_detected."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    plate: str
    confidence: float
    bbox_x1: int
    bbox_y1: int
    bbox_x2: int
    bbox_y2: int
    detected_at: datetime
    created_at: datetime


class PlateDetectedCreate(BaseModel):
    """Payload para que el gestor/test empuje manualmente resultados OCR."""

    hits: list[PlateHit] = Field(default_factory=list, max_length=50)