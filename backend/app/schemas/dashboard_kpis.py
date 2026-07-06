"""Esquema de KPIs agregados para el dashboard administrativo.

Sprint UI Costes + Reportería + Dashboard KPIs (2026-07-06).
Pydantic v2 — espejo de ``frontend/src/api/client.ts::DashboardKpis``.

Decisiones de diseño:

- **``None`` vs ``0``**: ``revenue`` y ``costs`` devuelven ``None`` en
  cada ventana si NO hay muestra válida (sin tickets cerrados en
  ventana, sin costes registrados). El frontend distingue "sin datos"
  de "0 € facturados" y muestra ``—``. Mismo patrón que
  ``TicketSummaryRead.total_revenue_24h`` (Fase 4-parte-2).

- **``parking_id: int | None``**: ``None`` significa agregado global
  (suma de TODAS las sucursales). El endpoint devuelve este campo para
  que el frontend confirme el alcance efectivo.

- **Ventanas fijas**: día=24 h, semana=168 h, mes=720 h. Expongo los
  3 valores en el schema para que el frontend renderice la etiqueta
  correcta sin hardcodear.
"""
from __future__ import annotations

from app.schemas import ORMModel


class DashboardSpacesRead(ORMModel):
    """KPIs de plazas de parking.

    ``free`` ya descuenta ``occupied`` y ``broken`` (no es
    ``total - occupied``, sino ``total - occupied - broken``).
    Una plaza rota no cuenta como libre aunque no esté ocupada.
    """

    total: int
    occupied: int
    free: int
    broken: int


class DashboardCamerasRead(ORMModel):
    """KPIs de salud de cámaras.

    - ``operational``: ``last_heartbeat_ok = True`` (último probe OK).
    - ``alert``: ``last_heartbeat_ok = False`` (último probe fallido).
    - ``never_probed``: ``last_heartbeat_at IS NULL AND
      last_heartbeat_ok IS NULL`` (cámara recién dada de alta, sin
      historial).
    """

    total: int
    operational: int
    alert: int
    never_probed: int


class DashboardMoneyPeriodRead(ORMModel):
    """Cantidad de dinero aplicada en 3 ventanas móviles.

    Cada campo puede ser ``None`` si no hay muestra en la ventana.
    """

    day: float | None
    week: float | None
    month: float | None


class DashboardKpisRead(ORMModel):
    """KPIs administrativos agregados.

    Si ``parking_id`` es ``None``, los totales abarcan TODAS las
    sucursales activas. Si es un entero, sólo esa sucursal.
    """

    parking_id: int | None
    spaces: DashboardSpacesRead
    cameras: DashboardCamerasRead
    revenue: DashboardMoneyPeriodRead
    costs: DashboardMoneyPeriodRead
    window_hours_day: int = 24
    window_hours_week: int = 168
    window_hours_month: int = 720


__all__ = [
    "DashboardSpacesRead",
    "DashboardCamerasRead",
    "DashboardMoneyPeriodRead",
    "DashboardKpisRead",
]