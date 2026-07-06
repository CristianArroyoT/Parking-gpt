"""Esquemas de usuario y membresía."""

from __future__ import annotations

from typing import Optional

from pydantic import EmailStr, Field

from app.schemas import ORMModel, TimestampMixinSchema


class UserBase(ORMModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: str = "cliente"
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(ORMModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserRead(UserBase, TimestampMixinSchema):
    id: int


class MembershipCreate(ORMModel):
    parking_id: int
    role_in_parking: str = "gestor"


class MembershipRead(ORMModel, TimestampMixinSchema):
    id: int
    user_id: int
    parking_id: int
    role_in_parking: str