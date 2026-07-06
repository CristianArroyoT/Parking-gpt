"""Tests del hook ``_build_tokens → session_tracker`` (Sprint R2-followup).

El sprint R2 (PR #8) introdujo ``SessionTracker`` y ``POST /auth/logout/all``
como building block, pero el hook en ``_build_tokens`` (que añade los jtis
al set ``user:{id}:active_jtis`` en login/refresh) quedó fuera de scope.
Sin ese hook, ``revoke_all`` devolvía 0 en operación normal y el endpoint
estaba documentado como "follow-up".

Este sprint cierra el caveat añadiendo el hook. Cubre:

  1. ``/auth/login`` añade access + refresh al set del usuario.
  2. ``/auth/refresh`` añade los jtis NUEVOS al set (los viejos se
     quedan hasta ``exp`` — comportamiento correcto: ``revoke_all``
     los blacklisteaba igualmente).
  3. Fail-OPEN: si Redis cae durante ``track_session`` (probado
     parcheando ``_r`` con un fake que lanza ``RedisError`` en
     ``sadd``), login responde 200 igualmente.
  4. End-to-end: login → ``/auth/logout/all`` → ``revoked_count=2`` y
     ambos jtis quedan en blacklist.
"""
from __future__ import annotations

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.services.session_tracker import session_tracker
from tests._audit_helpers import (
    _login,
    _login_headers,
    _seed_admin,
)


def _active_jtis(user_id: int) -> set[str]:
    """Lee el set ``user:{id}:active_jtis`` directamente desde Redis."""
    return set(session_tracker._r().smembers(f"user:{user_id}:active_jtis"))


def test_login_tracks_both_jtis(client: TestClient, db_session: Session) -> None:
    """Login añade access + refresh al set del usuario."""
    admin = _seed_admin(db_session)
    access = _login(client, admin.email, "admin12345")
    user_id = admin.id

    jtis = _active_jtis(user_id)
    access_jti = decode_token(access)["jti"]
    assert access_jti in jtis, f"access jti {access_jti} no en set: {jtis}"
    assert len(jtis) == 2, f"esperaba 2 jtis (access+refresh), got {len(jtis)}"


def test_refresh_tracks_new_jtis(client: TestClient, db_session: Session) -> None:
    """Refresh añade los jtis nuevos al set (los viejos se quedan)."""
    admin = _seed_admin(db_session)
    user_id = admin.id

    # 1. Login → 2 jtis (access + refresh). El endpoint ``/auth/refresh``
    # toma un body ``TokenPair`` completo (re-usa el access viejo más el
    # refresh), rota tokens y devuelve un TokenPair nuevo. Reusamos el
    # access viejo simplemente para satisfacer la validación de schema
    # — el endpoint sólo lee ``payload.refresh_token``.
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "admin12345"},
    )
    pair = login_resp.json()
    first_access_jti = decode_token(pair["access_token"])["jti"]
    assert len(_active_jtis(user_id)) == 2

    # 2. Refresh → 2 jtis nuevos (access rotado + refresh rotado).
    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json=pair,
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    new_access_jti = decode_token(refresh_resp.json()["access_token"])["jti"]

    # 3. Set ahora tiene los 2 viejos (login) + 2 nuevos (refresh) = 4.
    # Los viejos se quedan hasta su exp natural — comportamiento correcto
    # porque ``revoke_all`` los blacklistea igualmente.
    jtis = _active_jtis(user_id)
    assert first_access_jti in jtis
    assert new_access_jti in jtis
    assert len(jtis) == 4, f"esperaba 4 jtis (2 viejos + 2 nuevos), got {len(jtis)}"


class _BrokenRedis:
    """Fake de Redis que lanza RedisError en SADD (simula Redis caído)."""

    def sadd(self, *_args, **_kwargs):  # noqa: ANN001
        raise redis.RedisError("simulated redis down")


def test_login_fail_open_when_redis_down(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si Redis cae durante track_session, login responde 200 igualmente.

    Parchea ``session_tracker._r`` con un fake que lanza ``RedisError``
    en ``sadd``. ``track_session`` captura el error internamente y
    devuelve False (fail-OPEN documentado en ``session_tracker.py``),
    así que login NO debe fallar.
    """
    admin = _seed_admin(db_session)
    monkeypatch.setattr(session_tracker, "_r", lambda: _BrokenRedis())

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "admin12345"},
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


def test_logout_all_now_invalidates_real_jtis(
    client: TestClient, db_session: Session,
) -> None:
    """End-to-end: login → /auth/logout/all → revoked_count=2 + blacklist real."""
    admin = _seed_admin(db_session)
    user_id = admin.id
    headers = _login_headers(client, admin.email, "admin12345")

    # Tras login hay 2 jtis trackeados.
    assert len(_active_jtis(user_id)) == 2

    # /auth/logout/all → 200 con revoked_count=2.
    resp = client.post("/api/v1/auth/logout/all", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "Sesiones cerradas: 2" in resp.json()["detail"]

    # Set del usuario ya NO existe (revoke_all hace DEL).
    assert len(_active_jtis(user_id)) == 0

    # Los jtis quedaron en blacklist — siguiente request con el access
    # token original debe devolver 401.
    follow_up = client.get("/api/v1/users/me", headers=headers)
    assert follow_up.status_code == 401