"""Tests del módulo de planes y suscripciones (T-18).

Cubre:

1. CRUD de planes (alta, listado, patch, baja) con su RBAC.
2. Alta/baja de suscripciones y la vista "Mi plan" del cliente.
3. Aislamiento entre usuarios: un conductor sólo ve **su** suscripción.
4. Caducidad: una suscripción vencida o dada de baja **no** aplica descuento.
5. El criterio de aceptación del plan maestro: alta de plan → suscripción →
   cierre de ticket → ``discount`` = porcentaje esperado.

Los tests corren en SQLite (por defecto) y en PostgreSQL (con
``TEST_DATABASE_URL``), que es el dialecto de producción: por eso todas las
fechas van en UTC explícito (``...Z``) para que ambos motores coincidan.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import VehicleRole
from app.models.pricing import Tariff
from app.models.vehicle import Vehicle, VehicleUser
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_gestor,
    _seed_parking,
    assert_audit_log,
)

# ── Helpers ────────────────────────────────────────────────────────────

#: Inicio y fin del periodo de una suscripción de prueba (UTC).
_INICIO = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FIN = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _plan_payload(code: str = "empresa", discount: float = 20.0) -> dict[str, Any]:
    return {
        "code": code,
        "name": "Empresa",
        "monthly_price": 200.0,
        "discount_percent": discount,
        "included_vehicles": 10,
    }


def _suscripcion_payload(user_id: int, plan_id: int) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "plan_id": plan_id,
        "starts_at": _INICIO.isoformat(),
        "ends_at": _FIN.isoformat(),
    }


def _crear_plan(client: TestClient, headers: dict[str, str], **kwargs: Any) -> dict[str, Any]:
    payload = _plan_payload(**kwargs)
    r = client.post("/api/v1/plans", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _sembrar_tarifa(db: Session, parking_id: int) -> None:
    db.add(
        Tariff(
            parking_id=parking_id,
            name="Estándar",
            price_per_hour=2.0,
            price_per_fraction=0.5,
            fraction_minutes=15,
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.commit()


def _sembrar_vehiculo_de(
    db: Session, user_id: int, plate: str
) -> Vehicle:
    """Vehículo vinculado al usuario (propietario)."""
    vehiculo = Vehicle(plate=plate)
    db.add(vehiculo)
    db.flush()
    db.add(
        VehicleUser(
            vehicle_id=vehiculo.id,
            user_id=user_id,
            role=VehicleRole.PROPIETARIO,
        )
    )
    db.commit()
    return vehiculo


# ── CRUD de planes ─────────────────────────────────────────────────────


def test_alta_de_plan_admin(client: TestClient, db_session: Session) -> None:
    """El admin crea un plan → 201 y el plan queda en el catálogo."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post("/api/v1/plans", json=_plan_payload(), headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "empresa"
    assert body["name"] == "Empresa"
    assert body["monthly_price"] == 200.0
    assert body["discount_percent"] == 20.0
    assert body["included_vehicles"] == 10
    assert body["is_active"] is True

    listado = client.get("/api/v1/plans", headers=headers)
    assert listado.status_code == 200
    assert [p["code"] for p in listado.json()] == ["empresa"]

    assert_audit_log(db_session, action="create_plan", user_id=admin.id, result="success")


def test_alta_de_plan_con_codigo_duplicado_409(
    client: TestClient, db_session: Session
) -> None:
    """El ``code`` del plan es único."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    _crear_plan(client, headers)

    r = client.post("/api/v1/plans", json=_plan_payload(), headers=headers)
    assert r.status_code == 409, r.text
    assert "código" in r.json()["detail"].lower()


def test_cliente_no_puede_crear_planes(client: TestClient, db_session: Session) -> None:
    """El cliente no gestiona el catálogo → 403."""
    cliente = _seed_cliente(db_session, email="cli-plan-403@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.post("/api/v1/plans", json=_plan_payload(), headers=headers)
    assert r.status_code == 403, r.text


def test_gestor_no_tiene_planes(client: TestClient, db_session: Session) -> None:
    """El gestor no gestiona planes: ni siquiera puede ver el catálogo."""
    gestor = _seed_gestor(db_session, email="ges-plan-403@test.es")
    headers = _login_headers(client, gestor.email, "gestor1234")

    assert client.get("/api/v1/plans", headers=headers).status_code == 403
    assert client.post("/api/v1/plans", json=_plan_payload(), headers=headers).status_code == 403


def test_listado_de_planes_el_cliente_solo_ve_activos(
    client: TestClient, db_session: Session
) -> None:
    """El admin ve los planes desactivados; el cliente sólo los activos."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-cat@test.es")
    headers_admin = _login_headers(client, admin.email, "admin12345")
    _crear_plan(client, headers_admin, code="basico")
    familiar = _crear_plan(client, headers_admin, code="familiar")

    r = client.patch(
        f"/api/v1/plans/{familiar['id']}", json={"is_active": False}, headers=headers_admin
    )
    assert r.status_code == 200, r.text

    visto_admin = client.get("/api/v1/plans", headers=headers_admin)
    assert visto_admin.status_code == 200
    assert len(visto_admin.json()) == 2

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    visto_cliente = client.get("/api/v1/plans", headers=headers_cliente)
    assert visto_cliente.status_code == 200
    assert [p["code"] for p in visto_cliente.json()] == ["basico"]


