"""Esquemas Pydantic para el resultado del flujo ENTRADA (ingest OCR → ticket)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IngestResultRead(BaseModel):
    """Espejo Pydantic de ``app.services.ingest_service.IngestResult``.

    Lo devuelve ``POST /api/v1/parkings/{parking_id}/cameras/{camera_id}/plates``
    cuando, además de persistir la fila cruda de ``PlatesDetected``, cruza el
    bbox con las geocercas y crea (o skipea) el ticket correspondiente.
    """

    model_config = ConfigDict(from_attributes=True)

    plate: str
    camera_id: int
    parking_id: int
    status: str
    confidence: float
    ticket_id: int | None = None
    vehicle_id: int | None = None
    parking_space_id: int | None = None
    reason: str | None = None


__all__ = ["IngestResultRead"]