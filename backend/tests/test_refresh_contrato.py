"""Contrato de ``POST /auth/refresh``: el body que manda **el cliente**.

T-187 (2026-10-25): el frontend manda SÓLO ``{"refresh_token": ...}`` y el
endpoint exigía un ``TokenPair`` completo (``access_token`` + ``expires_in``
+ ``refresh_token``): el refresco respondía **422**, el cliente limpiaba la
sesión y el operador quedaba en el login a los **15 minutos** (el TTL del
access token), con el refresh token —válido 7 días— sin poder usarlo.

Estos tests usan **el body exacto que manda el cliente**, no el que le daba
la gana a los tests de antes (que reusaban el access viejo «simplemente
para satisfacer la validación de schema»). Ese comentario era la prueba de
que la puerta y el cliente discrepaban: cada uno con su propia verdad, y
sólo se comprobaba una.

MEDIDO (2026-10-25, navegador de verdad): ``GET /api/v1/parkings`` → 401 y
``POST /api/v1/auth/refresh`` → 422, con el evento ``solidapp:sesion-caducada``
y vuelta al login.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import _seed_admin

PASSWORD = "admin12345"


def _login(client: TestClient, email: str) -> dict:
    """Login y devuelve el par de tokens."""
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_el_refresh_acepta_solo_el_refresh_token(
    client: TestClient, db_session: Session,
) -> None:
    """El body que manda el frontend (sólo ``refresh_token``) → 200.

    Este es el test que faltaba: con el contrato viejo, este body daba 422
    y la sesión moría a los 15 minutos.
    """
    admin = _seed_admin(db_session)
    tokens = _login(client, admin.email)

    r = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r.status_code == 200, r.text

    renewed = r.json()
    assert renewed["access_token"], r.text
    assert renewed["refresh_token"], r.text

    # Y el access nuevo sirve de verdad: no basta con que el 200 sea bonito.
    r_me = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {renewed['access_token']}"},
    )
    assert r_me.status_code == 200, r_me.text
    assert r_me.json()["email"] == admin.email


def test_el_refresh_tambien_acepta_el_token_pair_completo(
    client: TestClient, db_session: Session,
) -> None:
    """El body antiguo (TokenPair completo) sigue funcionando: no se rompe
    ningún cliente que mandara el par entero."""
    admin = _seed_admin(db_session)
    tokens = _login(client, admin.email)

    r = client.post("/api/v1/auth/refresh", json=tokens)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"], r.text


def test_refresh_sin_token_da_401_y_no_422(
    client: TestClient, db_session: Session,
) -> None:
    """Sin refresh token → 401 («no hay credenciales»), no 422.

    422 significa «el cliente manda algo que no encaja», que es un error de
    contrato; 401 es «no renuevo». Un 422 aquítapaba el logout de verdad.
    """
    admin = _seed_admin(db_session)
    _login(client, admin.email)

    r = client.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 401, r.text
    assert "token" in r.text.lower(), r.text


def test_refresh_con_token_invalido_da_401(
    client: TestClient, db_session: Session,
) -> None:
    """Un refresh token que no es un token → 401 (no 500 ni 422)."""
    admin = _seed_admin(db_session)
    _login(client, admin.email)

    r = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "esto-no-es-un-jwt"},
    )
    assert r.status_code == 401, r.text