def test_patch_de_plan(client: TestClient, db_session: Session) -> None:
    """El admin edita precio y descuento."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    r = client.patch(
        f"/api/v1/plans/{plan['id']}",
        json={"monthly_price": 250.0, "discount_percent": 25.0},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["monthly_price"] == 250.0
    assert r.json()["discount_percent"] == 25.0

    assert_audit_log(
        db_session,
        action="update_plan",
        resource=f"plans/{plan['id']}",
        user_id=admin.id,
        result="success",
    )


def test_baja_de_plan_sin_suscripciones(client: TestClient, db_session: Session) -> None:
    """Un plan sin suscripciones se puede borrar (204)."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    r = client.delete(f"/api/v1/plans/{plan['id']}", headers=headers)
    assert r.status_code == 204, r.text
    assert client.get(f"/api/v1/plans/{plan['id']}", headers=headers).status_code == 404


def test_baja_de_plan_con_suscripciones_409(
    client: TestClient, db_session: Session
) -> None:
    """Un plan con suscripciones no se borra: el histórico debe sobrevivir."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-restrict@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    alta = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert alta.status_code == 201, alta.text

    r = client.delete(f"/api/v1/plans/{plan['id']}", headers=headers)
    assert r.status_code == 409, r.text


# ── Suscripciones ──────────────────────────────────────────────────────


def test_alta_de_suscripcion(client: TestClient, db_session: Session) -> None:
    """El admin suscribe a un cliente a un plan."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-sub@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    r = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_id"] == cliente.id
    assert body["plan_id"] == plan["id"]
    assert body["is_active"] is True
    assert body["plan"]["discount_percent"] == 20.0
    assert body["user_email"] == cliente.email

    assert_audit_log(
        db_session, action="create_subscription", user_id=admin.id, result="success"
    )


def test_alta_de_suscripcion_con_usuario_inexistente_404(
    client: TestClient, db_session: Session
) -> None:
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    r = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(99999, plan["id"]),
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_suscripcion_con_periodo_invalido_422(
    client: TestClient, db_session: Session
) -> None:
    """``ends_at`` tiene que ser posterior a ``starts_at``."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-periodo@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    r = client.post(
        "/api/v1/plans/subscriptions",
        json={
            "user_id": cliente.id,
            "plan_id": plan["id"],
            "starts_at": _FIN.isoformat(),
            "ends_at": _INICIO.isoformat(),
        },
        headers=headers,
    )
    assert r.status_code == 422, r.text


def test_no_se_puede_suscribir_dos_veces_en_el_mismo_periodo(
    client: TestClient, db_session: Session
) -> None:
    """Un usuario tiene como mucho una suscripción vigente."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-doble@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    primero = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert primero.status_code == 201, primero.text

    segundo = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert segundo.status_code == 409, segundo.text


