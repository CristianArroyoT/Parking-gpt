"""Esquema del resumen operativo de tickets por sucursal.

Sprint Fase 4-parte-2 (2026-07-06): KPIs que ve el gestor en el dashboard
para una ventana móvil de 24 h. Pensado para render directo en
``DashboardGestor.vue`` (no es histórico ni paginado).
"""
from __future__ import annotations

from app.schemas import ORMModel


class TicketSummaryRead(ORMModel):
    """Resumen agregado de tickets para una sucursal.

    Métricas expuestas:

    - ``total_tickets_24h``: tickets con ``entry_at`` en últimos 24 h.
    - ``active_tickets_now``: tickets con ``status=ACTIVO`` (sin filtro
      temporal; refleja ocupación en el instante de la consulta).
    - ``closed_tickets_24h``: tickets con ``status=CERRADO`` y
      ``exit_at`` en últimos 24 h.
    - ``cancelled_tickets_24h``: tickets con ``status=CANCELADO``
      actualizados en últimos 24 h (cubre cancelaciones recientes; usa
      ``updated_at`` porque ``Ticket.cancelado_at`` no existe).
    - ``total_revenue_24h``: suma de ``total`` (€) sobre tickets cerrados
      en últimos 24 h. ``None`` si no hay tickets cerrados (Pydantic
      ``float`` admite ``None``).
    - ``average_duration_minutes``: media de ``(exit_at - entry_at)`` en
      minutos sobre los tickets cerrados en últimos 24 h con
      ``exit_at`` no nulo. ``None`` si no hay muestra válida.
    - ``window_hours``: ventana móvil aplicada (constante = 24). Útil
      para que el frontend renderice la etiqueta "24 h" sin hardcodear.
    """

    total_tickets_24h: int
    active_tickets_now: int
    closed_tickets_24h: int
    cancelled_tickets_24h: int
    total_revenue_24h: float | None
    average_duration_minutes: float | None
    window_hours: int = 24