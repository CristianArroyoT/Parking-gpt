"""Concentrador de routers v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    alerts,
    auth,
    cameras,
    incidents,
    parkings,
    plates,
    spaces,
    tariffs,
    ticket_summary,
    tickets,
    users,
    vehicles,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(parkings.router)
api_router.include_router(spaces.router)
api_router.include_router(cameras.router)
api_router.include_router(vehicles.router)
api_router.include_router(tariffs.router)
api_router.include_router(tickets.router)
# Sprint Fase 4-parte-2: resumen operativo de tickets por sucursal (24 h).
api_router.include_router(ticket_summary.router)
api_router.include_router(plates.router)
api_router.include_router(alerts.router)
api_router.include_router(incidents.router)
# Sprint Fase 3A: endpoint admin-only de lectura de audit_logs.
api_router.include_router(admin.router)

__all__ = ["api_router"]
