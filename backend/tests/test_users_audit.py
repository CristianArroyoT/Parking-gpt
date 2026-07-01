"""Tests audit Fase 3B-parte-2 — users (create_user, update_user, delete_user, create_membership).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 4 handlers del router
``app/api/v1/users.py`` decorados con ``@audited``. Todos son
admin-only.

Casos cubiertos:
  1. ``create_user`` admin 201 → audit con action=create_user.
  2. ``update_user`` admin 200 → audit con action=update_user +
     resource="users/{id}".
  3. ``delete_user`` admin 204 → audit con action=delete_user +
     resource="users/{id}".
  4. ``create_membership`` admin 201 → audit con action=create_membership
     + resource="users/{user_id}".
  5. ``create_user`` gestor 403 → NO crea audit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_gestor,
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
)


def test_create_user_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea usuario → audit con action=create_user, result=success."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.post(
        "/api/v1/users",
        json={
            "email": "newclient@test.es",
            "full_name": "Cliente Nuevo",
            "phone": "600000000",
            "role": "cliente",
            "password": "secret1234",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    new_user_id = response.json()["id"]

    row = assert_audit_log(
        db_session,
        action="create_user",
        user_id=admin.id,
        result="success",
    )
    assert row.resource is None  # create_user no tiene resource_arg.
    # Verificar que el password NUNCA aparece en el payload.
    payload_str = str(row.payload or {})
    assert "secret1234" not in payload_str


def test_update_user_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin modifica usuario → audit con resource=users/{id}."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    # Crear primero un usuario para tener su id.
    r = client.post(
        "/api/v1/users",
        json={
            "email": "updateme@test.es",
            "full_name": "Por Actualizar",
            "role": "cliente",
            "password": "secret1234",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    # Y ahora modificarlo.
    response = client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "Nombre Actualizado"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_user",
        resource=f"users/{user_id}",
        user_id=admin.id,
        result="success",
    )


def test_delete_user_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin borra usuario → audit con action=delete_user + resource."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        "/api/v1/users",
        json={
            "email": "deleteme@test.es",
            "full_name": "Por Borrar",
            "role": "cliente",
            "password": "secret1234",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    response = client.delete(
        f"/api/v1/users/{user_id}",
        headers=headers,
    )
    assert response.status_code == 204, response.text

    assert_audit_log(
        db_session,
        action="delete_user",
        resource=f"users/{user_id}",
        user_id=admin.id,
        result="success",
    )


def test_create_membership_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea membresía → audit con action=create_membership + resource."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-MEM")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        "/api/v1/users",
        json={
            "email": "gestor-mem@test.es",
            "full_name": "Gestor Membresía",
            "role": "gestor",
            "password": "gestor1234",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    response = client.post(
        f"/api/v1/users/{user_id}/memberships",
        json={"parking_id": parking.id, "role_in_parking": "gestor"},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    assert_audit_log(
        db_session,
        action="create_membership",
        resource=f"users/{user_id}",
        user_id=admin.id,
        result="success",
    )


def test_create_user_gestor_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Gestor intenta crear usuario → 403, NO crea audit (decorator post-dep)."""
    gestor = _seed_gestor(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")

    response = client.post(
        "/api/v1/users",
        json={
            "email": "no-pass@test.es",
            "full_name": "Sin Permiso",
            "role": "cliente",
            "password": "secret1234",
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_user")