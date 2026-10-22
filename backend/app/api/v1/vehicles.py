"""CRUD de vehículos y asociación con usuarios."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import require_role
from app.models.enums import UserRole, VehicleRole
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleRead,
    VehicleUpdate,
    VehicleUserCreate,
    VehicleUserRead,
)
from app.services.endpoint_rate_limit import enforce_endpoint_rate_limit

router = APIRouter(prefix="/vehicles", tags=["vehículos"])

_STAFF = (UserRole.ADMIN.value, UserRole.GESTOR.value, UserRole.OPERADOR.value)


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:

    """Delega en la implementación única (T-69).

    Antes este helper estaba copiado en cinco routers: arreglar uno
    no arreglaba los otros cuatro.
    """
    enforce_endpoint_rate_limit(
        request, db, scope=scope, actor_id=actor_id,
    )


@router.get("", response_model=list[VehicleRead])
def list_vehicles(
    plate: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_STAFF)),
) -> list[Vehicle]:
    query = db.query(Vehicle)
    if plate:
        query = query.filter(Vehicle.plate.ilike(f"%{plate}%"))
    return query.order_by(Vehicle.plate).all()


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
@audited("create_vehicle")
def create_vehicle(
    payload: VehicleCreate,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_STAFF)),
) -> Vehicle:
    # Sprint Fase 3D: rate-limit por actor (staff autenticado).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="vehicles_create", actor_id=actor_id,
        )
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Matrícula duplicada"
        ) from exc
    db.refresh(vehicle)
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleRead)
@audited("update_vehicle", resource_arg="vehicle_id")
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_STAFF)),
) -> Vehicle:
    # Sprint Fase 3D: rate-limit por actor en updates también.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="vehicles_update", actor_id=actor_id,
        )
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, key, value)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post(
    "/{vehicle_id}/users",
    response_model=VehicleUserRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("add_vehicle_user", resource_arg="vehicle_id")
def add_vehicle_user(
    vehicle_id: int,
    payload: VehicleUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_STAFF)),
) -> VehicleUser:
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    link = VehicleUser(
        vehicle_id=vehicle_id,
        user_id=payload.user_id,
        role=VehicleRole(payload.role),
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asociación duplicada"
        ) from exc
    db.refresh(link)
    return link