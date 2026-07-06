"""Endpoint ``GET /admin/dashboard/kpis`` (Sprint UI Costes + Reportería
+ Dashboard KPIs, 2026-07-06).

KPIs administrativos agregados para alimentar la nueva vista
``DashboardView.vue`` del admin (sin formularios ni cargas pesadas;
sólo lectura de indicadores).

Reglas:

- ``parking_id`` ausente → agrega TODAS las sucursales activas.
- ``parking_id`` presente → filtra a esa sucursal concreta.
- RBAC: admin-only (la guarda ``require_role("admin")`` rechaza a
  gestor / operador / cliente con 403 antes de tocar la BD). El
  gestor sigue usando ``GET /parkings/{id}/tickets/summary`` para su
  propio dashboard — si en el futuro se quiere exponer este endpoint
  a gestores con parking scope, abrir sprint separado.

Patrones respetados:

- ``require_role("admin")`` en router prefix (``costs.py``,
  ``admin.py``).
- Service ``compute_*`` aislado y testeable sin ``TestClient``
  (``ticket_summary.py``, ``cost.py``).
- ``None`` vs ``0`` para distinguir "sin muestra" de "0 facturado".
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.schemas.dashboard_kpis import DashboardKpisRead
from app.services.dashboard_kpis import compute_dashboard_kpis

router = APIRouter(
    prefix="/admin/dashboard",
    tags=["admin-dashboard"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("/kpis", response_model=DashboardKpisRead)
def get_dashboard_kpis(
    parking_id: Annotated[Optional[int], Query(ge=1)] = None,
    db: Session = Depends(get_db),
) -> DashboardKpisRead:
    """KPIs administrativos agregados.

    Args:
        parking_id: si se pasa, filtra a esa sucursal. Si se omite,
            agrega TODAS las sucursales.
        db: sesión SQLAlchemy (inyectada).

    Returns:
        Espacios (totales / ocupados / libres / rotos), cámaras
        (operativas / en alerta / sin probar) y revenue + costes
        por ventana (24 h / 7 días / 30 días).
    """
    return compute_dashboard_kpis(db, parking_id)


__all__ = ["router"]


