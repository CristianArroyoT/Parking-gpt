"""Tests del router REST de alertas.

Casos cubiertos:
  1. ``GET /api/v1/parkings/{id}/alerts`` devuelve la lista al admin.
  2. Filtros ``type`` y ``acknowledged`` reducen el resultado correctamente.
  3. ``POST .../alerts/{id}/acknowledge`` marca la alerta como reconocida.
  4. Cliente no tiene acceso (403) por falta de membresía.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType, UserRole
from app.models.parking import Parking
from app.models.user import ParkingMembership, User


def _seed(db) -> tuple[Parking, User, User, User, Alert]:
    admin = User(
        email="admin@test.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )
    gestor = User(
        email="gestor@test.es",
        full_name="Gestor",
        role=UserRole.GESTOR,
        hashed_password=hash_password("gestor12345"),
    )
    cliente = User(
        email="cliente@test.es",
        full_name="Cliente",
        role=UserRole.CLIENTE,
        hashed_password=hash_password("cliente12345"),
    )
    parking = Parking(code="P-T", name="Madrid Test", address="x", city="y")
    db.add_all([admin, gestor, cliente, parking])
    db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking.id))
    alert = Alert(
        parking_id=parking.id,
        type=AlertType.OCR_FAILED,
        severity=AlertSeverity.WARN,
        message="test",
        context={"camera_code": "CAM-01"},
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return parking, admin, gestor, cliente, alert


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_list_alerts_as_admin(client: TestClient, db_session) -> None:
    parking, admin, *_ = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get(f"/api/v1/parkings/{parking.id}/alerts", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["type"] == "ocr_failed"
    assert body[0]["severity"] == "warn"
    assert body[0]["acknowledged_at"] is None


def test_filter_alerts_by_type_and_acknowledged(client: TestClient, db_session) -> None:
    parking, admin, *_ = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get(
        f"/api/v1/parkings/{parking.id}/alerts",
        params={"type": "ocr_failed", "acknowledged": "false"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    r = client.get(
        f"/api/v1/parkings/{parking.id}/alerts",
        params={"type": "camera_offline"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_acknowledge_alert(client: TestClient, db_session) -> None:
    parking, _admin, gestor, _cliente, alert = _seed(db_session)
    token = _login(client, gestor.email, "gestor12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/api/v1/parkings/{parking.id}/alerts/{alert.id}/acknowledge",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acknowledged_at"] is not None
    assert body["acknowledged_by"] == gestor.id

    r2 = client.post(
        f"/api/v1/parkings/{parking.id}/alerts/{alert.id}/acknowledge",
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["acknowledged_at"] == body["acknowledged_at"]


def test_cliente_no_puede_listar(client: TestClient, db_session) -> None:
    parking, _admin, _gestor, cliente, _alert = _seed(db_session)
    token = _login(client, cliente.email, "cliente12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get(f"/api/v1/parkings/{parking.id}/alerts", headers=headers)
    assert r.status_code == 403, r.text