def test_baja_de_suscripcion(client: TestClient, db_session: Session) -> None:
    """La baja es lógica: la suscripción deja de aplicar descuento."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-baja@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    alta = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert alta.status_code == 201, alta.text
    sub_id = alta.json()["id"]

    r = client.delete(f"/api/v1/plans/subscriptions/{sub_id}", headers=headers)
    assert r.status_code == 204, r.text

    # La suscripción sigue existiendo (histórico) pero ya no aplica descuento.
    listado = client.get("/api/v1/plans/subscriptions", headers=headers)
    assert listado.status_code == 200
    assert listado.json()[0]["is_active"] is False

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    mi = client.get("/api/v1/plans/me", headers=headers_cliente)
    assert mi.status_code == 200
    assert mi.json()["applies_discount"] is False
    assert mi.json()["status"] == "cancelada"
    assert mi.json()["next_billing_at"] is None

    assert_audit_log(
        db_session,
        action="cancel_subscription",
        resource=f"subscriptions/{sub_id}",
        user_id=admin.id,
        result="success",
    )


# ── "Mi plan" ──────────────────────────────────────────────────────────


def test_mi_plan_muestra_el_plan_del_cliente(
    client: TestClient, db_session: Session
) -> None:
    """El cliente ve su plan: % de descuento, alta, vencimiento y próximo cobro."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-miplan@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)
    client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/plans/me", headers=headers_cliente)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "vigente"
    assert body["plan"]["name"] == "Empresa"
    assert body["plan"]["discount_percent"] == 20.0
    assert body["applies_discount"] is True
    assert body["starts_at"].startswith("2026-01-01")
    assert body["ends_at"].startswith("2027-01-01")
    # Próximo cobro: la renovación al vencer el periodo.
    assert body["next_billing_at"].startswith("2027-01-01")
    assert body["next_billing_amount"] == 200.0
    # Cobro contable (decisión D2): se registra, pero no se cobra.
    assert body["billing_mode"] == "contable"
    assert "no se cobra" in body["billing_note"].lower()


def test_mi_plan_sin_suscripcion(client: TestClient, db_session: Session) -> None:
    """Sin suscripción, "Mi plan" lo dice claramente."""
    cliente = _seed_cliente(db_session, email="cli-sinplan@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.get("/api/v1/plans/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sin_plan"
    assert body["plan"] is None
    assert body["applies_discount"] is False
    assert body["next_billing_at"] is None


def test_un_cliente_no_ve_la_suscripcion_de_otro(
    client: TestClient, db_session: Session
) -> None:
    """Cada usuario ve sólo lo suyo: la suscripción es de un ``user_id``."""
    admin = _seed_admin(db_session)
    uno = _seed_cliente(db_session, email="uno@test.es")
    otro = _seed_cliente(db_session, email="otro@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    alta = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(otro.id, plan["id"]),
        headers=headers,
    )
    assert alta.status_code == 201, alta.text

    headers_uno = _login_headers(client, uno.email, "cliente1234")
    r = client.get("/api/v1/plans/me", headers=headers_uno)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sin_plan"
    assert body["plan"] is None
    assert body["subscription_id"] is None


def test_mi_plan_de_suscripcion_caducada(
    client: TestClient, db_session: Session
) -> None:
    """Una suscripción vencida no aplica descuento."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-caduca@test.es")
    headers = _login_headers(client, admin.email, "admin12345")
    plan = _crear_plan(client, headers)

    ahora = datetime.now(timezone.utc)
    client.post(
        "/api/v1/plans/subscriptions",
        json={
            "user_id": cliente.id,
            "plan_id": plan["id"],
            "starts_at": (ahora - timedelta(days=90)).isoformat(),
            "ends_at": (ahora - timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/plans/me", headers=headers_cliente)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "caducada"
    assert body["applies_discount"] is False
    assert body["next_billing_at"] is None
    assert body["next_billing_amount"] is None


# ── Criterio de aceptación del plan maestro ────────────────────────────


def test_alta_plan_suscripcion_cierre_ticket_aplica_descuento(
    client: TestClient, db_session: Session
) -> None:
    """Alta de plan → suscripción → cierre de ticket → descuento esperado.

    Es el criterio de aceptación de T-18: el descuento del ticket cerrado
    tiene que ser exactamente el porcentaje del plan (20 % de 4,00 € = 0,80 €).
    """
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-flujo@test.es")
    parking = _seed_parking(db_session, code="P-PLAN")
    _sembrar_tarifa(db_session, parking.id)
    vehiculo = _sembrar_vehiculo_de(db_session, cliente.id, "2222-PLN")
    headers = _login_headers(client, admin.email, "admin12345")

    # 1) Alta del plan.
    plan = _crear_plan(client, headers, code="empresa", discount=20.0)

    # 2) Alta de la suscripción del cliente.
    alta = client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )
    assert alta.status_code == 201, alta.text

    # 3) Ticket de 2 horas con ese vehículo.
    creado = client.post(
        "/api/v1/tickets",
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": "2026-06-01T09:00:00Z",
        },
        headers=headers,
    )
    assert creado.status_code == 201, creado.text
    ticket_id = creado.json()["id"]

    # 4) Cierre del ticket.
    cerrado = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        json={"exit_at": "2026-06-01T11:00:00Z"},
        headers=headers,
    )
    assert cerrado.status_code == 200, cerrado.text
    body = cerrado.json()
    assert body["amount"] == 4.0                    # 2 h × 2,00 €/h
    assert body["discount"] == pytest.approx(0.8)  # 20 % de 4,00 €
    assert body["total"] == pytest.approx(3.2)
    assert body["status"] == "cerrado"


def test_suscripcion_caducada_no_descuenta_al_cerrar_ticket(
    client: TestClient, db_session: Session
) -> None:
    """El mismo flujo con la suscripción vencida → el ticket NO se descuenta."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-caduca-ticket@test.es")
    parking = _seed_parking(db_session, code="P-PLAN-CAD")
    _sembrar_tarifa(db_session, parking.id)
    vehiculo = _sembrar_vehiculo_de(db_session, cliente.id, "3333-PLN")
    headers = _login_headers(client, admin.email, "admin12345")

    plan = _crear_plan(client, headers, code="familiar", discount=10.0)

    ahora = datetime.now(timezone.utc)
    alta = client.post(
        "/api/v1/plans/subscriptions",
        json={
            "user_id": cliente.id,
            "plan_id": plan["id"],
            "starts_at": (ahora - timedelta(days=90)).isoformat(),
            "ends_at": (ahora - timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )
    assert alta.status_code == 201, alta.text

    creado = client.post(
        "/api/v1/tickets",
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": "2026-06-01T09:00:00Z",
        },
        headers=headers,
    )
    assert creado.status_code == 201, creado.text
    ticket_id = creado.json()["id"]

    cerrado = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        json={"exit_at": "2026-06-01T11:00:00Z"},
        headers=headers,
    )
    assert cerrado.status_code == 200, cerrado.text
    body = cerrado.json()
    assert body["amount"] == 4.0
    assert body["discount"] == 0.0
    assert body["total"] == 4.0


