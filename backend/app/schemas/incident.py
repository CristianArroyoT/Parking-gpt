"""Esquemas Pydantic de los ADJUNTOS de incidentes (T-21).

El binario de la foto **nunca** viaja en la API: la respuesta del
endpoint de subida lleva sólo la metadata y las URLs de la miniatura y
de la descarga. El cliente baja el fichero con el token de acceso.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas import ORMModel


class IncidentAttachmentRead(ORMModel):
    """Metadata de una foto adjunta (lo que ve el gestor/admin)."""

    id: int
    alert_id: int
    parking_id: int
    uploaded_by: int
    original_filename: str
    content_hash: str
    mime_type: str
    size_bytes: int
    # Rutas relativas al prefijo /api/v1. El frontend les añade el token
    # de acceso (?token=...) porque un <img> no puede mandar cabeceras.
    thumbnail_url: str
    download_url: str
    # Fin de la retención de la foto (LOPDGDD). None = retención global.
    expires_at: Optional[datetime] = None
    created_at: datetime


class IncidentAttachmentUploadRead(ORMModel):
    """Resultado de una subida (una fila por fichero aceptado)."""

    attachments: list[IncidentAttachmentRead]
    rejected: list[str] = []


__all__ = ["IncidentAttachmentRead", "IncidentAttachmentUploadRead"]
