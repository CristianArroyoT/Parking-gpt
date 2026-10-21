"""Esquemas Pydantic del módulo de planes y suscripciones (T-18).

Decisión D2 (2026-10-21)
------------------------
El cobro de los planes es **contable**, no real: se registra la suscripción
y su precio, pero **no se cobra nada** porque todavía no hay pasarela de
pago (falta un cliente piloto). Por eso la API expone el modo de cobro
(``BILLING_MODE``) y su explicación (``BILLING_NOTE``) para que la interfaz
pueda decirlo explícitamente al cliente en vez de dar a entender que ya se
ha pagado.

Los esquemas viven en su propio fichero (y no en ``app/schemas/pricing.py``)
porque este módulo tiene su propio contrato: el de las suscripciones de un
usuario (alta, baja y "mi plan") y el desglose que la interfaz necesita
para explicarle al cliente su descuento.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field, model_validator

from app.schemas import ORMModel, TimestampMixinSchema

#: Modo de cobro vigente (decisión D2): el importe se registra pero no se cobra.
BILLING_MODE = "contable"

#: Texto que la interfaz muestra al cliente para explicar el modo de cobro.
BILLING_NOTE = (
    "Cobro contable: el importe del plan se registra en el sistema, pero "
    "todavía no se cobra nada porque no hay pasarela de pago."
)

#: Estado de la suscripción tal y como lo ve el cliente en "Mi plan".
ESTADO_VIGENTE = "vigente"
ESTADO_CADUCADA = "caducada"
ESTADO_CANCELADA = "cancelada"
ESTADO_SIN_PLAN = "sin_plan"


class PlanCreate(ORMModel):
    """Alta de un plan de suscripción.

    ``discount_percent`` es el mismo porcentaje que aplica el servicio de
    precios (``app/services/pricing.py``) al cerrar un ticket.
    ``included_vehicles`` es informativo (nº de vehículos que cubre el plan);
    el descuento no depende de él.
    """

    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=64)
    monthly_price: float = Field(ge=0)
    discount_percent: float = Field(ge=0, le=100)
    included_vehicles: int = Field(ge=0)
    is_active: bool = True


class PlanUpdate(ORMModel):
    """PATCH parcial de un plan (todos los campos opcionales)."""

    code: Optional[str] = Field(default=None, min_length=2, max_length=32)
    name: Optional[str] = Field(default=None, min_length=2, max_length=64)
    monthly_price: Optional[float] = Field(default=None, ge=0)
    discount_percent: Optional[float] = Field(default=None, ge=0, le=100)
    included_vehicles: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class PlanRead(ORMModel, TimestampMixinSchema):
    """Plan tal y como lo devuelve la API."""

    id: int
    code: str
    name: str
    monthly_price: float
    discount_percent: float
    included_vehicles: int
    is_active: bool


class PlanResumenRead(ORMModel):
    """Datos del plan que necesita la vista "Mi plan" (sin metadatos)."""

    id: int
    code: str
    name: str
    monthly_price: float
    discount_percent: float
    included_vehicles: int


class SubscriptionCreate(ORMModel):
    """Alta de una suscripción (la hace el administrador)."""

    user_id: int = Field(ge=1)
    plan_id: int = Field(ge=1)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _check_period(self) -> "SubscriptionCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
        return self


class SubscriptionRead(ORMModel, TimestampMixinSchema):
    """Suscripción con el plan y el usuario (vista del administrador)."""

    id: int
    user_id: int
    plan_id: int
    starts_at: datetime
    ends_at: datetime
    is_active: bool
    plan: PlanResumenRead
    user_email: str
    user_full_name: str


class MiPlanRead(ORMModel):
    """Estado del plan del cliente para la vista "Mi plan".

    ``applies_discount`` indica si la suscripción aplica descuento **ahora
    mismo**, con el mismo criterio que el servicio de precios. Si no hay
    ninguna suscripción, ``plan`` es ``null`` y ``status`` vale
    ``"sin_plan"``.
    """

    status: str = ESTADO_SIN_PLAN
    plan: Optional[PlanResumenRead] = None
    subscription_id: Optional[int] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    subscription_active: bool = False
    applies_discount: bool = False
    days_remaining: Optional[int] = None
    next_billing_at: Optional[datetime] = None
    next_billing_amount: Optional[float] = None
    billing_mode: str = BILLING_MODE
    billing_note: str = BILLING_NOTE


__all__ = [
    "BILLING_MODE",
    "BILLING_NOTE",
    "ESTADO_CADUCADA",
    "ESTADO_CANCELADA",
    "ESTADO_SIN_PLAN",
    "ESTADO_VIGENTE",
    "MiPlanRead",
    "PlanCreate",
    "PlanResumenRead",
    "PlanRead",
    "PlanUpdate",
    "SubscriptionCreate",
    "SubscriptionRead",
]
