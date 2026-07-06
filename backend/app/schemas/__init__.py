"""Esquemas Pydantic v2 compartidos."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr


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


class MessageResponse(ORMModel):
    detail: str


class LoginRequest(ORMModel):
    email: EmailStr
    password: str


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