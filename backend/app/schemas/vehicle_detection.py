"""Esquemas Pydantic para el detector cenital de vehículos (vehicle-detector).

Sprint 2026-07-07: pre-flight check durante la calibración de geocercas.
El cliente ``app.services.vehicle_detector.client`` envía la imagen
capturada y recibe ``VehicleDetection`` con bbox ya en coordenadas del
viewBox 960x540 del CalibrateView (el backend redimensiona antes de
inferir, ver ``docker/vehicle-detector/app.py``).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class VehicleDetection(BaseModel):
    """Una detección de vehículo devuelta por el servicio YOLO."""

    class_name: str = Field(
        ...,
        description="Etiqueta COCO de la detección: car|truck|bus|motorcycle|bicycle",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: list[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="[x, y, w, h] en píxeles del viewBox 960x540 del SVG",
    )


class DetectVehiclesRequest(BaseModel):
    """Payload de entrada: dataURL o base64 puro del JPEG capturado."""

    image: str = Field(
        ...,
        min_length=1,
        description="dataURL 'data:image/jpeg;base64,...' o base64 puro",
    )


class DetectVehiclesResponse(BaseModel):
    """Respuesta del endpoint ``POST /cameras/{id}/detect-vehicles``."""

    detections: list[VehicleDetection] = Field(default_factory=list)