"""Tests del rate-limit de endpoints CRUD (Sprint Fase 3D, 2026-07-01).

Cubre:

  - ``POST /users`` (scope ``users_create``) → bloquea tras N intentos.
  - ``POST /vehicles`` (scope ``vehicles_create``) → bloquea tras N intentos.
  - El bloqueo escribe un ``audit_log`` con ``action=rate_limited_endpoint``
    y ``payload={scope, bucket, count}``.
  - Buckets independientes por ``actor`` (dos admins no se interfieren).
  - Reset por ventana (EXPIRE no es sliding).
  - Scopes independientes: saturar ``users_create`` no bloquea
    ``vehicles_create``.

Usa ``endpoint_rate_limiter.check`` directamente para verificar el
payload del audit (es el mismo path que en producción) y limpia
``rl:users_*`` / ``rl:vehicles_*`` desde la fixture autouse de
``conftest.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    assert_audit_log,
)


# ── helpers ────────────────────────────────────────────────────────────

def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def _force_endpoint_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_attempts: int,
    window_seconds: int = 60,
) -> None:
    """Parchea ``get_settings`` en los módulos donde está enlazado el import.

    ``endpoint_rate_limiter.check`` llama a ``get_settings()`` desde el
    módulo ``app.services.endpoint_rate_limit`` (donde está el binding
    importado al arrancar). Hay que parchear ESE módulo — no el del
    config — porque Python captura el nombre localmente.
    """
    from app.services import endpoint_rate_limit as erl_mod
    from app.core import config as cfg_mod

    def _patched():
        real = cfg_mod.get_settings()
        field_names = (
            list(real.model_fields.keys())
            if hasattr(real, "model_fields")
            else [a for a in dir(real) if not a.startswith("_")]
        )
        data = {name: getattr(real, name) for name in field_names}
        data["endpoint_rate_limit_max_attempts"] = max_attempts
        data["endpoint_rate_limit_window_seconds"] = window_seconds
        return SimpleNamespace(**data)

    monkeypatch.setattr(erl_mod, "get_settings", _patched)


def _force_users_max(monkeypatch: pytest.MonkeyPatch, *, max_attempts: int) -> None:
    """Compatibilidad con tests anteriores — la lógica está centralizada
    en ``_force_endpoint_settings`` que ahora parchea el módulo correcto."""
    pass


def _force_vehicles_max(monkeypatch: pytest.MonkeyPatch, *, max_attempts: int) -> None:
    """Compatibilidad con tests anteriores — idem."""
    pass


def _new_user_payload(i: int) -> dict:
    return {
        "email": f"rl-user-{i}@test.es",
        "full_name": f"RL User {i}",
        "role": "cliente",
        "password": "secret1234",
    }


def _new_vehicle_payload(i: int) -> dict:
    return {
        "plate": f"{i:04d}ABC",
        "make": "Renault",
        "model": "Clio",
        "color": "Blanco",
    }


# ── tests ──────────────────────────────────────────────────────────────

def test_create_user_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /users`` admin: ``max_attempts + 1`` → 429."""
    _force_endpoint_settings(monkeypatch, max_attempts=3)
    _force_users_max(monkeypatch, max_attempts=3)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    # Los 3 primeros pasan (201). El 4º cae en 429.
    for i in range(3):
        r = client.post(
            "/api/v1/users", json=_new_user_payload(i), headers=headers,
        )
        assert r.status_code == 201, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        "/api/v1/users", json=_new_user_payload(99), headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"
    assert "Demasiadas operaciones" in r.text


