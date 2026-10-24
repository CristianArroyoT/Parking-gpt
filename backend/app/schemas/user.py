"""Esquemas de usuario y membresía."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import EmailStr, Field, field_validator

from app.core.deps import validar_rol_de_sucursal
from app.core.emails import normalizar_email
from app.core.password_policy import ContrasenaBcrypt
from app.schemas import ORMModel, TimestampMixinSchema
from app.schemas.vehicle import VehicleRead


class UserBase(ORMModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: str = "cliente"
    is_active: bool = True


class UserCreate(UserBase):
    # T-87: el limite real es de 72 BYTES (bcrypt), no de 128
    # caracteres: a partir de ahi el hash solo distingue el prefijo.
    password: ContrasenaBcrypt = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def _email_canonico(cls, valor: object) -> object:
        """T-99: el email se guarda en su forma canonica (minusculas).

        Sin esto se podrian crear dos cuentas que solo se diferencian en
        como estan escritas ("A@b.es" y "a@b.es"): el login compararia
        el texto en bruto y cada una entraria con su propia forma, pero
        para el usuario seria la misma cuenta. Con el indice unico
        sobre ``lower(email)`` la base de datos lo prohibe.

        Va en modo ``before`` (no ``after``) porque ``EmailStr`` es un
        tipo especial que no se puede construir a mano: se normaliza el
        texto y luego lo valida pydantic como siempre.
        """
        if isinstance(valor, str):
            return normalizar_email(valor)
        return valor


class OperadorCreate(ORMModel):
    """Alta de operador por parte de un gestor (T-20).

    A diferencia de ``UserCreate``, **no acepta ``role`` ni ``is_active``**:
    el usuario creado es siempre un ``operador`` y queda activo. Un gestor
    no puede crear admins ni desactivarlos (eso sigue siendo del admin).
    """
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = None
    password: ContrasenaBcrypt = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def _email_canonico(cls, valor: object) -> object:
        """T-99: el email se guarda en su forma canonica (minusculas)."""
        if isinstance(valor, str):
            return normalizar_email(valor)
        return valor


class UserUpdate(ORMModel):
    # T-19 (2026-10-21): ``full_name`` arrastra el mismo ``min_length``
    # que ``UserBase``/``UserRead``. Sin él, un PATCH podía guardar un
    # nombre de 1 carácter y la fila invalidaba después la serialización
    # de ``GET /users`` (500 por ResponseValidationError).
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    # T-19 lo arregló para ``full_name``; el ``phone`` seguia sin limite
    # (2026-10-22), y un PATCH podia guardar un telefono de 500
    # caracteres que despues invalidaba la fila al serializar.
    phone: Optional[str] = Field(default=None, max_length=32)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[ContrasenaBcrypt] = Field(default=None, min_length=8, max_length=128)


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

    # T-87: ``current_password`` tambien se limita: verificar una
    # contrasena de mas de 72 bytes la comparaba truncada.
    current_password: ContrasenaBcrypt = Field(min_length=1, max_length=128)
    new_password: ContrasenaBcrypt = Field(min_length=8, max_length=128)


class MembershipCreate(ORMModel):
    parking_id: int
    role_in_parking: str = "gestor"

    @field_validator("role_in_parking")
    @classmethod
    def _rol_valido(cls, valor: str) -> str:
        """Un rol por sucursal, y **nunca** ``admin`` (ADR 0005).

        El ``admin`` es un rol **global**: no existe un admin «de una
        sucursal». Un valor que no sea un rol se rechaza con 422.
        """
        return validar_rol_de_sucursal(valor)


class MembershipUpdate(ORMModel):
    """Cambio del rol en una sucursal (RBAC por sucursal, ADR 0005)."""

    role_in_parking: str

    @field_validator("role_in_parking")
    @classmethod
    def _rol_valido(cls, valor: str) -> str:
        return validar_rol_de_sucursal(valor)


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
    phone: Optional[str] = None


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