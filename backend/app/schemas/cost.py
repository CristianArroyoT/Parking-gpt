"""Esquemas Pydantic para ``Cost`` (Sprint P1 solidAPP, 2026-07-06).

Validaciones de negocio (no sólo de tipos):

- ``period_end`` es obligatorio cuando ``periodicity == PUNTUAL`` y debe
  ser estrictamente posterior a ``period_start``.
- Para periodicidades recurrentes (``MENSUAL``/``TRIMESTRAL``/``ANUAL``)
  ``period_end`` debe ser NULL: el ciclo se extiende hacia adelante
  mientras el reporte lo pida.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field, model_validator

from app.models.enums import CostCategory, CostPeriod
from app.schemas import ORMModel, TimestampMixinSchema


class CostBase(ORMModel):
    parking_id: int = Field(ge=1)
    category: CostCategory
    amount: float = Field(gt=0, description="Importe en euros. Positivo.")
    periodicity: CostPeriod
    period_start: datetime
    period_end: Optional[datetime] = None
    description: Optional[str] = Field(default=None, max_length=255)


class CostCreate(CostBase):
    """Alta de un coste. Valida coherencia entre ``periodicity`` y
    ``period_end``."""

    @model_validator(mode="after")
    def _check_period(self) -> "CostCreate":
        if self.periodicity is CostPeriod.PUNTUAL:
            if self.period_end is None:
                raise ValueError(
                    "Costes puntuales requieren period_end",
                )
            if self.period_end <= self.period_start:
                raise ValueError(
                    "period_end debe ser posterior a period_start",
                )
        else:
            # Recurrentes: period_end se ignora si viene.
            if self.period_end is not None:
                raise ValueError(
                    "Costes recurrentes no admiten period_end",
                )
        return self


class CostUpdate(ORMModel):
    """PATCH parcial. Si se cambia la ``periodicity`` hay que revisar
    ``period_end`` (validado en el handler con un check análogo)."""

    category: Optional[CostCategory] = None
    amount: Optional[float] = Field(default=None, gt=0)
    periodicity: Optional[CostPeriod] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    description: Optional[str] = Field(default=None, max_length=255)


class CostRead(CostBase, TimestampMixinSchema):
    id: int


__all__ = ["CostCreate", "CostUpdate", "CostRead"]