"""Tests del token blacklist (Sprint Fase 3D, 2026-07-01).

Cubre:

  - ``POST /auth/logout`` blacklistea el ``jti`` del token actual.
  - Re-request con el mismo token tras logout → 401
    ``WWW-Authenticate: Bearer error="invalid_token"``.
  - Audit ``logout_success`` con ``payload.jti_blacklisted=true``.
  - Backwards-compat: tokens legacy sin ``jti`` → logout responde 200 con
    ``payload.jti_blacklisted=false`` (degradación graceful).
  - TTL del blacklist = ``(exp - now) + grace_seconds``.
  - Blacklist de un usuario NO afecta a tokens de otros usuarios.
  - Fail-CLOSED: si Redis cae durante el check en el middleware → 401
    ``Servicio de autenticación no disponible``.

Usa el helper ``_logout`` de ``tests._audit_helpers`` (Sprint 3D) y
parchea ``token_blacklist.is_blocked`` cuando se quiere simular
caída de Redis (vía ``monkeypatch`` o ``unittest.mock``).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.services.token_blacklist import token_blacklist
from tests._audit_helpers import (
    _login_headers,
    _logout,
    _seed_admin,
    assert_audit_log,
)


# ── helpers ────────────────────────────────────────────────────────────

def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def _clean_jwt_blacklist() -> None:
    """Borra ``jwt:blacklist:*`` por si quedó algún residuo entre tests."""
    try:
        for key in _redis().scan_iter("jwt:blacklist:*"):
            _redis().delete(key)
    except Exception:
        pass


# ── tests ──────────────────────────────────────────────────────────────

def test_logout_blacklists_token(
    client: TestClient, db_session: Session,
) -> None:
    """Logout real: añade el ``jti`` a Redis y un re-request con el mismo
    Authorization devuelve 401 ``WWW-Authenticate: Bearer error="invalid_token"``.
    """
    _clean_jwt_blacklist()
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    token = headers["Authorization"].split(None, 1)[1].strip()
    payload = decode_token(token)
    jti = payload["jti"]

    # 1. Logout.
    assert _logout(client, headers) == 200

    # 2. El jti debe estar en Redis con TTL > 0.
    rcli = _redis()
    key = f"{get_settings().jwt_blacklist_key_prefix}{jti}"
    assert rcli.exists(key) == 1, f"esperaba {key} en blacklist"
    assert rcli.ttl(key) > 0

    # 3. Re-request con el mismo token → 401.
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401, response.text
    assert response.headers.get("WWW-Authenticate", "").startswith("Bearer error=")


def test_logout_audit_includes_blacklist(
    client: TestClient, db_session: Session,
) -> None:
    """El audit ``logout_success`` lleva ``payload.jti_blacklisted=true``."""
    _clean_jwt_blacklist()
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    assert _logout(client, headers) == 200

    row = assert_audit_log(
        db_session, action="logout_success", user_id=admin.id, result="success",
    )
    assert row.payload is not None
    assert row.payload["jti_blacklisted"] is True


def test_blacklist_blocks_subsequent_requests(
    client: TestClient, db_session: Session,
) -> None:
    """Tras blacklistear el jti, CUALQUIER endpoint autenticado devuelve 401.

    Verificamos con dos endpoints distintos (``/users/me`` y un GET a
    ``/users``) que el middleware aborta antes del handler.
    """
    _clean_jwt_blacklist()
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    token_blacklist.add(jti=decode_token(
        headers["Authorization"].split(None, 1)[1].strip()
    )["jti"], exp_epoch=int(time.time()) + 60)

    r1 = client.get("/api/v1/users/me", headers=headers)
    assert r1.status_code == 401
    r2 = client.get("/api/v1/users", headers=headers)
    assert r2.status_code == 401


def test_blacklist_fails_closed_on_redis_error(
    client: TestClient, db_session: Session,
) -> None:
    """Si Redis cae durante ``is_blocked``, el middleware aborta con 401
    ``Servicio de autenticación no disponible`` (fail-CLOSED).

    NO se propaga la ``RedisError`` al handler: el middleware corta
    antes de pasar al router.
    """
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    with patch(
        "app.core.middleware.token_blacklist.is_blocked",
        side_effect=redis.RedisError("simulated outage"),
    ):
        r = client.get("/api/v1/users/me", headers=headers)
    assert r.status_code == 401, r.text
    assert "Servicio de autenticación no disponible" in r.text


def test_blacklist_ttl_uses_jwt_exp(
    client: TestClient, db_session: Session,
) -> None:
    """El TTL aplicado es ``(exp_epoch - now) + grace`` (con grace=60s)."""
    _clean_jwt_blacklist()
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    token = headers["Authorization"].split(None, 1)[1].strip()
    payload = decode_token(token)
    jti = payload["jti"]
    exp_epoch = int(payload["exp"])

    ttl = token_blacklist.add(jti=jti, exp_epoch=exp_epoch)
    expected_ttl = max(int(exp_epoch - time.time()) + get_settings().jwt_blacklist_ttl_grace_seconds, 1)

    # El TTL aplicado debe estar en +-2s del teórico (por timing del test).
    assert abs(ttl - expected_ttl) <= 2, (
        f"esperaba TTL ~{expected_ttl}, obtuve {ttl}"
    )

    # Y redis.ttl(key) debe coincidir aproximadamente.
    key = f"{get_settings().jwt_blacklist_key_prefix}{jti}"
    actual_ttl = _redis().ttl(key)
    assert abs(actual_ttl - expected_ttl) <= 2, (
        f"redis.ttl({key})={actual_ttl}, esperaba ~{expected_ttl}"
    )


def test_blacklist_does_not_affect_other_users(
    client: TestClient, db_session: Session,
) -> None:
    """El blacklist del jti de un usuario NO afecta a los tokens de otros."""
    _clean_jwt_blacklist()
    admin_a = _seed_admin(db_session, email="admin-a@test.es")
    admin_b = _seed_admin(db_session, email="admin-b@test.es")

    # Ambos se autentican.
    headers_a = _login_headers(client, admin_a.email, "admin12345")
    headers_b = _login_headers(client, admin_b.email, "admin12345")
    jti_a = decode_token(headers_a["Authorization"].split(None, 1)[1].strip())["jti"]

    # Logout de A → blacklistea su jti.
    assert _logout(client, headers_a) == 200

    # Re-request de A → 401.
    r_a = client.get("/api/v1/users/me", headers=headers_a)
    assert r_a.status_code == 401

    # Request de B con su token (NO blacklisteado) → 200.
    r_b = client.get("/api/v1/users/me", headers=headers_b)
    assert r_b.status_code == 200, r_b.text
    assert r_b.json()["email"] == admin_b.email

    # Sanity: el jti de A sigue en blacklist, el de B NO.
    rcli = _redis()
    assert rcli.exists(f"{get_settings().jwt_blacklist_key_prefix}{jti_a}") == 1


def test_logout_legacy_token_without_jti(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token legacy sin ``jti`` → logout responde 200 con
    ``jti_blacklisted=false`` (degradación graceful). El sistema sigue
    funcionando, pero ese token concreto NO queda invalidado en Redis.

    Parchea ``AuditMiddleware`` para simular el payload sin ``jti``
    justo ANTES de persistir en ``request.state.audit``.
    """
    _clean_jwt_blacklist()
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    import app.core.middleware as mw_mod

    original_decode = mw_mod.decode_token

    def fake_decode(token: str):
        payload = original_decode(token)
        payload.pop("jti", None)
        return payload

    monkeypatch.setattr(mw_mod, "decode_token", fake_decode)

    # El handler de logout recibe audit sin jti → 200 con
    # jti_blacklisted=false.
    r = client.post("/api/v1/auth/logout", headers=headers)
    assert r.status_code == 200, r.text

    row = assert_audit_log(
        db_session, action="logout_success", user_id=admin.id, result="success",
    )
    assert row.payload is not None
    assert row.payload["jti_blacklisted"] is False