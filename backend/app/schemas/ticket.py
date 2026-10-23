"""Esquemas de ticket."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, computed_field

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
    origin: TicketOrigin = TicketOrigin.AUTOMATIC

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pdf_available(self) -> bool:
        """¿Hay PDF descargable de este ticket? (T-97)

        Antes la API devolvia ``pdf_path``: la ruta **del disco del
        servidor** (``/tmp/solidapp-tickets/ticket-1.pdf``). Eso no solo
        enseña la estructura de ficheros a quien llama: ademas el
        enlace que hacia el frontend **daba 404**, porque ese fichero
        no lo sirve nadie (vive en el contenedor del backend).

        Ahora el PDF se pide a la API (``GET /tickets/{id}/pdf``), que
        lo genera al vuelo, y aqui solo se dice si lo hay.
        """
        return self.exit_at is not None