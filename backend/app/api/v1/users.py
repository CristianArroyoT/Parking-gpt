"""CRUD de usuarios y membresías (sólo admin)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import hash_password, verify_password
from app.models.enums import UserRole, VehicleRole
from app.models.ticket import Ticket
from app.models.user import ParkingMembership, User
from app.models.vehicle import Vehicle, VehicleUser
from app.schemas.ticket import TicketRead
from app.schemas.user import (
    MembershipCreate,
    MembershipRead,
    MyVehicleCreate,
    MyVehicleRead,
    MyVehicleUpdate,
    PasswordChange,
    ProfileUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
    VehicleLinkCreate,
    VehicleLinkRead,
)
from app.services.audit import record_audit_from_request
from app.services.endpoint_rate_limit import endpoint_rate_limiter

router = APIRouter(prefix="/users", tags=["usuarios"])


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:
    """Aplica ``endpoint_rate_limiter.check`` y emite audit + 429 si bloquea.

    Helper compartido por ``create_user`` y ``update_user``. Lanza 429
    si el bucket del actor supera el umbral. El audit se persiste con
    ``action="rate_limited_endpoint"`` y el scope concreto (e.g.
    ``users_create``) para correlación operativa.
    """
    allowed, bucket, count = endpoint_rate_limiter.check(
        scope=scope, identifiers={"actor": str(actor_id)},
    )
    if not allowed:
        record_audit_from_request(
            request, db,
            action="rate_limited_endpoint",
            payload={"scope": scope, "bucket": bucket, "count": count},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas operaciones. Intenta más tarde.",
        )


@router.get("/me", response_model=UserRead)
def get_me(current: User = Depends(get_current_user)) -> User:
    """Devuelve el usuario autenticado (usado por el frontend al arrancar)."""
    return current


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    """Sprint R5-sidebar (2026-07-06): cambio de clave del usuario actual.

    El usuario se identifica a sí mismo con ``current_password`` (un
    atacante con un JWT robado no podría cambiar la clave sin conocer
    la actual). Tras el cambio el resto de sesiones del mismo usuario
    siguen siendo válidas — no invalidamos tokens aquí; el usuario
    puede usar ``POST /auth/logout/all`` si quiere cerrar todas.

    Audit: ``action=change_my_password`` con ``result=success`` o
    ``failure`` según el caso (failure → ``reason=current_password_mismatch``
    para correlación operativa).
    """
    if not verify_password(payload.current_password, current.hashed_password):
        record_audit_from_request(
            request, db,
            action="change_my_password",
            payload={"user_id": current.id, "reason": "current_password_mismatch"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no es correcta",
        )
    current.hashed_password = hash_password(payload.new_password)
    db.commit()
    record_audit_from_request(
        request, db,
        action="change_my_password",
        payload={"user_id": current.id},
        result="success",
    )
    db.commit()
    return None


# ──────────────────────────────────────────────────────────────────────────
# T-19 (2026-10-21): endpoints *user-scoped* del propio usuario.
#
# Motivo de existir aquí y no en ``api/v1/vehicles.py``: el router de
# vehículos es **sólo staff** (admin/gestor/operador) y un cliente recibe
# 403 en ``GET /vehicles`` y ``POST /vehicles/{id}/users``. Como el router
# de usuarios ya está registrado en ``api/v1/__init__.py`` (y ese fichero
# lo mantiene otro agente), estas rutas user-scoped viven aquí para que la
# vista "Mis vehículos" del cliente funcione sin tocar ficheros ajenos.
#
# Todas usan ``get_current_user``: cada usuario sólo ve y toca **sus**
# vehículos (los vinculados por ``VehicleUser``) y sus tickets.
# ──────────────────────────────────────────────────────────────────────────


def _role_value(role: object) -> str:
    """Normaliza el rol del enum/str persistido a su valor textual."""
    return role.value if hasattr(role, "value") else str(role)


def _vehicle_links(
    db: Session, vehicle_ids: list[int],
) -> dict[int, list[VehicleLinkRead]]:
    """Vínculos de cada vehículo con los datos de la persona vinculada."""
    if not vehicle_ids:
        return {}
    rows = (
        db.query(VehicleUser)
        .filter(VehicleUser.vehicle_id.in_(vehicle_ids))
        .all()
    )
    user_ids = {r.user_id for r in rows}
    usuarios = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
        if user_ids else {}
    )
    out: dict[int, list[VehicleLinkRead]] = {}
    for r in rows:
        u = usuarios.get(r.user_id)
        out.setdefault(r.vehicle_id, []).append(
            VehicleLinkRead(
                user_id=r.user_id,
                email=u.email if u else "",
                full_name=u.full_name if u else "",
                role=_role_value(r.role),
            )
        )
    return out


def _my_vehicle_read(
    vehicle: Vehicle, my_role: str, links: dict[int, list[VehicleLinkRead]],
) -> MyVehicleRead:
    """Construye el ``MyVehicleRead`` del vehículo con sus vínculos."""
    return MyVehicleRead(
        id=vehicle.id,
        plate=vehicle.plate,
        brand=vehicle.brand,
        model=vehicle.model,
        color=vehicle.color,
        vehicle_type=vehicle.vehicle_type,
        created_at=vehicle.created_at,
        updated_at=vehicle.updated_at,
        my_role=my_role,
        links=links.get(vehicle.id, []),
    )


def _my_link(
    db: Session, vehicle_id: int, user_id: int,
) -> Optional[VehicleUser]:
    """Vínculo del usuario con el vehículo (o ``None``)."""
    return (
        db.query(VehicleUser)
        .filter(
            VehicleUser.vehicle_id == vehicle_id,
            VehicleUser.user_id == user_id,
        )
        .first()
    )


@router.patch("/me/profile", response_model=UserRead)
@audited("update_my_profile")
def update_my_profile(
    payload: ProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> User:
    """T-19: el usuario actual actualiza su nombre y su teléfono.

    No se puede cambiar el email (identidad de acceso) ni el rol (lo
    asigna el administrador). Si el body no trae ningún campo se responde
    400 en vez de devolver un no-op silencioso.
    """
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay datos para actualizar",
        )
    for key, value in data.items():
        setattr(current, key, value)
    db.commit()
    db.refresh(current)
    return current


@router.get("/me/vehicles", response_model=list[MyVehicleRead])
def list_my_vehicles(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[MyVehicleRead]:
    """T-19: vehículos vinculados al usuario actual (propietario/conductor)."""
    rows = (
        db.query(VehicleUser)
        .filter(VehicleUser.user_id == current.id)
        .all()
    )
    if not rows:
        return []
    my_role = {r.vehicle_id: _role_value(r.role) for r in rows}
    vehicles = (
        db.query(Vehicle)
        .filter(Vehicle.id.in_(list(my_role.keys())))
        .order_by(Vehicle.plate)
        .all()
    )
    links = _vehicle_links(db, list(my_role.keys()))
    return [_my_vehicle_read(v, my_role[v.id], links) for v in vehicles]


@router.post(
    "/me/vehicles",
    response_model=MyVehicleRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("create_my_vehicle")
def create_my_vehicle(
    payload: MyVehicleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> MyVehicleRead:
    """T-19: alta de vehículo. El usuario queda como ``propietario``."""
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="vehicles_create", actor_id=actor_id,
        )
    vehicle = Vehicle(
        plate=payload.plate.strip().upper(),
        brand=payload.brand,
        model=payload.model,
        color=payload.color,
        vehicle_type=payload.vehicle_type,
    )
    db.add(vehicle)
    try:
        db.flush()
        db.add(
            VehicleUser(
                vehicle_id=vehicle.id,
                user_id=current.id,
                role=VehicleRole.PROPIETARIO,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Matrícula duplicada"
        ) from exc
    db.refresh(vehicle)
    links = _vehicle_links(db, [vehicle.id])
    return _my_vehicle_read(vehicle, VehicleRole.PROPIETARIO.value, links)


@router.patch("/me/vehicles/{vehicle_id}", response_model=MyVehicleRead)
@audited("update_my_vehicle", resource_arg="vehicle_id")
def update_my_vehicle(
    vehicle_id: int,
    payload: MyVehicleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> MyVehicleRead:
    """T-19: edición de un vehículo propio (sólo el propietario edita)."""
    link = _my_link(db, vehicle_id, current.id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El vehículo no está vinculado a tu usuario",
        )
    if _role_value(link.role) != VehicleRole.PROPIETARIO.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sólo el propietario puede editar el vehículo",
        )
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vehículo no encontrado"
        )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, key, value)
    db.commit()
    db.refresh(vehicle)
    links = _vehicle_links(db, [vehicle.id])
    return _my_vehicle_read(vehicle, VehicleRole.PROPIETARIO.value, links)


@router.post(
    "/me/vehicles/{vehicle_id}/links",
    response_model=VehicleLinkRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("add_my_vehicle_user", resource_arg="vehicle_id")
def add_my_vehicle_user(
    vehicle_id: int,
    payload: VehicleLinkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> VehicleLinkRead:
    """T-19: vincula a otra persona con un vehículo propio.

    La persona se identifica por **email** porque ``GET /users`` es
    admin-only: el cliente no puede listar usuarios del sistema.
    """
    link = _my_link(db, vehicle_id, current.id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El vehículo no está vinculado a tu usuario",
        )
    if _role_value(link.role) != VehicleRole.PROPIETARIO.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sólo el propietario puede vincular a otras personas",
        )
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vehículo no encontrado"
        )
    target = (
        db.query(User).filter(User.email == payload.email).one_or_none()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe ningún usuario con ese correo",
        )
    existing = _my_link(db, vehicle_id, target.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario ya está vinculado a este vehículo con el rol "
                f"'{_role_value(existing.role)}'"
            ),
        )
    nuevo = VehicleUser(
        vehicle_id=vehicle_id,
        user_id=target.id,
        role=VehicleRole(payload.role),
    )
    db.add(nuevo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asociación duplicada"
        ) from exc
    db.refresh(nuevo)
    return VehicleLinkRead(
        user_id=target.id,
        email=target.email,
        full_name=target.full_name,
        role=_role_value(nuevo.role),
    )


@router.delete(
    "/me/vehicles/{vehicle_id}/links/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@audited("remove_my_vehicle_user", resource_arg="vehicle_id")
def remove_my_vehicle_user(
    vehicle_id: int,
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    """T-19: desvincula a una persona (o al propio usuario) del vehículo."""
    link = _my_link(db, vehicle_id, user_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El vínculo no existe",
        )
    propio = _my_link(db, vehicle_id, current.id)
    es_propietario = propio is not None and (
        _role_value(propio.role) == VehicleRole.PROPIETARIO.value
    )
    if not es_propietario and user_id != current.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sólo el propietario puede desvincular a otras personas",
        )
    if _role_value(link.role) == VehicleRole.PROPIETARIO.value:
        owners = (
            db.query(VehicleUser)
            .filter(
                VehicleUser.vehicle_id == vehicle_id,
                VehicleUser.role == VehicleRole.PROPIETARIO.value,
            )
            .count()
        )
        if owners <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El vehículo se quedaría sin propietario",
            )
    db.delete(link)
    db.commit()


@router.get("/me/tickets", response_model=list[TicketRead])
def list_my_tickets(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[Ticket]:
    """T-19: tickets **de los vehículos del usuario**.

    Éste es el scope correcto para un cliente (propietario o conductor):
    los tickets de los vehículos que conduce, y no los de los demás
    vehículos de la sucursal. El listado genérico ``GET /tickets`` filtra
    por membresía de sucursal, no por vehículo, así que un cliente con
    membresía vería tickets de vehículos ajenos.

    Tickets de vehículos vinculados al usuario, de más reciente a más
    antiguo, con el mismo tope de 200 que usa ``GET /tickets``.
    """
    vehicle_ids = [
        r.vehicle_id
        for r in db.query(VehicleUser)
        .filter(VehicleUser.user_id == current.id)
        .all()
    ]
    if not vehicle_ids:
        return []
    return (
        db.query(Ticket)
        .filter(Ticket.vehicle_id.in_(vehicle_ids))
        .order_by(Ticket.entry_at.desc())
        .limit(200)
        .all()
    )


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> list[User]:
    return db.query(User).order_by(User.id).all()

@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@audited("create_user")
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
    # Sprint Fase 3D (2026-07-01): rate-limit por actor (admin).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="users_create", actor_id=actor_id,
        )
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        role=UserRole(payload.role),
        is_active=payload.is_active,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email duplicado"
        ) from exc
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.patch("/{user_id}", response_model=UserRead)
@audited("update_user", resource_arg="user_id")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
    # Sprint Fase 3D: rate-limit por actor (admin) en updates también.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="users_update", actor_id=actor_id,
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    if "role" in data:
        user.role = UserRole(data.pop("role"))
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_user", resource_arg="user_id")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.delete(user)
    db.commit()


@router.post(
    "/{user_id}/memberships",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/{user_id}/memberships",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("create_membership", resource_arg="user_id")
def add_membership(
    user_id: int,
    payload: MembershipCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> ParkingMembership:
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    membership = ParkingMembership(
        user_id=user_id,
        parking_id=payload.parking_id,
        role_in_parking=UserRole(payload.role_in_parking),
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Membresía duplicada"
        ) from exc
    db.refresh(membership)
    return membership