"""CRUD de tarifas por sucursal.

Lectura abierta a cualquier usuario autenticado (la usan los gestores para
ver la tabla vigente y la app del cliente para mostrar el importe estimado).
Crear/editar requiere parking_context (gestor con membresía o admin).
Eliminar está restringido a admin para no perder histórico de tickets.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import get_current_user, parking_context, require_role
from app.models.enums import UserRole
from app.models.parking import Parking
from app.models.pricing import Tariff
from app.models.user import User
from app.schemas.pricing import TariffCreate, TariffRead, TariffUpdate
from app.services.audit import record_audit_from_request
from app.services.endpoint_rate_limit import endpoint_rate_limiter

router = APIRouter(prefix="/parkings/{parking_id}/tariffs", tags=["tarifas"])


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:
    """Sprint R5 (2026-07-06): rate-limit por actor para POST/PATCH
    /tariffs. Misma lógica que ``users``/``cameras``/``parkings``."""
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


@router.get("", response_model=list[TariffRead])
def list_tariffs(
    parking_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Tariff]:
    if not db.get(Parking, parking_id):
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    return (
        db.query(Tariff)
        .filter(Tariff.parking_id == parking_id)
        .order_by(Tariff.valid_from.desc())
        .all()
    )


@router.post("", response_model=TariffRead, status_code=status.HTTP_201_CREATED)
@audited("create_tariff")
def create_tariff(
    parking_id: int,
    payload: TariffCreate,
    request: Request,
    db: Session = Depends(get_db),
    _current: User = Depends(parking_context),
) -> Tariff:
    # Sprint R5: rate-limit por actor.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="tariffs_create", actor_id=actor_id,
        )
    if payload.parking_id != parking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parking_id del body no coincide con la URL",
        )
    if not db.get(Parking, parking_id):
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    if payload.valid_to and payload.valid_to <= payload.valid_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="valid_to debe ser posterior a valid_from",
        )
    tariff = Tariff(**payload.model_dump())
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.patch("/{tariff_id}", response_model=TariffRead)
@audited("update_tariff", resource_arg="tariff_id")
def update_tariff(
    parking_id: int,
    tariff_id: int,
    payload: TariffUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _current: User = Depends(parking_context),
) -> Tariff:
    # Sprint R5: rate-limit por actor.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="tariffs_update", actor_id=actor_id,
        )
    tariff = (
        db.query(Tariff)
        .filter(Tariff.id == tariff_id, Tariff.parking_id == parking_id)
        .one_or_none()
    )
    if not tariff:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tariff, key, value)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.delete("/{tariff_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_tariff", resource_arg="tariff_id")
def delete_tariff(
    parking_id: int,
    tariff_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN.value)),
) -> None:
    # Sprint R5 (follow-up): paridad con POST/PATCH.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="tariffs_delete", actor_id=actor_id,
        )
    tariff = (
        db.query(Tariff)
        .filter(Tariff.id == tariff_id, Tariff.parking_id == parking_id)
        .one_or_none()
    )
    if not tariff:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    db.delete(tariff)
    db.commit()