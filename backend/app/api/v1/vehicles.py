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

router = APIRouter(prefix="/vehicles", tags=["vehículos"])

_STAFF = (UserRole.ADMIN.value, UserRole.GESTOR.value, UserRole.OPERADOR.value)


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