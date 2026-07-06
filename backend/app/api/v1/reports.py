"""Endpoints de reporte operativo: margen por sucursal (Sprint P1).

Dos rutas equivalentes:

  - ``GET /admin/reports/margins?parking_id=&from=&to=`` → JSON.
  - ``GET /admin/reports/margins.csv?parking_id=&from=&to=`` → CSV
    descargable (``text/csv``).

RBAC: admin ve cualquier sucursal. Gestor sólo la suya (validación
manual contra ``ParkingMembership`` para poder devolver el id validado
en lugar de ``User``).
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import ParkingMembership, User
from app.schemas.reports import MarginReportRead
from app.services.cost import compute_margin

router = APIRouter(
    prefix="/admin/reports",
    tags=["admin-reports"],
    dependencies=[Depends(get_current_user)],
)


def _resolve_parking_id(
    requested: int, user: User, db: Session,
) -> int:
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    if role_value == "admin":
        return requested
    membership = (
        db.query(ParkingMembership)
        .filter(
            ParkingMembership.user_id == user.id,
            ParkingMembership.parking_id == requested,
        )
        .one_or_none()
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="No tiene acceso a esta sucursal",
        )
    return requested


def _parse_window(
    from_: Optional[datetime], to: Optional[datetime],
) -> tuple[datetime, datetime]:
    if not from_ or not to:
        raise HTTPException(
            status_code=422,
            detail="Parámetros 'from' y 'to' obligatorios (ISO 8601)",
        )
    if to < from_:
        raise HTTPException(
            status_code=422,
            detail="'to' debe ser posterior a 'from'",
        )
    return from_, to


@router.get("/margins", response_model=MarginReportRead)
def margin_report(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
) -> MarginReportRead:
    _resolve_parking_id(parking_id, user, db)
    f, t = _parse_window(from_, to)
    return compute_margin(db, parking_id, from_=f, to=t)


@router.get("/margins.csv")
def margin_report_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
) -> Response:
    _resolve_parking_id(parking_id, user, db)
    f, t = _parse_window(from_, to)
    report = compute_margin(db, parking_id, from_=f, to=t)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["parking_id", "parking_name", "from", "to"])
    writer.writerow([
        report.parking_id, report.parking_name,
        report.from_.isoformat(), report.to.isoformat(),
    ])
    writer.writerow([])
    writer.writerow(["metric", "value"])
    writer.writerow(["total_revenue", f"{report.total_revenue:.2f}"])
    writer.writerow(["closed_tickets", report.closed_tickets])
    writer.writerow(["total_costs", f"{report.total_costs:.2f}"])
    writer.writerow(["margin", f"{report.margin:.2f}"])
    writer.writerow([])
    writer.writerow(["category", "amount_eur", "cost_count"])
    for entry in report.cost_breakdown:
        writer.writerow([
            entry.category.value, f"{entry.amount:.2f}", entry.cost_count,
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="margin-{parking_id}-'
                f'{report.from_.date()}-{report.to.date()}.csv"'
            ),
        },
    )


__all__ = ["router"]