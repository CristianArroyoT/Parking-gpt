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


class PasswordChange(ORMModel):
    """Sprint R5-sidebar (2026-07-06): payload para que el usuario
    autenticado cambie su propia clave desde el dropdown del sidebar.

    ``current_password`` se exige para confirmar identidad: un atacante
    con un token JWT robado no podría cambiar la clave sin conocer la
    actual. ``new_password`` cumple la misma política que ``UserCreate``
    (min_length=8).
    """

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class MembershipCreate(ORMModel):
    parking_id: int
    role_in_parking: str = "gestor"


class MembershipRead(ORMModel, TimestampMixinSchema):
    id: int
    user_id: int
    parking_id: int
    role_in_parking: str