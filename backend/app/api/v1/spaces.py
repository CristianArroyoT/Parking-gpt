"""CRUD de plazas por sucursal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import parking_context
from app.models.parking import Parking, ParkingSpace
from app.schemas.parking import (
    ParkingSpaceCreate,
    ParkingSpaceRead,
    ParkingSpaceUpdate,
)

router = APIRouter(
    prefix="/parkings/{parking_id}/spaces",
    tags=["plazas"],
    dependencies=[Depends(parking_context)],
)


@router.get("", response_model=list[ParkingSpaceRead])
def list_spaces(parking_id: int, db: Session = Depends(get_db)) -> list[ParkingSpace]:
    return (
        db.query(ParkingSpace)
        .filter(ParkingSpace.parking_id == parking_id)
        .order_by(ParkingSpace.lane, ParkingSpace.number)
        .all()
    )


@router.post("", response_model=ParkingSpaceRead, status_code=status.HTTP_201_CREATED)
@audited("create_space")
def create_space(
    parking_id: int,
    payload: ParkingSpaceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ParkingSpace:
    if not db.get(Parking, parking_id):
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    space = ParkingSpace(parking_id=parking_id, **payload.model_dump())
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


@router.patch("/{space_id}", response_model=ParkingSpaceRead)
@audited("update_space", resource_arg="space_id")
def update_space(
    parking_id: int,
    space_id: int,
    payload: ParkingSpaceUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> ParkingSpace:
    space = (
        db.query(ParkingSpace)
        .filter(ParkingSpace.id == space_id, ParkingSpace.parking_id == parking_id)
        .one_or_none()
    )
    if not space:
        raise HTTPException(status_code=404, detail="Plaza no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(space, key, value)
    db.commit()
    db.refresh(space)
    return space