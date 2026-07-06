"""CRUD de sucursales."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import get_current_user, parking_context, require_role
from app.models.enums import UserRole
from app.models.parking import Parking
from app.models.user import ParkingMembership, User
from app.schemas.parking import ParkingCreate, ParkingRead, ParkingUpdate
from app.services.audit import record_audit_from_request
from app.services.endpoint_rate_limit import endpoint_rate_limiter

router = APIRouter(prefix="/parkings", tags=["sucursales"])


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:
    """Sprint R5 (2026-07-06): misma lógica que ``users``/``cameras``.
    POST/PATCH /parkings protegidos contra ráfagas de scripts."""
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


@router.get("", response_model=list[ParkingRead])
def list_parkings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Parking]:
    if user.role == UserRole.ADMIN:
        return db.query(Parking).order_by(Parking.id).all()
    ids = [
        m.parking_id
        for m in db.query(ParkingMembership).filter(ParkingMembership.user_id == user.id).all()
    ]
    return db.query(Parking).filter(Parking.id.in_(ids)).order_by(Parking.id).all()


@router.post("", response_model=ParkingRead, status_code=status.HTTP_201_CREATED)
@audited("create_parking")
def create_parking(
    payload: ParkingCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> Parking:
    # Sprint R5: rate-limit por actor (admin).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="parkings_create", actor_id=actor_id,
        )
    parking = Parking(**payload.model_dump())
    db.add(parking)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Código duplicado"
        ) from exc
    db.refresh(parking)
    return parking


@router.get("/{parking_id}", response_model=ParkingRead)
def get_parking(
    parking_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(parking_context),
) -> Parking:
    parking = db.get(Parking, parking_id)
    if not parking:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    return parking


@router.patch("/{parking_id}", response_model=ParkingRead)
@audited("update_parking", resource_arg="parking_id")
def update_parking(
    parking_id: int,
    payload: ParkingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(parking_context),
) -> Parking:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede modificar sucursales",
        )
    # Sprint R5: rate-limit por actor.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="parkings_update", actor_id=actor_id,
        )
    parking = db.get(Parking, parking_id)
    if not parking:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(parking, key, value)
    db.commit()
    db.refresh(parking)
    return parking


@router.delete("/{parking_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_parking", resource_arg="parking_id")
def delete_parking(
    parking_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> None:
    parking = db.get(Parking, parking_id)
    if not parking:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    db.delete(parking)
    db.commit()