def test_plan_desactivado_no_descuenta_al_cerrar_ticket(
    client: TestClient, db_session: Session
) -> None:
    """Si el admin desactiva el plan, el descuento deja de aplicarse."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-plan-off@test.es")
    parking = _seed_parking(db_session, code="P-PLAN-OFF")
    _sembrar_tarifa(db_session, parking.id)
    vehiculo = _sembrar_vehiculo_de(db_session, cliente.id, "4444-PLN")
    headers = _login_headers(client, admin.email, "admin12345")

    plan = _crear_plan(client, headers, code="basico", discount=5.0)
    client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(cliente.id, plan["id"]),
        headers=headers,
    )

    desactivado = client.patch(
        f"/api/v1/plans/{plan['id']}", json={"is_active": False}, headers=headers
    )
    assert desactivado.status_code == 200, desactivado.text

    creado = client.post(
        "/api/v1/tickets",
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": "2026-06-01T09:00:00Z",
        },
        headers=headers,
    )
    assert creado.status_code == 201, creado.text
    ticket_id = creado.json()["id"]

    cerrado = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        json={"exit_at": "2026-06-01T11:00:00Z"},
        headers=headers,
    )
    assert cerrado.status_code == 200, cerrado.text
    assert cerrado.json()["discount"] == 0.0


def test_suscripcion_de_otro_usuario_no_descuenta(
    client: TestClient, db_session: Session
) -> None:
    """El descuento es el de **quien conduce el vehículo**, no el de otro."""
    admin = _seed_admin(db_session)
    cliente = _seed_cliente(db_session, email="cli-conductor@test.es")
    suscriptor = _seed_cliente(db_session, email="cli-suscriptor@test.es")
    parking = _seed_parking(db_session, code="P-PLAN-OTRO")
    _sembrar_tarifa(db_session, parking.id)
    vehiculo = _sembrar_vehiculo_de(db_session, cliente.id, "5555-PLN")
    headers = _login_headers(client, admin.email, "admin12345")

    plan = _crear_plan(client, headers, code="empresa", discount=20.0)
    client.post(
        "/api/v1/plans/subscriptions",
        json=_suscripcion_payload(suscriptor.id, plan["id"]),
        headers=headers,
    )

    creado = client.post(
        "/api/v1/tickets",
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": "2026-06-01T09:00:00Z",
        },
        headers=headers,
    )
    assert creado.status_code == 201, creado.text
    ticket_id = creado.json()["id"]

    cerrado = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        json={"exit_at": "2026-06-01T11:00:00Z"},
        headers=headers,
    )
    assert cerrado.status_code == 200, cerrado.text
    assert cerrado.json()["discount"] == 0.0
