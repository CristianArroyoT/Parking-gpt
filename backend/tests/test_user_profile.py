"""Tests del endpoint de datos de perfil del usuario (T-19, 2026-10-21).

Cubre ``PATCH /api/v1/users/me/profile``:

  1. Actualización de nombre y teléfono → 200 y persistencia.
  2. Actualización parcial (sólo teléfono) → 200, el nombre no se toca.
  3. Teléfono a ``null`` (vaciarlo) → 200.
  4. Body vacío → 400 (no es un no-op silencioso).
  5. Sin token → 401.
  6. ``email`` y ``role`` **no** son editables (el esquema los ignora).
  7. Editar el perfil no toca el de otro usuario.
  8. Audit ``update_my_profile`` con ``result=success``.

El endpoint es user-scoped: cualquier usuario autenticado edita **su**
perfil, sin depender de rol (admin, gestor, operador o cliente).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    assert_audit_log,
)


def test_update_my_profile_success(
    client: TestClient, db_session: Session,
) -> None:
    """Nombre y teléfono → 200 y quedan persistidos."""
    cliente = _seed_cliente(db_session, email="perfil@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={"full_name": "Cliente Actualizado", "phone": "+34 600 999 999"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Cliente Actualizado"
    assert body["phone"] == "+34 600 999 999"

    db_session.expire_all()
    fresh = db_session.get(User, cliente.id)
    assert fresh is not None
    assert fresh.full_name == "Cliente Actualizado"
    assert fresh.phone == "+34 600 999 999"


def test_update_my_profile_partial(
    client: TestClient, db_session: Session,
) -> None:
    """Sólo se envía el teléfono → el nombre no cambia."""
    cliente = _seed_cliente(db_session, email="perfil-parcial@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={"phone": "+34 600 111 222"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone"] == "+34 600 111 222"
    assert body["full_name"] == "Cliente"


def test_update_my_profile_clear_phone(
    client: TestClient, db_session: Session,
) -> None:
    """``phone: null`` vacía el teléfono (el campo es opcional de verdad)."""
    cliente = _seed_cliente(db_session, email="perfil-vacio@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={"phone": None},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["phone"] is None

    db_session.expire_all()
    fresh = db_session.get(User, cliente.id)
    assert fresh is not None
    assert fresh.phone is None


def test_update_my_profile_empty_body(
    client: TestClient, db_session: Session,
) -> None:
    """Body sin campos → 400."""
    cliente = _seed_cliente(db_session, email="perfil-vacio-body@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "No hay datos para actualizar" in r.text


def test_update_my_profile_requires_auth(
    client: TestClient,
) -> None:
    """Sin Authorization → 401."""
    r = client.patch(
        "/api/v1/users/me/profile",
        json={"full_name": "Sin Sesion"},
    )
    assert r.status_code == 401


def test_update_my_profile_cannot_change_email_or_role(
    client: TestClient, db_session: Session,
) -> None:
    """El email y el rol NO son editables desde el perfil."""
    cliente = _seed_cliente(db_session, email="perfil-roles@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={
            "full_name": "Nombre Valido",
            "email": "otro@test.es",
            "role": "admin",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "perfil-roles@test.es"
    assert body["role"] == "cliente"


def test_update_my_profile_does_not_affect_other_user(
    client: TestClient, db_session: Session,
) -> None:
    """Editar el perfil propio no toca el del resto."""
    _seed_cliente(db_session, email="perfil-a@test.es")
    otro = _seed_cliente(db_session, email="perfil-b@test.es")
    headers = _login_headers(client, "perfil-a@test.es", "cliente1234")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={"full_name": "Solo Yo"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    fresh = db_session.get(User, otro.id)
    assert fresh is not None
    assert fresh.full_name == "Cliente"


def test_update_my_profile_audit(
    client: TestClient, db_session: Session,
) -> None:
    """El cambio deja audit ``update_my_profile`` con ``result=success``."""
    admin = _seed_admin(db_session, email="perfil-admin@test.es")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.patch(
        "/api/v1/users/me/profile",
        json={"full_name": "Admin Actualizado"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    row = assert_audit_log(
        db_session,
        action="update_my_profile",
        user_id=admin.id,
        result="success",
    )
    assert row.user_id == admin.id
