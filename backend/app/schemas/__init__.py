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


class TokenRefreshRequest(ORMModel):
    """Body de ``POST /auth/refresh``: sólo hace falta el **refresh token**.

    T-187 (2026-10-25): el endpoint pedía un ``TokenPair`` COMPLETO
    (``access_token`` + ``expires_in`` + ``refresh_token``) y el cliente
    manda SÓLO ``{"refresh_token": ...}``: el backend respondía **422** y el
    frontend limpiaba la sesión y echaba al login.

    MEDIDO (2026-10-25, con un navegador de verdad): a los 15 minutos (el TTL
    del access token) la primera petición da 401, el refresco da 422 y el
    operador queda en el login con el refresh token —**válido 7 días**— sin
    poder usarlo. El endpoint sólo lee ``refresh_token``; exigir el access
    (caducado, justo lo que se viene a renovar) no tenía sentido.

    El campo tiene valor por defecto para que un body vacío siga
    respondiendo 401 ("Token de refresco requerido") y no un 422 de
    Pydantic: el 422 significa "el cliente manda algo que no encaja", que es
    un error de contrato, no de credenciales.
    """

    refresh_token: str = ""


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