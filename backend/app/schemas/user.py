"""Esquemas de usuario y membresía."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import EmailStr, Field

from app.schemas import ORMModel, TimestampMixinSchema
from app.schemas.vehicle import VehicleRead


class UserBase(ORMModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: str = "cliente"
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class OperadorCreate(ORMModel):
    """Alta de operador por parte de un gestor (T-20).

    A diferencia de ``UserCreate``, **no acepta ``role`` ni ``is_active``**:
    el usuario creado es siempre un ``operador`` y queda activo. Un gestor
    no puede crear admins ni desactivarlos (eso sigue siendo del admin).
    """
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(ORMModel):
    # T-19 (2026-10-21): ``full_name`` arrastra el mismo ``min_length``
    # que ``UserBase``/``UserRead``. Sin él, un PATCH podía guardar un
    # nombre de 1 carácter y la fila invalidaba después la serialización
    # de ``GET /users`` (500 por ResponseValidationError).
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
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


# ── T-19 (2026-10-21): perfil y vehículos del propio usuario ───────────
#
# El router de vehículos (``api/v1/vehicles.py``) es **sólo staff**
# (admin/gestor/operador): un cliente recibe 403 y no existe ninguna
# forma de consultar sus vehículos ni sus vínculos por la API pública.
# Estos esquemas dan soporte a los endpoints *user-scoped* del router
# de usuarios (``/users/me/...``), que son los que consume la vista
# "Mis vehículos" del cliente.


class ProfileUpdate(ORMModel):
    """Datos de perfil editables por el propio usuario (T-19).

    ``email`` y ``role`` **no** son editables desde aquí: el email es la
    identidad de acceso y el rol lo asigna el administrador. Ambos campos
    son opcionales para permitir actualizaciones parciales (por ejemplo,
    cambiar sólo el teléfono o vaciarlo con ``null``).
    """

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)


class VehicleLinkRead(ORMModel):
    """Vínculo usuario↔vehículo con el rol ``propietario|conductor``."""

    user_id: int
    email: str
    full_name: str
    role: str


class MyVehicleRead(VehicleRead):
    """Vehículo visto desde la perspectiva del usuario autenticado.

    Añade el rol que tiene el usuario en ese vehículo (``my_role``) y el
    resto de personas vinculadas, para que la vista pueda mostrar quién
    conduce cada vehículo sin llamadas adicionales.
    """

    my_role: str
    links: list[VehicleLinkRead] = Field(default_factory=list)


class MyVehicleCreate(ORMModel):
    """Alta de vehículo por parte del usuario (T-19).

    Se crea el vehículo y el vínculo del usuario como ``propietario`` en
    la misma operación.
    """

    plate: str = Field(min_length=4, max_length=16)
    brand: Optional[str] = Field(default=None, max_length=64)
    model: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=32)
    vehicle_type: Optional[str] = Field(default=None, max_length=32)


class MyVehicleUpdate(ORMModel):
    """Edición de un vehículo propio (T-19).

    La matrícula **no** se edita: es la clave natural del vehículo y
    cambiarla desincroniza los tickets ya emitidos.
    """

    brand: Optional[str] = Field(default=None, max_length=64)
    model: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=32)
    vehicle_type: Optional[str] = Field(default=None, max_length=32)


class VehicleLinkCreate(ORMModel):
    """Vínculo de otra persona a un vehículo propio (T-19).

    Se identifica a la persona por **email** y no por ``user_id`` porque
    ``GET /users`` es admin-only: el cliente no tiene forma de listar
    usuarios del sistema.
    """

    email: EmailStr
    role: Literal["propietario", "conductor"] = "conductor"