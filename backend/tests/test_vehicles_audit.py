"""Tests audit Fase 3B-parte-2 — vehicles (create_vehicle, update_vehicle, add_vehicle_user).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 3 handlers del router
``app/api/v1/vehicles.py`` decorados con ``@audited``. Acceso por rol:
admin / gestor / operador (``_STAFF``); cliente → 403.

Casos cubiertos:
  1. ``create_vehicle`` admin 201 → audit con action=create_vehicle.
  2. ``update_vehicle`` admin 200 → audit con resource=vehicles/{id}.
  3. ``add_vehicle_user`` admin 201 → audit con action=add_vehicle_user
     + resource=vehicles/{id}.
  4. ``create_vehicle`` cliente 403 → NO crea audit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    assert_audit_log,
    assert_no_audit_log,
)


def test_create_vehicle_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea vehículo → audit con action=create_vehicle, result=success."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.post(
        "/api/v1/vehicles",
        json={"plate": "1234ABC", "brand": "Renault", "color": "Azul"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    vehicle_id = response.json()["id"]

    row = assert_audit_log(
        db_session,
        action="create_vehicle",
        user_id=admin.id,
        result="success",
    )
    assert row.resource is None


def test_update_vehicle_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin modifica vehículo → audit con resource=vehicles/{id}."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        "/api/v1/vehicles",
        json={"plate": "5678DEF", "color": "Rojo"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    vehicle_id = r.json()["id"]

    response = client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"color": "Negro", "brand": "Seat"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_vehicle",
        resource=f"vehicles/{vehicle_id}",
        user_id=admin.id,
        result="success",
    )


def test_add_vehicle_user_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin asocia vehículo a usuario → audit con resource=vehicles/{id}."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        "/api/v1/vehicles",
        json={"plate": "9012GHI"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    vehicle_id = r.json()["id"]

    u = client.post(
        "/api/v1/users",
        json={
            "email": "owner-veh@test.es",
            "full_name": "Propietario Test",
            "role": "cliente",
            "password": "secret1234",
        },
        headers=headers,
    )
    assert u.status_code == 201, u.text
    user_id = u.json()["id"]

    response = client.post(
        f"/api/v1/vehicles/{vehicle_id}/users",
        json={"user_id": user_id, "role": "propietario"},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    assert_audit_log(
        db_session,
        action="add_vehicle_user",
        resource=f"vehicles/{vehicle_id}",
        user_id=admin.id,
        result="success",
    )


def test_create_vehicle_cliente_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Cliente intenta crear vehículo → 403, NO crea audit."""
    cliente = _seed_cliente(db_session, email="cli-veh@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    response = client.post(
        "/api/v1/vehicles",
        json={"plate": "0000XXX"},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_vehicle")