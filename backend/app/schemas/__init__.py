"""Esquemas Pydantic v2 compartidos."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.password_policy import ContrasenaBcrypt


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampMixinSchema(BaseModel):
    created_at: datetime
    updated_at: datetime


T = TypeVar("T")


class Page(ORMModel, Generic[T]):
    items: list[T]
    total: int


class HealthResponse(ORMModel):
    status: str = "ok"
    version: str


class ReadinessResponse(ORMModel):
    """Estado de *readiness*: ¿puede el backend servir tráfico ahora?

    ``status`` es ``"ready"`` sólo si **todas** las dependencias
    críticas (base de datos y Redis) responden. ``dependencies`` dice
    cuál falla, para no tener que adivinarlo.
    """

    status: str = "ready"
    version: str
    dependencies: dict[str, str] = Field(default_factory=dict)


class MessageResponse(ORMModel):
    detail: str


class LoginRequest(ORMModel):
    email: EmailStr
    # T-87: el login tambien respeta el limite real de bcrypt. Una
    # contrasena de mas de 72 bytes se comparaba truncada, asi que
    # servia cualquier sufijo.
    password: ContrasenaBcrypt


class TokenPair(ORMModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class LogoutRequest(ORMModel):
    """Body opcional de ``POST /auth/logout``.

    Sprint Fase 3D (push security review 2026-07-01): si el cliente
    envía ``refresh_token``, ``logout`` lo blacklistea también —
    cerrando el bypass en el que el ``refresh`` seguía vivo tras
    logout y permitía rotar ``access`` nuevos durante 7 días.

    Si NO se envía, sólo se blacklistea el ``access`` (el comportamiento
    previo) — útil para clientes que ya invalidaron el refresh por su
    cuenta (p. ej. SPA que descarta ambos en memoria).
    """

    refresh_token: Optional[str] = None