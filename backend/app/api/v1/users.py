"""CRUD de usuarios y membresías (sólo admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import ParkingMembership, User
from app.schemas.user import (
    MembershipCreate,
    MembershipRead,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["usuarios"])


@router.get("/me", response_model=UserRead)
def get_me(current: User = Depends(get_current_user)) -> User:
    """Devuelve el usuario autenticado (usado por el frontend al arrancar)."""
    return current


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> list[User]:
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
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
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
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
def delete_user(
    user_id: int,
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
def add_membership(
    user_id: int,
    payload: MembershipCreate,
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