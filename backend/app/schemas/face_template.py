"""Esquemas de las plantillas de reconocimiento facial (T-23).

**Fuera del MVP**: sólo describen la estructura preparada. El router que
los usa está deshabilitado por feature flag (``FACE_TEMPLATES_ENABLED``).
"""

from __future__ import annotations

from pydantic import Field

from app.schemas import ORMModel, TimestampMixinSchema


class FaceTemplateCreate(ORMModel):
    """Alta de un template biométrico para el usuario autenticado.

    ``embedding`` es el vector de características (lista de floats). El
    tamaño máximo acota el abuso: un vector razonable son cientos de
    floats, no cientos de miles.
    """

    embedding: list[float] = Field(min_length=1, max_length=4096)
    camera_id: int | None = None


class FaceTemplateRead(ORMModel, TimestampMixinSchema):
    """Template almacenado (el vector se devuelve tal cual)."""

    id: int
    user_id: int
    camera_id: int | None
    dimension: int | None


__all__ = ["FaceTemplateCreate", "FaceTemplateRead"]
