"""Lógica de planes y suscripciones (T-18).

Criterio de "suscripción vigente" (la que aplica descuento)
-----------------------------------------------------------
Es **exactamente** el de ``app/services/pricing.py::_compute_discount``:

- ``Subscription.is_active`` es ``True``
- ``Plan.is_active`` es ``True``
- ``starts_at <= at``
- ``ends_at >= at``

No se inventa otro criterio. Si divergieran, el descuento que muestra la
vista "Mi plan" podría no ser el que de verdad se aplica al cerrar un
ticket, y el cliente vería una promesa que el sistema no cumple.

Distinción importante
----------------------
Hay **dos** nociones distintas y este módulo las mantiene separadas:

- ``suscripciones_vigentes``: suscripción + plan activo → **aplica
  descuento**. Es el criterio de precios.
- ``suscripcion_en_periodo``: sólo la suscripción (``is_active`` y dentro
  del periodo), sin mirar el plan → sirve para la regla de negocio "un
  usuario tiene como mucho una suscripción vigente" (si el plan se
  desactivó, la suscripción sigue viva y hay que darla de baja).

Normalización de fechas
-----------------------
SQLite guarda los ``DateTime(timezone=True)`` **sin offset**, así que un
datetime con zona distinto de UTC se compararía mal contra ``now()``. Por
eso todo lo que se escribe pasa por :func:`a_utc`: los naive se interpretan
como UTC y los aware se convierten a UTC. Así SQLite y PostgreSQL (que sí
guarda el instante absoluto) coinciden exactamente.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.pricing import Plan, Subscription
from app.schemas.plan import (
    ESTADO_CADUCADA,
    ESTADO_CANCELADA,
    ESTADO_VIGENTE,
)


def a_utc(dt: datetime) -> datetime:
    """Normaliza un datetime a UTC (naive → se interpreta como UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ahora_utc() -> datetime:
    """Instante actual en UTC."""
    return datetime.now(timezone.utc)


def suscripciones_vigentes(
    db: Session, *, user_id: int, at: datetime | None = None
) -> list[tuple[Subscription, Plan]]:
    """Suscripciones de ``user_id`` que aplican descuento en ``at``.

    Devuelve las parejas ``(suscripción, plan)`` que cumplen el criterio de
    precios (ver el docstring del módulo).
    """
    instante = a_utc(at or ahora_utc())
    filas = (
        db.query(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
            Plan.is_active.is_(True),
            Subscription.starts_at <= instante,
            Subscription.ends_at >= instante,
        )
        .all()
    )
    return [(suscripcion, plan) for suscripcion, plan in filas]


def plan_vigente(
    db: Session, *, user_id: int, at: datetime | None = None
) -> tuple[Subscription, Plan] | None:
    """Suscripción vigente **con el mayor descuento** (criterio de precios).

    ``pricing.py`` aplica el mayor ``discount_percent`` de entre las
    suscripciones vigentes; aquí se replica esa elección para que "Mi plan"
    enseñe el mismo descuento que se va a aplicar.
    """
    filas = suscripciones_vigentes(db, user_id=user_id, at=at)
    if not filas:
        return None
    return max(filas, key=lambda fila: fila[1].discount_percent)


def suscripcion_en_periodo(
    db: Session, *, user_id: int, at: datetime | None = None
) -> Subscription | None:
    """Suscripción con ``is_active`` dentro del periodo (sin mirar el plan).

    Sirve para la regla de negocio "un usuario tiene como mucho una
    suscripción vigente": si el plan se desactivó, la suscripción sigue
    viva y hay que darla de baja explícitamente.
    """
    instante = a_utc(at or ahora_utc())
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
            Subscription.starts_at <= instante,
            Subscription.ends_at >= instante,
        )
        .order_by(Subscription.ends_at.desc(), Subscription.id.desc())
        .first()
    )


def suscripcion_para_mostrar(
    db: Session, *, user_id: int, at: datetime | None = None
) -> tuple[Subscription, Plan] | None:
    """Suscripción que describe el plan del usuario en la vista "Mi plan".

    Prioriza la vigente; si no hay ninguna, devuelve la más reciente (vencida
    o cancelada) para que el cliente vea **por qué** no tiene descuento en
    lugar de un "no tienes plan" vacío.
    """
    vigente = plan_vigente(db, user_id=user_id, at=at)
    if vigente is not None:
        return vigente
    fila = (
        db.query(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.ends_at.desc(), Subscription.id.desc())
        .first()
    )
    if fila is None:
        return None
    return fila[0], fila[1]


def estado_suscripcion(
    subscription: Subscription, plan: Plan, *, at: datetime | None = None
) -> str:
    """Estado legible de la suscripción: vigente / caducada / cancelada."""
    instante = a_utc(at or ahora_utc())
    if not subscription.is_active:
        return ESTADO_CANCELADA
    # SQLite devuelve los DateTime(timezone=True) *naive* (no guarda el
    # offset), así que hay que normalizarlos antes de comparar.
    if a_utc(subscription.starts_at) > instante or a_utc(subscription.ends_at) < instante:
        return ESTADO_CADUCADA
    if not plan.is_active:
        return ESTADO_CADUCADA
    return ESTADO_VIGENTE


def dias_restantes(ends_at: datetime, *, at: datetime | None = None) -> int:
    """Días que quedan hasta ``ends_at`` (0 si ya venció)."""
    instante = a_utc(at or ahora_utc())
    restante = (a_utc(ends_at) - instante).days
    return max(0, restante)


__all__ = [
    "a_utc",
    "ahora_utc",
    "dias_restantes",
    "estado_suscripcion",
    "plan_vigente",
    "suscripcion_en_periodo",
    "suscripcion_para_mostrar",
    "suscripciones_vigentes",
]
