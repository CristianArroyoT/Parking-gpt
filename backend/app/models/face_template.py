"""Plantilla de reconocimiento facial (T-23 · plan maestro 2026-10-21).

.. warning::

   **El reconocimiento facial está FUERA DEL MVP.**

   Esta tabla y sus endpoints son sólo la **estructura preparada**:
   el endpoint de alta/baja está deshabilitado por feature flag
   (``FACE_TEMPLATES_ENABLED``, por defecto ``false`` → el router
   responde ``404``) y **el login NO usa estos datos para autenticar a
   nadie**. El acceso sigue siendo exclusivamente usuario + contraseña.

Decisiones de diseño:

- ``embedding`` guarda el vector de características como **JSON** (lista de
  floats). Es la forma menos atada a un motor concreto: cuando se implemente
  el reconocimiento real (fuera del MVP) se puede migrar a
  ``LargeBinary``/pgvector sin reescribir la API.
- ``dimension`` guarda la longitud del vector: permite validar en el
  futuro que todos los templates de una instalación usen el mismo modelo.
- ``camera_id`` es **informativo**: registra de qué cámara se obtuvo el
  template. Si la cámara se da de baja, el template se conserva
  (``ON DELETE SET NULL``) porque el dato biométrico sigue siendo válido.
- El vector **NO es un dato de autenticación**: es un dato biométrico
  (LOPDGDD/GDPR). Cuando esto se active, habrá que documentar su base
  legal y su retención.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.parking import Camera
    from app.models.user import User


class FaceTemplate(Base, TimestampMixin):
    """Template biométrico de un usuario (estructura preparada, sin uso)."""

    __tablename__ = "face_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    #: Vector de características (lista de floats) en formato JSON.
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    #: Longitud del vector (``len(embedding)``).
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship()
    camera: Mapped["Camera | None"] = relationship()


__all__ = ["FaceTemplate"]
