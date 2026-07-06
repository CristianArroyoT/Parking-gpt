"""CRUD de costes operativos (Sprint P1 solidAPP, 2026-07-06).

Endpoints admin-only sobre la tabla ``costs`` (modelo definido en
``app/models/cost.py``). Permiten al administrador dar de alta
costes por sucursal para que el reporte de margen los tenga en
cuenta.

RBAC: ``require_role("admin")`` rechaza a gestores / operadores /
clientes con 403 antes de tocar la BD.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import require_role
from app.models.cost import Cost
from app.models.enums import CostCategory, CostPeriod
from app.models.user import User
from app.schemas.cost import CostCreate, CostRead, CostUpdate

router = APIRouter(
    prefix="/admin/costs",
    tags=["admin-costs"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("", response_model=list[CostRead])
def list_costs(
    db: Annotated[Session, Depends(get_db)],
    parking_id: Annotated[Optional[int], Query(ge=1)] = None,
    category: Annotated[Optional[CostCategory], Query()] = None,
    periodicity: Annotated[Optional[CostPeriod], Query()] = None,
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
) -> list[Cost]:
    """Lista costes con filtros opcionales. Orden: más recientes primero."""
    q = db.query(Cost).order_by(Cost.id.desc())
    if parking_id is not None:
        q = q.filter(Cost.parking_id == parking_id)
    if category is not None:
        q = q.filter(Cost.category == category)
    if periodicity is not None:
        q = q.filter(Cost.periodicity == periodicity)
    if from_ is not None:
        q = q.filter(Cost.period_start >= from_)
    if to is not None:
        q = q.filter(Cost.period_start <= to)
    return q.all()


@router.post("", response_model=CostRead, status_code=status.HTTP_201_CREATED)
@audited("create_cost")
def create_cost(
    payload: CostCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role("admin"))],
) -> Cost:
    """Da de alta un coste. Valida coherencia ``periodicity``/``period_end``
    en el schema ``CostCreate`` antes de tocar la BD."""
    cost = Cost(**payload.model_dump())
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


@router.get("/{cost_id}", response_model=CostRead)
def get_cost(
    cost_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Cost:
    cost = db.get(Cost, cost_id)
    if not cost:
        raise HTTPException(status_code=404, detail="Coste no encontrado")
    return cost


@router.patch("/{cost_id}", response_model=CostRead)
@audited("update_cost", resource_arg="cost_id")
def update_cost(
    cost_id: int,
    payload: CostUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Cost:
    """PATCH parcial. Si cambia ``periodicity`` se revalida la regla
    period_end ↔ periodicidad para no dejar el modelo en estado
    inconsistente."""
    cost = db.get(Cost, cost_id)
    if not cost:
        raise HTTPException(status_code=404, detail="Coste no encontrado")

    data = payload.model_dump(exclude_unset=True)
    new_periodicity = data.get("periodicity", cost.periodicity)
    new_period_end = data.get("period_end", cost.period_end)
    new_period_start = data.get("period_start", cost.period_start)
    if new_periodicity is CostPeriod.PUNTUAL:
        if new_period_end is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Costes puntuales requieren period_end",
            )
        if new_period_end <= new_period_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="period_end debe ser posterior a period_start",
            )
    else:
        if new_period_end is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Costes recurrentes no admiten period_end",
            )

    for key, value in data.items():
        setattr(cost, key, value)
    db.commit()
    db.refresh(cost)
    return cost


@router.delete("/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_cost", resource_arg="cost_id")
def delete_cost(
    cost_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    cost = db.get(Cost, cost_id)
    if not cost:
        raise HTTPException(status_code=404, detail="Coste no encontrado")
    db.delete(cost)
    db.commit()


__all__ = ["router"]