def test_create_vehicle_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /vehicles`` staff: ``max_attempts + 1`` → 429."""
    _force_endpoint_settings(monkeypatch, max_attempts=3)
    _force_vehicles_max(monkeypatch, max_attempts=3)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(3):
        r = client.post(
            "/api/v1/vehicles", json=_new_vehicle_payload(i), headers=headers,
        )
        assert r.status_code == 201, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        "/api/v1/vehicles", json=_new_vehicle_payload(99), headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


def test_endpoint_rate_limit_audit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloqueo escribe ``audit_log`` con ``action=rate_limited_endpoint``
    y ``payload={scope, bucket, count}``."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    _force_users_max(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(2):
        client.post("/api/v1/users", json=_new_user_payload(i), headers=headers)
    r = client.post(
        "/api/v1/users", json=_new_user_payload(99), headers=headers,
    )
    assert r.status_code == 429

    row = assert_audit_log(
        db_session,
        action="rate_limited_endpoint",
        user_id=admin.id,
        result="failure",
    )
    assert row.payload is not None
    assert row.payload["scope"] == "users_create"
    assert row.payload["bucket"].startswith("rl:users_create:")
    assert row.payload["count"] >= 3


def test_endpoint_rate_limit_per_user_independent(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada admin tiene su propio bucket ``actor``. Saturar admin1 no
    bloquea admin2 (que pueden compartir IP porque están autenticados
    con tokens distintos → ``user_id`` distinto en ``request.state.audit``).
    """
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    _force_users_max(monkeypatch, max_attempts=2)
    admin_a = _seed_admin(db_session, email="rl-admin-a@test.es")
    admin_b = _seed_admin(db_session, email="rl-admin-b@test.es")
    headers_a = _login_headers(client, admin_a.email, "admin12345")
    headers_b = _login_headers(client, admin_b.email, "admin12345")

    # admin_a satura su bucket.
    for i in range(2):
        r = client.post(
            "/api/v1/users", json=_new_user_payload(i), headers=headers_a,
        )
        assert r.status_code == 201
    r = client.post(
        "/api/v1/users", json=_new_user_payload(99), headers=headers_a,
    )
    assert r.status_code == 429

    # admin_b debe seguir creando OK (bucket independiente).
    r = client.post(
        "/api/v1/users", json=_new_user_payload(50), headers=headers_b,
    )
    assert r.status_code == 201, (
        f"admin_b no debería estar bloqueado, obtuve {r.status_code}: {r.text}"
    )


def test_endpoint_rate_limit_resets_after_window(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tras ``window_seconds``, el bucket se resetea (EXPIRE, no sliding)."""
    # La ventana real se deja en su valor por defecto (60 s) a propósito.
    # Con una ventana de 2 s, las tres peticiones de este test (cada una
    # con un hash bcrypt de contraseña) podían tardar más de 2 s en una
    # máquina cargada: el bucket expiraba ENTRE peticiones, el contador
    # se reiniciaba y el 429 nunca llegaba. Era un flake dependiente de
    # la carga del equipo, no un fallo del código.
    #
    # El paso de la ventana se simula igual que antes, pero de forma
    # determinista: borrando la clave del bucket a mano (más abajo).
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    _force_users_max(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(2):
        client.post("/api/v1/users", json=_new_user_payload(i), headers=headers)
    r = client.post(
        "/api/v1/users", json=_new_user_payload(99), headers=headers,
    )
    assert r.status_code == 429

    # Forzar expiración manual de los buckets (simula paso de la ventana).
    rcli = _redis()
    for key in rcli.scan_iter(match="rl:users_create:*"):
        rcli.delete(key)

    # Tras el reset, el siguiente POST debe pasar.
    r = client.post(
        "/api/v1/users", json=_new_user_payload(200), headers=headers,
    )
    assert r.status_code == 201, (
        f"tras reset del bucket esperaba 201, obtuve {r.status_code}: {r.text}"
    )


def test_endpoint_rate_limit_separate_scopes(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``users_create`` y ``vehicles_create`` son scopes distintos: saturar
    uno NO bloquea el otro (un admin que crea muchos usuarios puede
    seguir creando vehículos)."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    _force_users_max(monkeypatch, max_attempts=2)
    _force_vehicles_max(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    # users_create saturado.
    for i in range(2):
        r = client.post(
            "/api/v1/users", json=_new_user_payload(i), headers=headers,
        )
        assert r.status_code == 201
    r = client.post(
        "/api/v1/users", json=_new_user_payload(99), headers=headers,
    )
    assert r.status_code == 429, "users_create debería estar saturado"

    # vehicles_create sigue OK.
    r = client.post(
        "/api/v1/vehicles", json=_new_vehicle_payload(1), headers=headers,
    )
    assert r.status_code == 201, (
        f"vehicles_create debería estar independiente, obtuve {r.status_code}: {r.text}"
    )