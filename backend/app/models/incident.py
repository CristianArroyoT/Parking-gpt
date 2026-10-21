"""Modelo de los ADJUNTOS de un incidente (T-21, plan maestro 2026-10-21).

Un incidente ES un ``Alert`` (ver ``app/services/incidents.py``): no hay
tabla paralela de incidentes. Este modelo guarda **sólo la metadata** de
las fotos adjuntas:

- ``original_filename``: nombre que subió el operador (saneado).
- ``content_hash``: SHA-256 del contenido. El **nombre del fichero en
  disco se deriva de este hash**, así el volumen no filtra el nombre
  original y dos subidas del mismo fichero comparten fichero (dedup).
- ``mime_type``: tipo **verificado por los bytes** del fichero, no el
  que declara el cliente.
- ``size_bytes`` y ``storage_path`` / ``thumbnail_path``: rutas relativas
  dentro del volumen local.

El binario **NO** se guarda en la base de datos (ni como bytea, ni como
base64): vive en el volumen local. En la BD queda la metadata y las
claves foráneas que permiten el borrado en cascada (derecho al olvido).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class IncidentAttachment(Base, TimestampMixin):
    """Metadata de una foto adjunta a un incidente.

    Borrado en cascada:

    - ``alert_id`` → si se borra el incidente, se borran sus fotos.
    - ``parking_id`` → si se borra la sucursal, se borran sus fotos.
    - ``uploaded_by`` → si se borra el usuario (derecho al olvido), se
      borran las fotos que subió. Además ``app/services/incident_attachments.py``
      limpia los ficheros del disco en ese mismo borrado (el ``ON DELETE
      CASCADE`` de la BD no toca el volumen).
    """

    __tablename__ = "incident_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Rutas RELATIVAS al directorio del volumen: guardar la ruta
    # absoluta ataría la base de datos a un host concreto.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Fin de la retención (LOPDGDD). Lo calcula el servicio al crear la
    # foto; si está a NULL se usa la retención global por defecto.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


__all__ = ["IncidentAttachment"]
