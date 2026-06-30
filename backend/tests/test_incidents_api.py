"""Tests del endpoint de incidentes (POST /api/v1/parkings/{id}/incidents).

Estrategia: TestClient + SQLite en memoria + StaticPool, mismo patrón
que ``test_ticket_manual.py`` y ``test_alert_api.py``.

Casos cubiertos:
  1. space_broken OK: marca is_broken=True + crea Alert.
  2. space_unbroken OK: limpia is_broken + crea Alert.
  3. space_unbroken idempotente: plaza ya rehabilitada → 201 sin Alert nuevo.
  4. robery_reported sin matrícula: 201, severity=CRITICAL, email dry-run.
  5. robery_reported con matrícula: normalizada (uppercase, sin separadores).
  6. robery_reported con 4 fotos → 422.
  7. Cliente → 403.
  8. Plaza de otra sucursal → 422.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.audit import Alert, AuditLog
from app.models.enums import UserRole
from app.models.parking import Parking, ParkingSpace
from app.models.user import ParkingMembership, User
from app.services import email as email_mod


def _seed(db) -> tuple[Parking, ParkingSpace, User, User, User]:
    admin = User(
        email="admin@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    operador = User(
        email="operador@test.es", full_name="Operador",
        role=UserRole.OPERADOR, hashed_password=hash_password("oper12345"),
    )
    cliente = User(
        email="cliente@test.es", full_name="Cliente",
        role=UserRole.CLIENTE, hashed_password=hash_password("cli12345"),
    )
    parking_a = Parking(code="P-A", name="A", address="x", city="y")
    parking_b = Parking(code="P-B", name="B", address="x", city="y")
    db.add_all([admin, operador, cliente, parking_a, parking_b])
    db.flush()
    db.add(ParkingMembership(user_id=operador.id, parking_id=parking_a.id))
    space_a = ParkingSpace(parking_id=parking_a.id, lane="A", number="A-01")
    space_b = ParkingSpace(parking_id=parking_b.id, lane="B", number="B-01")
    db.add_all([space_a, space_b])
    db.commit()
    db.refresh(parking_a); db.refresh(space_a)
    return parking_a, space_a, admin, operador, cliente


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_space_broken_ok(client: TestClient, db_session, monkeypatch) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    sent: list[dict] = []
    monkeypatch.setattr(email_mod, "send_alert_email", lambda *a, **k: sent.append({}) or True)

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "space_broken",
            "parking_space_id": space.id,
            "reason": "physical_damage",
            "notes": "hueco en el suelo",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "space_broken"
    assert body["severity"] == "warn"
    assert body["context"]["kind"] == "space_broken"

    db_session.expire_all()
    db_session.commit()
    space_fresh = db_session.get(ParkingSpace, space.id)
    assert space_fresh.is_broken is True
    assert space_fresh.is_broken_at is not None
    assert sent == []


def test_space_unbroken_ok(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    space.is_broken = True
    db_session.commit()

    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "space_unbroken",
            "parking_space_id": space.id,
            "reason": "other",
            "notes": "reparada",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "space_broken"
    assert body["context"]["kind"] == "space_unbroken"

    db_session.expire_all()
    space_fresh = db_session.get(ParkingSpace, space.id)
    assert space_fresh.is_broken is False
    assert space_fresh.is_broken_at is None


def test_space_unbroken_idempotent(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    initial_alerts = db_session.query(Alert).count()

    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "space_unbroken",
            "parking_space_id": space.id,
            "reason": "other",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("noop") is True

    assert db_session.query(Alert).count() == initial_alerts

    noop = db_session.query(AuditLog).filter(
        AuditLog.action == "incident_space_unbroken_noop"
    ).first()
    assert noop is not None


def test_robery_reported_without_plate(client: TestClient, db_session, monkeypatch) -> None:
    parking, _space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    sent: list[dict] = []
    monkeypatch.setattr(email_mod, "send_alert_email", lambda *a, **k: sent.append({"args": a, "kwargs": k}) or True)

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "robery_reported",
            "reason": "theft_attempt",
            "notes": "ventana rota",
            "photos": ["f1.jpg", "f2.jpg"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "robery_reported"
    assert body["severity"] == "critical"
    assert body["context"]["plate"] is None
    assert body["context"]["photos"] == ["f1.jpg", "f2.jpg"]

    assert len(sent) == 1
    assert sent[0]["kwargs"]["template_kind"] == "robery_reported"


def test_robery_reported_normalizes_plate(client: TestClient, db_session) -> None:
    parking, _space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "robery_reported",
            "reason": "suspicious_behavior",
            "plate": "1234-abc",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["context"]["plate"] == "1234ABC"


def test_robery_reported_too_many_photos(client: TestClient, db_session) -> None:
    parking, _space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={
            "kind": "robery_reported",
            "reason": "other",
            "photos": ["f1.jpg", "f2.jpg", "f3.jpg", "f4.jpg"],
        },
    )
    assert r.status_code == 422


def test_incident_cliente_403(client: TestClient, db_session) -> None:
    parking, _space, _admin, _operador, cliente = _seed(db_session)
    token = _login(client, cliente.email, "cli12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}",
        headers=headers,
        json={"kind": "robery_reported", "reason": "other"},
    )
    assert r.status_code == 403


def test_incident_cross_parking_422(client: TestClient, db_session) -> None:
    parking_a, _space_a, admin, _operador, _cliente = _seed(db_session)
    parking_b = db_session.query(Parking).filter(Parking.code == "P-B").one()
    space_b = db_session.query(ParkingSpace).filter(
        ParkingSpace.parking_id == parking_b.id
    ).one()

    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/incidents/parkings/{parking_a.id}",
        headers=headers,
        json={
            "kind": "space_broken",
            "parking_space_id": space_b.id,
            "reason": "other",
        },
    )
    assert r.status_code == 422