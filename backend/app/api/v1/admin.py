"""Endpoints admin-only: lectura del histórico de ``audit_logs``.

Sprint Fase 3A (2026-07-01). Sólo accesible a usuarios con
``UserRole.ADMIN``. Devuelve los registros ordenados por
``created_at DESC`` (más recientes primero) con paginación
limit/offset y filtros por user_id, action, resource, parking_id,
result, correlation_id y rango de fechas.

RBAC: la dep ``require_role("admin")`` rechaza a gestores/operadores/
clientes con 403 antes de tocar la BD. NO hay RBAC por sucursal —
un admin ve todas las sucursales.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogRead

router = APIRouter(
    prefix="/admin/audit-logs",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[int | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource: Annotated[str | None, Query(max_length=128)] = None,
    parking_id: Annotated[int | None, Query()] = None,
    result: Annotated[str | None, Query(max_length=16)] = None,
    correlation_id: Annotated[str | None, Query(max_length=36)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLog]:
    """Lista audit_logs con filtros y paginación. Orden: más recientes primero."""
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource:
        q = q.filter(AuditLog.resource == resource)
    if parking_id is not None:
        q = q.filter(AuditLog.parking_id == parking_id)
    if result:
        q = q.filter(AuditLog.result == result)
    if correlation_id:
        q = q.filter(AuditLog.correlation_id == correlation_id)
    if from_ is not None:
        q = q.filter(AuditLog.created_at >= from_)
    if to is not None:
        q = q.filter(AuditLog.created_at <= to)
    return q.limit(limit).offset(offset).all()


__all__ = ["router"]