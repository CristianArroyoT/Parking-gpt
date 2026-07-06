"""Esquemas para el reporte de margen por sucursal (Sprint P1).

El reporte combina:

- Ingresos por tickets cerrados en el periodo.
- Costes operativos (prorrateados por días dentro del rango del reporte).
- Margen = ingresos − costes.

El desglose por categoría de coste facilita auditoría y exportación
CSV (cada fila del CSV es un ``CostBreakdownEntry``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.enums import CostCategory
from app.schemas import ORMModel


class CostBreakdownEntry(ORMModel):
    """Una fila del desglose por categoría de coste."""

    category: CostCategory
    amount: float = Field(
        description="Suma de costes aplicados (prorrateados) en el periodo.",
    )
    cost_count: int = Field(
        description="Número de costes distintos que aportaron a este total.",
    )


class MarginReportRead(ORMModel):
    """Reporte completo de margen para una sucursal y un rango."""

    parking_id: int
    parking_name: str
    from_: datetime = Field(alias="from")
    to: datetime
    total_revenue: float = Field(
        description="Suma de Ticket.total para tickets CERRADOS en el rango.",
    )
    closed_tickets: int
    total_costs: float = Field(
        description="Suma de costes prorrateados aplicados al rango.",
    )
    margin: float = Field(description="total_revenue − total_costs")
    cost_breakdown: list[CostBreakdownEntry]


__all__ = ["CostBreakdownEntry", "MarginReportRead"]