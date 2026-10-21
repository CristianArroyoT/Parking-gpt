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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import enforce_parking_membership, get_current_user
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import ParkingMembership, User
from app.schemas.user import OperadorCreate, UserRead
from app.services.endpoint_rate_limit import endpoint_rate_limiter

router = APIRouter(prefix="/parkings/{parking_id}", tags=["gestor-operadores"])


def _exigir_gestor(current: User) -> None:
    """Sólo admin o gestor (un operador o un cliente no gestionan personal)."""
    if current.role not in (UserRole.ADMIN, UserRole.GESTOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
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
    _exigir_gestor(current)

    ids = select(ParkingMembership.user_id).where(
        ParkingMembership.parking_id == parking_id
    )
    usuarios = (
        db.query(User)
        .filter(User.id.in_(ids), User.role == UserRole.OPERADOR)
        .order_by(User.id)
        .all()
    )
    return usuarios


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
    _exigir_gestor(current)

    # Mismo rate-limit por actor que el alta de usuarios del admin (R5).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        allowed, bucket, count = endpoint_rate_limiter.check(
            scope="users_create", identifiers={"actor": str(actor_id)},
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas operaciones. Intenta más tarde.",
            )

    email = payload.email.lower()
    existente = db.query(User).filter(User.email == email).one_or_none()
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
