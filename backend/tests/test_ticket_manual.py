"""Tests del alta manual de tickets (POST /api/v1/tickets/manual).

Estrategia: TestClient + SQLite en memoria + StaticPool, mismo patrón
que ``test_ticket_close.py``.

Casos cubiertos:
  1. ENTRADA manual con matrícula nueva → 201.
  2. ENTRADA sobre plaza ya ocupada → 409.
  3. Doble ENTRADA del mismo vehículo → 409.
  4. SALIDA manual con ticket activo → 200 + ticket CERRADO + origin=manual_exit.
  5. SALIDA manual sin ticket activo → 409.
  6. Cliente → 403.
  7. Matrícula vacía tras normalizar → 422.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.parking import Parking, ParkingSpace
from app.models.pricing import Tariff
from app.models.ticket import Ticket
from app.models.user import ParkingMembership, User


def _seed(db) -> tuple[Parking, ParkingSpace, User, User, User]:
    admin = User(
        email="admin@test.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )
    operador = User(
        email="operador@test.es",
        full_name="Operador",
        role=UserRole.OPERADOR,
        hashed_password=hash_password("oper12345"),
    )
    cliente = User(
        email="cliente@test.es",
        full_name="Cliente",
        role=UserRole.CLIENTE,
        hashed_password=hash_password("cli12345"),
    )
    parking = Parking(code="P-M", name="Madrid Manual", address="x", city="y")
    db.add_all([admin, operador, cliente, parking])
    db.flush()
    db.add(ParkingMembership(user_id=operador.id, parking_id=parking.id))
    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    db.add(space)
    db.add(Tariff(
        parking_id=parking.id,
        name="Estándar",
        price_per_hour=2.0,
        price_per_fraction=0.5,
        fraction_minutes=15,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    db.commit()
    db.refresh(parking)
    db.refresh(space)
    return parking, space, admin, operador, cliente


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_manual_entry_success(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "6421-ABC",
            "direction": "entry",
            "parking_id": parking.id,
            "parking_space_id": space.id,
            "reason": "camera_down",
            "notes": "CAM-07 sin respuesta",
            "camera_id": 7,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["origin"] == "manual_entry"
    assert body["status"] == "activo"
    assert body["parking_space_id"] == space.id

    # Verificar AuditLog. La sesión de test y la de servicio comparten
    # motor SQLite (StaticPool) pero no transacción; refresh + commit
    # explícito asegura visibilidad.
    db_session.expire_all()
    db_session.commit()
    audit = db_session.query(AuditLog).filter(
        AuditLog.resource == f"ticket:{body['id']}"
    ).one()
    assert audit.action == "entry_manual"
    assert audit.user_id == admin.id
    assert audit.payload["plate"] == "6421ABC"
    assert audit.payload["reason"] == "camera_down"


def test_manual_entry_space_occupied_409(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "1111AAA",
            "direction": "entry",
            "parking_id": parking.id,
            "parking_space_id": space.id,
            "reason": "ocr_failed",
        },
    )
    assert r1.status_code == 201, r1.text

    r2 = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "2222BBB",
            "direction": "entry",
            "parking_id": parking.id,
            "parking_space_id": space.id,
            "reason": "other",
        },
    )
    assert r2.status_code == 409, r2.text
    assert "ocupada" in r2.json()["detail"].lower()


def test_manual_entry_duplicate_vehicle_409(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "plate": "3333CCC",
        "direction": "entry",
        "parking_id": parking.id,
        "parking_space_id": space.id,
        "reason": "camera_down",
    }
    r1 = client.post("/api/v1/tickets/manual", headers=headers, json=payload)
    assert r1.status_code == 201, r1.text

    payload["parking_space_id"] = None
    r2 = client.post("/api/v1/tickets/manual", headers=headers, json=payload)
    assert r2.status_code == 409, r2.text
    assert "ya tiene" in r2.json()["detail"].lower()


def test_manual_exit_success(client: TestClient, db_session) -> None:
    parking, space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "4444DDD",
            "direction": "entry",
            "parking_id": parking.id,
            "parking_space_id": space.id,
            "reason": "ocr_failed",
        },
    )
    assert r1.status_code == 201, r1.text
    ticket_id = r1.json()["id"]

    entry = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.expire_all()
    t = db_session.get(Ticket, ticket_id)
    t.entry_at = entry
    db_session.commit()

    occurred_exit = entry + timedelta(hours=1, minutes=15)
    r2 = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "4444DDD",
            "direction": "exit",
            "parking_id": parking.id,
            "reason": "camera_down",
            "occurred_at": occurred_exit.isoformat(),
        },
    )
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["origin"] == "manual_exit"
    assert body["status"] == "cerrado"
    assert body["exit_at"] is not None
    assert body["total"] is not None


def test_manual_exit_no_active_ticket_409(client: TestClient, db_session) -> None:
    parking, _space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "5555EEE",
            "direction": "exit",
            "parking_id": parking.id,
            "reason": "other",
        },
    )
    assert r.status_code == 409, r.text
    assert "no tiene" in r.json()["detail"].lower()


def test_manual_cliente_403(client: TestClient, db_session) -> None:
    parking, _space, _admin, _operador, cliente = _seed(db_session)
    token = _login(client, cliente.email, "cli12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "6666FFF",
            "direction": "entry",
            "parking_id": parking.id,
            "reason": "other",
        },
    )
    assert r.status_code == 403, r.text


def test_manual_empty_plate_422(client: TestClient, db_session) -> None:
    parking, _space, admin, _operador, _cliente = _seed(db_session)
    token = _login(client, admin.email, "admin12345")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/tickets/manual",
        headers=headers,
        json={
            "plate": "----",
            "direction": "entry",
            "parking_id": parking.id,
            "reason": "other",
        },
    )
    assert r.status_code == 422, r.text