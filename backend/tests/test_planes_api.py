"""El catálogo de planes y la regla de «una sola suscripción» (T-132, T-133).

**T-132** · un plan **desactivado** no se puede comprar, así que el
cliente no debe verlo. Pero el parámetro ``only_active`` se podía
invertir (``?only_active=false``) y ``GET /plans/{id}`` no filtraba nada:
el cliente veía los planes retired.

**T-133** · la regla «un usuario tiene como mucho una suscripción
vigente» se comprobaba mal: la guardaba miraba la suscripción que
estaba en periodo *ahora*, así que se podían crear dos suscripciones
**solapadas** (la nueva empieza antes de que caduque la otra). Con dos
solapadas, el descuento que se aplica es el máximo y ``/plans/me`` sólo
enseña una: la otra se queda en la contabilidad sin que nadie la vea.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.pricing import Plan, Subscription
from tests._audit_helpers import _login_headers, _seed_admin, _seed_cliente

AHORA = datetime.now(timezone.utc)


def _plan(db: Session, code: str, *, activo: bool = True) -> Plan:
    plan = Plan(
        code=code,
        name=code.upper(),
        monthly_price=100.0,
        discount_percent=20.0,
        included_vehicles=5,
        is_active=activo,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _suscripcion(
    db: Session, user_id: int, plan_id: int, *, desde: datetime, hasta: datetime
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        plan_id=plan_id,
        starts_at=desde,
        ends_at=hasta,
        is_active=True,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# ── T-132 · el catálogo ─────────────────────────────────────────────────


def test_el_cliente_solo_ve_los_planes_activos(
    client: TestClient, db_session: Session
) -> None:
    """Un plan desactivado no aparece en el catálogo del cliente."""
    _seed_cliente(db_session, email="cliente_planes@test.es")
    activo = _plan(db_session, "ACTIVO")
    _plan(db_session, "RETIRADO", activo=False)
    headers = _login_headers(client, "cliente_planes@test.es", "cliente1234")

    r = client.get("/api/v1/plans", headers=headers)
    assert r.status_code == 200, r.text
    assert [p["code"] for p in r.json()] == [activo.code], r.text


def test_el_cliente_no_puede_invertir_el_filtro(
    client: TestClient, db_session: Session
) -> None:
    """``?only_active=false`` no le enseña al cliente los planes retired."""
    _seed_cliente(db_session, email="cliente_planes2@test.es")
    _plan(db_session, "ACTIVO")
    _plan(db_session, "RETIRADO", activo=False)
    headers = _login_headers(client, "cliente_planes2@test.es", "cliente1234")

    r = client.get("/api/v1/plans?only_active=false", headers=headers)
    assert r.status_code == 200, r.text
    assert [p["code"] for p in r.json()] == ["ACTIVO"], r.text


def test_el_detalle_de_un_plan_desactivado_es_un_404_para_el_cliente(
    client: TestClient, db_session: Session
) -> None:
    """Como si el plan no existiera."""
    _seed_cliente(db_session, email="cliente_planes3@test.es")
    retirado = _plan(db_session, "RETIRADO", activo=False)
    headers = _login_headers(client, "cliente_planes3@test.es", "cliente1234")

    r = client.get(f"/api/v1/plans/{retirado.id}", headers=headers)
    assert r.status_code == 404, r.text


def test_el_admin_si_ve_los_planes_desactivados(
    client: TestClient, db_session: Session
) -> None:
    """El admin los tiene que ver (para poder reactivarlos)."""
    _seed_admin(db_session, email="admin_planes@test.es")
    retirado = _plan(db_session, "RETIRADO", activo=False)
    headers = _login_headers(client, "admin_planes@test.es", "admin12345")

    r = client.get("/api/v1/plans", headers=headers)
    assert r.status_code == 200, r.text
    assert "RETIRADO" in [p["code"] for p in r.json()], r.text

    r = client.get(f"/api/v1/plans/{retirado.id}", headers=headers)
    assert r.status_code == 200, r.text


# ── T-133 · la regla de una sola suscripción ─────────────────────────────


def test_no_se_puede_crear_una_suscripcion_que_se_solape_con_otra(
    client: TestClient, db_session: Session
) -> None:
    """La nueva se solapa con una **futura**: 409.

    Es el caso que distingue el defecto: **no** hay ninguna suscripción
    vigente en este instante (la existente empieza dentro de 10 dias),
    pero la nueva se solaparía con ella cuando llegue. La guarda
    anterior (la que mira "la que está en periodo ahora") no lo veía.
    """
    _seed_admin(db_session, email="admin_subs4@test.es")
    cliente = _seed_cliente(db_session, email="cliente_subs4@test.es")
    plan = _plan(db_session, "PLAN")
    headers = _login_headers(client, "admin_subs4@test.es", "admin12345")

    # Existente **futura**: todavia no esta vigente.
    _suscripcion(
        db_session,
        user_id=cliente.id,
        plan_id=plan.id,
        desde=AHORA + timedelta(days=10),
        hasta=AHORA + timedelta(days=40),
    )

    # La nueva empieza dentro de la futura: se solapan.
    r = client.post(
        "/api/v1/plans/subscriptions",
        headers=headers,
        json={
            "user_id": cliente.id,
            "plan_id": plan.id,
            "starts_at": (AHORA + timedelta(days=20)).isoformat(),
            "ends_at": (AHORA + timedelta(days=60)).isoformat(),
        },
    )
    assert r.status_code == 409, r.text


def test_una_suscripcion_vencida_no_bloquea_la_nueva(
    client: TestClient, db_session: Session
) -> None:
    """Control: una suscripción **caducada** no impide contratar otra."""
    _seed_admin(db_session, email="admin_subs5@test.es")
    cliente = _seed_cliente(db_session, email="cliente_subs5@test.es")
    plan = _plan(db_session, "PLAN")
    headers = _login_headers(client, "admin_subs5@test.es", "admin12345")

    # Vencida ayer: no se solapa con la nueva de ahora.
    _suscripcion(
        db_session,
        user_id=cliente.id,
        plan_id=plan.id,
        desde=AHORA - timedelta(days=40),
        hasta=AHORA - timedelta(days=1),
    )

    r = client.post(
        "/api/v1/plans/subscriptions",
        headers=headers,
        json={
            "user_id": cliente.id,
            "plan_id": plan.id,
            "starts_at": AHORA.isoformat(),
            "ends_at": (AHORA + timedelta(days=30)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text


def test_se_puede_renovar_al_vencer_sin_solaparse(
    client: TestClient, db_session: Session
) -> None:
    """Control: la renovación justa (empieza justo cuando caduca) sí vale."""
    _seed_admin(db_session, email="admin_subs3@test.es")
    cliente = _seed_cliente(db_session, email="cliente_subs3@test.es")
    plan = _plan(db_session, "PLAN")
    headers = _login_headers(client, "admin_subs3@test.es", "admin12345")

    caduca = AHORA + timedelta(days=30)
    _suscripcion(
        db_session,
        user_id=cliente.id,
        plan_id=plan.id,
        desde=AHORA - timedelta(days=1),
        hasta=caduca,
    )

    r = client.post(
        "/api/v1/plans/subscriptions",
        headers=headers,
        json={
            "user_id": cliente.id,
            "plan_id": plan.id,
            "starts_at": caduca.isoformat(),
            "ends_at": (caduca + timedelta(days=30)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
