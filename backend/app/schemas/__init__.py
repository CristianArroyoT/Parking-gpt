"""Esquemas Pydantic v2 compartidos."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

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