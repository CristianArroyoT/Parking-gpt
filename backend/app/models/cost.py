"""Costes operativos de la sucursal (Sprint P1 solidAPP, 2026-07-06).

Modelo para imputar costes (alquiler de cámaras, mantenimiento,
operación, etc.) por sucursal y poder calcular el **margen** en un
periodo: ``ingresos_tickets_cerrados - costes_aplicados``.

Decisiones de diseño:

- ``periodicity`` distingue costes one-shot (``PUNTUAL``) de recurrentes
  (``MENSUAL``/``TRIMESTRAL``/``ANUAL``). Los recurrentes se prorratean
  dentro del rango del reporte según los días que el ciclo cae dentro.
- ``period_end`` es OBLIGATORIO para ``PUNTUAL`` (validado en schema
  ``CostCreate``) y NULL para recurrentes (el ciclo empieza en
  ``period_start`` y se extiende mientras el reporte lo pida).
- ``description`` es libre (255 chars) para que el gestor documente el
  origen del coste (``"Alquiler cámara 3"``, ``"Limpieza Q3"``...).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.enums import CostCategory, CostPeriod

if TYPE_CHECKING:
    from app.models.parking import Parking


class Cost(Base, TimestampMixin):
    __tablename__ = "costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    parking_id: Mapped[int] = mapped_column(
        ForeignKey("parkings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category: Mapped[CostCategory] = mapped_column(
        Enum(
            CostCategory,
            name="costcategory",
            # Mismo motivo que ``Camera.kind`` (parking.py): la migración
            # 0010 creó el tipo Postgres con los valores en minúscula
            # (``mantenimiento``, ``camaras``...). Sin ``values_callable``
            # SQLAlchemy usaría los nombres mayúsculas del enum y
            # lanzaría ``LookupError`` al leer cualquier fila de Cost.
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Periodicidad declarada al alta. Para recurrentes, ``period_start``
    # marca el inicio del primer ciclo y se itera hacia adelante según
    # ``periodicity``.
    periodicity: Mapped[CostPeriod] = mapped_column(
        Enum(
            CostPeriod,
            name="costperiod",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    # Sólo obligatorio para ``PUNTUAL``. Validado en Pydantic.
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    parking: Mapped["Parking"] = relationship()


__all__ = ["Cost"]