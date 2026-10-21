"""Concentrador de routers v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    alerts,
    auth,
    cameras,
    cameras_live,
    cliente,
    costs,
    dashboard,
    events,
    face_templates,
    incidents,
    logout_all,
    parkings,
    password_reset,
    plans,
    plates,
    reports,
    spaces,
    tariffs,
    ticket_summary,
    tickets,
    users,
    vehicles,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(logout_all.router)
# T-22 (2026-10-21): recuperación de contraseña por correo (token de un
# solo uso, hasheado en BD). Routers separados para no tocar auth.py.
api_router.include_router(password_reset.router)
api_router.include_router(users.router)
api_router.include_router(parkings.router)
api_router.include_router(spaces.router)
api_router.include_router(cameras.router)
# Sprint Live-Preview (2026-07-07): stream MJPEG en vivo, requiere
# ?token=... porque se consume desde <img> del navegador.
api_router.include_router(cameras_live.router)
api_router.include_router(vehicles.router)
api_router.include_router(tariffs.router)
# T-18 (2026-10-21): CRUD de planes + alta/baja de suscripciones. El
# descuento ya se aplicaba al cerrar el ticket, pero nadie podía crear
# planes ni suscribir usuarios desde la aplicación.
api_router.include_router(plans.router)
api_router.include_router(tickets.router)
# Sprint Fase 4-parte-2: resumen operativo de tickets por sucursal (24 h).
api_router.include_router(ticket_summary.router)
api_router.include_router(plates.router)
api_router.include_router(alerts.router)
api_router.include_router(incidents.router)
# Sprint Fase 3A: endpoint admin-only de lectura de audit_logs.
api_router.include_router(admin.router)
# Sprint P1: CRUD de costes operativos + reporte de margen (admin/gestor).
api_router.include_router(costs.router)
api_router.include_router(reports.router)
# Sprint UI Costes + Dashboard KPIs: KPIs agregados (admin-only).
api_router.include_router(dashboard.router)
# Sprint O2 (2026-07-06): stream SSE por sucursal para refresco live de MapView.
api_router.include_router(events.router)
# T-23 (2026-10-21): estructura de reconocimiento facial PREPARADA pero
# FUERA del MVP. El router responde 404 mientras el feature flag
# FACE_TEMPLATES_ENABLED esté apagado (valor por defecto) y NO se usa en
# el login.
api_router.include_router(face_templates.router)
# T-24 (2026-10-21): pantallas del cliente final (PWA instalable) —
# "mi plaza" y "mis tickets" con el scope de los vehículos del propio
# cliente. El router de planes (T-18) expone su propio "mi plan" con el
# mismo criterio de vigencia que aplica el descuento al cerrar el ticket.
api_router.include_router(cliente.router)

__all__ = ["api_router"]
