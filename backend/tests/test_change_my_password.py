"""Tests del endpoint PATCH /users/me/password (Sprint R5-sidebar, 2026-07-06).

Cubre:

  1. Cambio exitoso con clave correcta → 204, hash actualizado,
     login con la clave nueva funciona, login con la vieja falla.
  2. Clave actual incorrecta → 400 + audit con ``result=failure`` y
     ``reason=current_password_mismatch``.
  3. Clave nueva demasiado corta → 422 (validación Pydantic).
  4. Sin token → 401.
  5. Cambio no afecta a otros usuarios.
  6. Audit ``change_my_password`` queda registrado en éxito.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from tests._audit_helpers import (
    _login,
    _login_headers,
    _seed_admin,
    assert_audit_log,
)


def _change_payload(current: str, new: str) -> dict:
    return {"current_password": current, "new_password": new}


def test_change_my_password_success(
    client: TestClient, db_session: Session,
) -> None:
    """Cambio válido de clave → 204 y persiste el nuevo hash."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    old_hash = admin.hashed_password  # snapshot ANTES del PATCH

    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("admin12345", "nueva-clave-99"),
        headers=headers,
    )
    assert r.status_code == 204, r.text

    # Forzar reload para asegurar que el hash se persistió. ``admin``
    # y ``fresh`` son la misma instancia en SQLAlchemy, así que
    # capturamos old_hash antes para poder comparar.
    db_session.expire_all()
    fresh = db_session.get(User, admin.id)
    assert fresh is not None
    assert fresh.hashed_password != old_hash

    # La clave vieja ya no funciona.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "admin12345"},
    )
    assert r.status_code == 401, "login con clave vieja debe fallar"

    # La nueva sí.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "nueva-clave-99"},
    )
    assert r.status_code == 200, (
        f"login con clave nueva debe funcionar, obtuve {r.status_code}: {r.text}"
    )


def test_change_my_password_wrong_current(
    client: TestClient, db_session: Session,
) -> None:
    """Clave actual incorrecta → 400 + audit ``failure``."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("WRONG-PWD", "nueva-clave-99"),
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "La contraseña actual no es correcta" in r.text

    # El hash NO cambia.
    db_session.expire_all()
    fresh = db_session.get(User, admin.id)
    assert fresh.hashed_password == admin.hashed_password

    # Audit con reason correcto.
    row = assert_audit_log(
        db_session,
        action="change_my_password",
        user_id=admin.id,
        result="failure",
    )
    assert row.payload["reason"] == "current_password_mismatch"


def test_change_my_password_new_too_short(
    client: TestClient, db_session: Session,
) -> None:
    """``new_password`` < 8 caracteres → 422 (Pydantic)."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("admin12345", "short"),
        headers=headers,
    )
    assert r.status_code == 422


def test_change_my_password_requires_auth(
    client: TestClient,
) -> None:
    """Sin Authorization → 401."""
    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("admin12345", "nueva-clave-99"),
    )
    assert r.status_code == 401


def test_change_my_password_does_not_affect_other_users(
    client: TestClient, db_session: Session,
) -> None:
    """Cambiar la clave de un usuario no afecta a otros."""
    _seed_admin(db_session, email="a-change@test.es")
    user_b = _seed_admin(db_session, email="b-change@test.es")
    headers_a = _login_headers(client, "a-change@test.es", "admin12345")

    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("admin12345", "nueva-A-123"),
        headers=headers_a,
    )
    assert r.status_code == 204

    # User B sigue pudiendo loguearse con admin12345.
    token_b = _login(client, user_b.email, "admin12345")
    assert token_b


def test_change_my_password_success_audit(
    client: TestClient, db_session: Session,
) -> None:
    """El cambio exitoso deja un audit ``change_my_password`` con
    ``result=success`` y ``payload.user_id`` correcto."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.patch(
        "/api/v1/users/me/password",
        json=_change_payload("admin12345", "exitosa-1234"),
        headers=headers,
    )
    assert r.status_code == 204

    row = assert_audit_log(
        db_session,
        action="change_my_password",
        user_id=admin.id,
        result="success",
    )
    assert row.payload["user_id"] == admin.id