"""Gestión de operadores **acotada por sucursal** (T-20, plan 2026-10-21).

Por qué un router nuevo y no relajar ``/users``:

``GET/POST /users`` y ``POST /users/{id}/memberships`` son **admin-only**, y
esa restricción es intencionada: el conjunto de usuarios del sistema y sus
roles no son asunto de un gestor de sucursal. Pero el wireframe del Gestor
pide "Operadores: alta y asignación" para **su** sucursal, y con la API
actual el gestor recibía un 403 y la vista sólo podía explicarlo.

La solución es una API **nueva y más estrecha**, no abrir la existente:

- ``GET  /parkings/{parking_id}/operadores`` → los operadores de esa
  sucursal.
- ``POST /parkings/{parking_id}/operadores`` → crea un usuario **siempre con
  rol ``operador``** y lo deja asignado a esa sucursal.

Garantías (esto es lo importante):

1. El gestor **sólo** puede actuar sobre sucursales de las que es miembro:
   ``enforce_parking_membership`` devuelve 403 en caso contrario.
2. El rol es **forzado** a ``operador``: el payload no tiene campo ``role``,
   así que un gestor no puede crear un admin ni un gestor.
3. El usuario creado **no** queda con permisos en otras sucursales: su única
   membresía es la del path.
4. Se aplica el mismo **rate-limit por actor** que el alta de usuarios del
   admin (sprint R5) y la misma **auditoría**.
5. Los endpoints de admin **no se tocan**: siguen siendo admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import (
    enforce_parking_membership,
    enforce_parking_role,
    get_current_user,
)
from app.core.emails import normalizar_email
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import ParkingMembership, User
from app.schemas.user import OperadorCreate, UserRead
from app.services.endpoint_rate_limit import enforce_endpoint_rate_limit

router = APIRouter(prefix="/parkings/{parking_id}", tags=["gestor-operadores"])


def _exigir_gestor(current: User, parking_id: int, db: Session) -> None:
    """Sólo admin o gestor **de esa sucursal** (un operador o un cliente no
    gestionan personal).

    T-178 (ADR 0005): antes miraba el rol **global** del usuario. Ahora
    decide el rol **efectivo en la sucursal del path**: un gestor que en
    esta sucursal es ``operador`` no gestiona el personal de aquí.
    """
    enforce_parking_role(
        current,
        parking_id,
        db,
        UserRole.ADMIN.value,
        UserRole.GESTOR.value,
        detail="Sólo el gestor o el administrador gestionan los operadores",
    )


@router.get("/operadores", response_model=list[UserRead])
def listar_operadores(
    parking_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[User]:
    """Operadores asignados a la sucursal.

    Un gestor sólo ve los de **sus** sucursales (si pide una en la que no
    es miembro, 403). El admin ve los de la que sea.
    """
    enforce_parking_membership(current, parking_id, db)
    _exigir_gestor(current, parking_id, db)

    ids = select(ParkingMembership.user_id).where(
        ParkingMembership.parking_id == parking_id
    )
    return (
        db.query(User)
        .filter(User.id.in_(ids), User.role == UserRole.OPERADOR)
        .order_by(User.id)
        .all()
    )


@router.post(
    "/operadores",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("create_operador")
def crear_operador(
    parking_id: int,
    payload: OperadorCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> User:
    """Crea un operador y lo asigna a la sucursal del path.

    El rol es forzado a ``operador`` y la única membresía que se crea es la
    de esta sucursal: un gestor no puede crear admins ni colgar a un
    operador de otra sucursal.
    """
    enforce_parking_membership(current, parking_id, db)
    _exigir_gestor(current, parking_id, db)

    # Mismo rate-limit por actor que el alta de usuarios del admin (R5).
    # T-69: usa la implementación única (antes esta lógica estaba escrita
    # aquí a mano: era la sexta copia del mismo código).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    enforce_endpoint_rate_limit(
        request, db, scope="users_create", actor_id=actor_id,
    )

    # T-99: el alta guarda el email canonico y lo compara asi (para que
    # no se pueda crear un duplicado que solo se diferencie en las
    # mayusculas).
    email = normalizar_email(str(payload.email))
    existente = (
        db.query(User)
        .filter(func.lower(User.email) == email)
        .one_or_none()
    )
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El email '{email}' ya está en uso"
                if existente.role == UserRole.OPERADOR
                else f"El email '{email}' ya existe con otro rol; pídele al "
                "administrador que lo gestione"
            ),
        )

    usuario = User(
        email=email,
        full_name=payload.full_name,
        phone=payload.phone,
        role=UserRole.OPERADOR,
        is_active=True,
        hashed_password=hash_password(payload.password),
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError as exc:  # pragma: no cover — carrera rara
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email duplicado"
        ) from exc

    db.add(
        ParkingMembership(user_id=usuario.id, parking_id=parking_id)
    )
    db.commit()
    db.refresh(usuario)
    return usuario
