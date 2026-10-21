"""API de planes y suscripciones (T-18).

Qué resuelve este router
------------------------
Hasta ahora los planes (``app/models/pricing.py``) sólo los poblaba el
seed: no había forma de crear un plan ni de suscribir a un usuario desde la
aplicación, aunque el descuento ya se aplicaba al cerrar un ticket
(``app/services/pricing.py``). Este router expone esa parte que faltaba.

Decisión D2 (2026-10-21) — cobro **contable**, sin pasarela de pago
-------------------------------------------------------------------------
Se registra la suscripción y su precio, pero **no se cobra nada**: todavía
no hay pasarela de pago porque falta un cliente piloto. Por eso la API
devuelve explícitamente ``billing_mode`` / ``billing_note`` para que la
interfaz se lo diga al cliente en vez de dar a entender que ya se ha
pagado.

RBAC
----
- **admin**: gestiona el catálogo de planes y las suscripciones (alta/baja).
- **cliente**: consulta el catálogo y **sólo su** suscripción ("Mi plan").
- **gestor / operador**: sin planes (403).

Un conductor ve lo suyo
-----------------------
``GET /plans/me`` nunca acepta un ``user_id`` por parámetro: la suscripción
se busca siempre por el id del usuario autenticado, así que nadie puede
pedir la suscripción de otro.

Criterio de caducidad
---------------------
Una suscripción vencida (``ends_at < now``) o dada de baja
(``is_active=False``) **no** aplica descuento. El criterio es exactamente
el de ``app/services/pricing.py`` (ver ``app/services/plans.py``), para que
lo que muestra "Mi plan" sea lo que de verdad se descuenta al cerrar un
ticket.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.pricing import Plan, Subscription
from app.models.user import User
from app.schemas.plan import (
    BILLING_MODE,
    BILLING_NOTE,
    ESTADO_SIN_PLAN,
    ESTADO_VIGENTE,
    MiPlanRead,
    PlanCreate,
    PlanRead,
    PlanResumenRead,
    SubscriptionCreate,
    SubscriptionRead,
    PlanUpdate,
)
from app.services.plans import (
    a_utc,
    ahora_utc,
    dias_restantes,
    estado_suscripcion,
    suscripcion_en_periodo,
    suscripcion_para_mostrar,
)

router = APIRouter(prefix="/plans", tags=["planes"])

#: Roles que pueden consultar el catálogo de planes y su propia suscripción.
ROLES_CONSULTA = (UserRole.ADMIN.value, UserRole.CLIENTE.value)


# ── Helpers ────────────────────────────────────────────────────────────


def _rol(user: User) -> str:
    """Rol del usuario como texto (el enum puede venir como ``str``)."""
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _plan_resumen(plan: Plan) -> PlanResumenRead:
    return PlanResumenRead(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        monthly_price=plan.monthly_price,
        discount_percent=plan.discount_percent,
        included_vehicles=plan.included_vehicles,
    )


def _subscription_read(db: Session, subscription: Subscription) -> SubscriptionRead:
    """Arma la respuesta de una suscripción con su plan y su usuario."""
    plan = db.get(Plan, subscription.plan_id)
    user = db.get(User, subscription.user_id)
    return SubscriptionRead(
        id=subscription.id,
        user_id=subscription.user_id,
        plan_id=subscription.plan_id,
        starts_at=a_utc(subscription.starts_at),
        ends_at=a_utc(subscription.ends_at),
        is_active=bool(subscription.is_active),
        plan=_plan_resumen(plan) if plan is not None else PlanResumenRead(
            id=subscription.plan_id,
            code="",
            name="",
            monthly_price=0.0,
            discount_percent=0.0,
            included_vehicles=0,
        ),
        user_email=user.email if user is not None else "",
        user_full_name=user.full_name if user is not None else "",
        created_at=a_utc(subscription.created_at),
        updated_at=a_utc(subscription.updated_at),
    )


# ── Catálogo de planes ─────────────────────────────────────────────────


@router.get("", response_model=list[PlanRead])
def list_plans(
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(require_role(*ROLES_CONSULTA))],
    only_active: Annotated[
        Optional[bool],
        Query(description="Si se omite: el admin ve todos y el cliente sólo los activos."),
    ] = None,
) -> list[Plan]:
    """Catálogo de planes, del más barato al más caro."""
    if only_active is None:
        only_active = _rol(current) != UserRole.ADMIN.value
    query = db.query(Plan).order_by(Plan.monthly_price.asc(), Plan.id.asc())
    if only_active:
        query = query.filter(Plan.is_active.is_(True))
    return query.all()


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
@audited("create_plan")
def create_plan(
    payload: PlanCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
) -> Plan:
    """Alta de un plan. El ``code`` es único."""
    if db.query(Plan).filter(Plan.code == payload.code).one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un plan con ese código",
        )
    plan = Plan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/me", response_model=MiPlanRead)
def mi_plan(
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(require_role(*ROLES_CONSULTA))],
) -> MiPlanRead:
    """Estado del plan del usuario autenticado (vista "Mi plan").

    Siempre es la suscripción del propio usuario: no hay ``user_id`` en la
    entrada, así que un conductor no puede ver la suscripción de otro.
    """
    ahora = ahora_utc()
    fila = suscripcion_para_mostrar(db, user_id=current.id, at=ahora)
    if fila is None:
        return MiPlanRead(
            status=ESTADO_SIN_PLAN,
            billing_mode=BILLING_MODE,
            billing_note=BILLING_NOTE,
        )
    subscription, plan = fila
    estado = estado_suscripcion(subscription, plan, at=ahora)
    vigente = estado == ESTADO_VIGENTE
    return MiPlanRead(
        status=estado,
        plan=_plan_resumen(plan),
        subscription_id=subscription.id,
        starts_at=a_utc(subscription.starts_at),
        ends_at=a_utc(subscription.ends_at),
        subscription_active=bool(subscription.is_active),
        applies_discount=vigente,
        days_remaining=dias_restantes(subscription.ends_at, at=ahora) if vigente else 0,
        # "Próximo cobro": la renovación al vencer el periodo. El importe es
        # contable (no se cobra todavía, ver decisión D2).
        next_billing_at=a_utc(subscription.ends_at) if vigente else None,
        next_billing_amount=plan.monthly_price if vigente else None,
        billing_mode=BILLING_MODE,
        billing_note=BILLING_NOTE,
    )


@router.get("/subscriptions", response_model=list[SubscriptionRead])
def list_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
    user_id: Annotated[Optional[int], Query(ge=1)] = None,
    plan_id: Annotated[Optional[int], Query(ge=1)] = None,
    only_active: Annotated[bool, Query()] = False,
) -> list[SubscriptionRead]:
    """Lista las suscripciones (sólo admin). Filtros opcionales."""
    query = db.query(Subscription).order_by(Subscription.id.desc())
    if user_id is not None:
        query = query.filter(Subscription.user_id == user_id)
    if plan_id is not None:
        query = query.filter(Subscription.plan_id == plan_id)
    if only_active:
        query = query.filter(Subscription.is_active.is_(True))
    return [_subscription_read(db, s) for s in query.all()]


@router.post("/subscriptions", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
@audited("create_subscription")
def create_subscription(
    payload: SubscriptionCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
) -> SubscriptionRead:
    """Alta de una suscripción.

    Regla de negocio: un usuario tiene **como mucho una** suscripción
    vigente. Si ya tiene una, hay que darla de baja antes (``DELETE
    /plans/subscriptions/{id}``).
    """
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado"
        )
    plan = db.get(Plan, payload.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado"
        )
    if not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede suscribir a un plan desactivado",
        )
    starts_at = a_utc(payload.starts_at)
    ends_at = a_utc(payload.ends_at)
    if ends_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ends_at debe ser posterior a starts_at",
        )
    if suscripcion_en_periodo(db, user_id=user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario ya tiene una suscripción vigente",
        )
    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        starts_at=starts_at,
        ends_at=ends_at,
        is_active=True,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return _subscription_read(db, subscription)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("cancel_subscription", resource_arg="subscription_id")
def cancel_subscription(
    subscription_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
) -> None:
    """Baja de una suscripción.

    Es una **baja lógica**: la suscripción deja de aplicar descuento pero se
    conserva el histórico (tickets ya cerrados con su descuento y la
    trazabilidad contable).
    """
    subscription = db.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada"
        )
    subscription.is_active = False
    db.commit()


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, Depends(require_role(*ROLES_CONSULTA))],
) -> Plan:
    """Detalle de un plan."""
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado"
        )
    return plan


@router.patch("/{plan_id}", response_model=PlanRead)
@audited("update_plan", resource_arg="plan_id")
def update_plan(
    plan_id: int,
    payload: PlanUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
) -> Plan:
    """PATCH parcial de un plan (precio, descuento, estado…)."""
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado"
        )
    data = payload.model_dump(exclude_unset=True)
    nuevo_codigo = data.get("code")
    if nuevo_codigo and nuevo_codigo != plan.code:
        repetido = (
            db.query(Plan)
            .filter(Plan.code == nuevo_codigo, Plan.id != plan_id)
            .one_or_none()
        )
        if repetido is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un plan con ese código",
            )
    for key, value in data.items():
        setattr(plan, key, value)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_plan", resource_arg="plan_id")
def delete_plan(
    plan_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN.value))],
) -> None:
    """Baja de un plan.

    La FK de ``subscriptions.plan_id`` es ``ON DELETE RESTRICT``: un plan con
    suscripciones **no** se puede borrar (el histórico de tickets debe
    sobrevivir). En ese caso hay que desactivarlo (``PATCH is_active=false``).
    """
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado"
        )
    if db.query(Subscription).filter(Subscription.plan_id == plan_id).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El plan tiene suscripciones: desactívalo en lugar de eliminarlo",
        )
    db.delete(plan)
    db.commit()


__all__ = ["router"]
