"""Tests del CRUD de costes operativos (Sprint P1 solidAPP).

Cubre los 5 endpoints de ``/admin/costs`` con foco en:

- RBAC: sólo admin puede listar/CRUD. Gestor → 403.
- Validación de schema: ``PUNTUAL`` requiere ``period_end`` y posterior
  a ``period_start``. Recurrentes NO admiten ``period_end``.
- Filtros: parking_id, category, periodicity, rango temporal.
- Auditoría: POST/PATCH/DELETE dejan audit_log con la action
  correspondiente.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.cost import Cost
from app.models.enums import CostCategory, CostPeriod
from tests import _audit_helpers as ah


def _payload(**overrides) -> dict:
    base = {
        "parking_id": 1,
        "category": CostCategory.MANTENIMIENTO.value,
        "amount": 150.0,
        "periodicity": CostPeriod.PUNTUAL.value,
        "period_start": "2026-01-01T00:00:00+00:00",
        "period_end": "2026-01-31T00:00:00+00:00",
        "description": "Limpieza Enero",
    }
    base.update(overrides)
    return base


# ── POST /admin/costs ─────────────────────────────────────────────────


def test_create_cost_admin_success(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR1")
    admin = ah._seed_admin(db_session, email="admin-c1@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")
    payload = _payload(parking_id=parking.id)
    r = client.post("/api/v1/admin/costs", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0
    assert body["amount"] == 150.0
    assert body["category"] == "mantenimiento"
    # ``create_cost`` no usa ``resource_arg`` (no hay ``cost_id`` en el
    # payload POST), así que el audit tiene ``resource=None``. Filtramos
    # sólo por action + user_id.
    ah.assert_audit_log(
        db_session, action="create_cost", user_id=admin.id,
    )


def test_create_cost_gestor_forbidden(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR2")
    gestor = ah._seed_gestor(db_session, email="gestor-c1@test.es")
    ah._seed_membership(db_session, user=gestor, parking=parking)
    headers = ah._login_headers(client, gestor.email, "gestor1234")
    r = client.post(
        "/api/v1/admin/costs", headers=headers,
        json=_payload(parking_id=parking.id),
    )
    assert r.status_code == 403
    ah.assert_no_audit_log(db_session, action="create_cost")


def test_create_cost_puntual_requires_period_end(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR3")
    admin = ah._seed_admin(db_session, email="admin-c3@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")
    bad = _payload(parking_id=parking.id)
    bad["period_end"] = None
    r = client.post("/api/v1/admin/costs", headers=headers, json=bad)
    assert r.status_code == 422
    assert "period_end" in r.text


def test_create_cost_recurrente_rejects_period_end(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR4")
    admin = ah._seed_admin(db_session, email="admin-c4@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")
    bad = _payload(
        parking_id=parking.id,
        periodicity=CostPeriod.MENSUAL.value,
        period_end="2026-02-01T00:00:00+00:00",
    )
    r = client.post("/api/v1/admin/costs", headers=headers, json=bad)
    assert r.status_code == 422
    assert "recurrentes" in r.text.lower()


# ── GET /admin/costs (lista + filtros) ────────────────────────────────


def test_list_costs_with_filters(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR5")
    admin = ah._seed_admin(db_session, email="admin-c5@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    r1 = client.post(
        "/api/v1/admin/costs", headers=headers,
        json=_payload(
            parking_id=parking.id,
            category=CostCategory.MANTENIMIENTO.value,
            period_start="2026-03-01T00:00:00+00:00",
            period_end="2026-03-15T00:00:00+00:00",
        ),
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/api/v1/admin/costs", headers=headers,
        json=_payload(
            parking_id=parking.id,
            category=CostCategory.CAMARAS.value,
            period_start="2026-04-01T00:00:00+00:00",
            period_end="2026-04-30T00:00:00+00:00",
        ),
    )
    assert r2.status_code == 201

    r = client.get(
        "/api/v1/admin/costs", headers=headers,
        params={"parking_id": parking.id, "category": "camaras"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["category"] == "camaras"

    r = client.get(
        "/api/v1/admin/costs", headers=headers,
        params={
            "parking_id": parking.id,
            "from": "2026-03-15T00:00:00+00:00",
        },
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["period_start"].startswith("2026-04-01")


# ── PATCH /admin/costs/{id} ──────────────────────────────────────────


def test_update_cost_changes_amount(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR6")
    admin = ah._seed_admin(db_session, email="admin-c6@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")
    created = client.post(
        "/api/v1/admin/costs", headers=headers,
        json=_payload(parking_id=parking.id),
    ).json()

    r = client.patch(
        f"/api/v1/admin/costs/{created['id']}",
        headers=headers,
        json={"amount": 999.99},
    )
    assert r.status_code == 200
    assert r.json()["amount"] == 999.99
    ah.assert_audit_log(
        db_session, action="update_cost",
        resource=f"costs/{created['id']}", user_id=admin.id,
    )


# ── DELETE /admin/costs/{id} ──────────────────────────────────────────


def test_delete_cost_audit(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-CR7")
    admin = ah._seed_admin(db_session, email="admin-c7@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")
    created = client.post(
        "/api/v1/admin/costs", headers=headers,
        json=_payload(parking_id=parking.id),
    ).json()

    r = client.delete(
        f"/api/v1/admin/costs/{created['id']}",
        headers=headers,
    )
    assert r.status_code == 204
    assert db_session.get(Cost, created["id"]) is None
    ah.assert_audit_log(
        db_session, action="delete_cost",
        resource=f"costs/{created['id']}", user_id=admin.id,
    )