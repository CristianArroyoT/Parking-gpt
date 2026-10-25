"""Tests del endpoint de *readiness* ``GET /health/ready``.

POR QUÉ (2026-10-21): ``GET /health`` devolvía ``{"status": "ok"}`` sin
comprobar nada. Con Redis caído, el ``AuditMiddleware`` va a *fail-closed*
y **toda** petición autenticada devuelve 401 con *"Servicio de
autenticación no disponible"*, pero el health check seguía diciendo "ok":
``docker compose ps`` mostraba el backend como *healthy* mientras la API
era inusable. Estos tests comprueban que ``/health/ready`` dice la verdad.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import create_app
from app.services import health as health_mod


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _fijar_informe(monkeypatch, informe: dict) -> None:
    """Parchea la comprobación de dependencias.

    OJO: hay que parchear en ``app.main``, no en ``app.services.health``:
    ``main.py`` importa la función con ``from ... import``, así que el
    endpoint tiene su propia referencia y un parche en el módulo de
    origen no le llega.
    """
    monkeypatch.setattr(main_mod, "comprobar_dependencias", lambda: informe)


def test_health_es_liveness_y_no_mira_dependencias(client: TestClient) -> None:
    """``/health`` responde 200 siempre: es liveness, no readiness."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_ok_cuando_todo_responde(client: TestClient, monkeypatch) -> None:
    """Con la BD y Redis operativos, responde 200 y dice que está listo."""
    _fijar_informe(
        monkeypatch,
        {"ok": True, "dependencies": {"database": "ok", "redis": "ok"}},
    )
    r = client.get("/health/ready")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ready"
    assert cuerpo["dependencies"] == {"database": "ok", "redis": "ok"}


def test_health_ready_503_si_falla_redis(client: TestClient, monkeypatch) -> None:
    """Redis caído → 503 y el detalle dice cuál falló."""
    _fijar_informe(
        monkeypatch,
        {"ok": False, "dependencies": {"database": "ok", "redis": "ConnectionError"}},
    )
    r = client.get("/health/ready")
    assert r.status_code == 503
    cuerpo = r.json()
    assert cuerpo["status"] == "not_ready"
    assert cuerpo["dependencies"]["redis"] == "ConnectionError"


def test_health_ready_503_si_falla_la_base_de_datos(
    client: TestClient, monkeypatch
) -> None:
    """Base de datos caída → 503, aunque Redis esté bien."""
    _fijar_informe(
        monkeypatch,
        {"ok": False, "dependencies": {"database": "OperationalError", "redis": "ok"}},
    )
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["dependencies"]["database"] == "OperationalError"


def test_comprobar_dependencias_detecta_redis_caido(monkeypatch) -> None:
    """La comprobación real de Redis distingue 'ok' de 'caído'."""
    import redis

    class _Boom:
        def ping(self):
            raise redis.exceptions.ConnectionError("sin redis")

        def close(self) -> None:
            pass

    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: _Boom())
    ok, detalle = health_mod._comprobar_redis()
    assert ok is False
    assert detalle == "ConnectionError"


def test_comprobar_dependencias_ok_con_redis_real(monkeypatch) -> None:
    """Con un Redis que responde, la comprobación devuelve ``ok``."""
    class _Fake:
        def ping(self):
            return True

        def close(self) -> None:
            pass

    monkeypatch.setattr(health_mod.redis.Redis, "from_url", lambda *a, **k: _Fake())
    ok, detalle = health_mod._comprobar_redis()
    assert ok is True
    assert detalle == "ok"


def test_comprobar_bd_ok() -> None:
    """La comprobación de la base de datos devuelve ok si responde."""
    ok, detalle = health_mod._comprobar_bd()
    assert ok is True
    assert detalle == "ok"


def test_comprobar_bd_detecta_caida(monkeypatch) -> None:
    """Si la base de datos no responde, la comprobación lo dice."""
    from sqlalchemy.exc import OperationalError

    class _Boom:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("sin bd"))

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(health_mod.engine, "connect", lambda: _Boom())
    ok, detalle = health_mod._comprobar_bd()
    assert ok is False
    assert detalle == "OperationalError"


def test_comprobar_esquema_ok_con_el_esquema_real(
    monkeypatch, motor_de_test
) -> None:
    """Con el esquema aplicado, la comprobacion dice ``ok``.

    (T-185, 2026-10-25): antes de esto, una base **vacia** tambien
    pasaba la comprobacion de la base de datos (un ``SELECT 1`` funciona
    contra una base sin tablas), asi que un despliegue sin migraciones
    arrancaba, el healthcheck daba verde y todas las peticiones de
    verdad devolvian 500.

    OJO: se apunta al motor **de la suite** (el global de la app es otro:
    en los tests es una base en memoria sin esquema).
    """
    monkeypatch.setattr(health_mod, "engine", motor_de_test)
    ok, detalle = health_mod._comprobar_esquema()
    assert ok is True
    assert detalle == "ok"


def test_comprobar_esquema_detecta_una_tabla_que_falta(monkeypatch) -> None:
    """Si falta una tabla base, la comprobacion lo dice CUAL."""
    from sqlalchemy.exc import OperationalError

    class _Conexion:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, statement, *args, **kwargs):
            texto = str(statement)
            if "FROM tickets " in texto:
                raise OperationalError(texto, {}, Exception("no such table"))
            return None

    monkeypatch.setattr(health_mod.engine, "connect", lambda: _Conexion())

    ok, detalle = health_mod._comprobar_esquema()
    assert ok is False
    assert "tickets" in detalle, detalle


def test_el_readiness_incluye_el_esquema(monkeypatch, motor_de_test) -> None:
    """El informe de dependencias dice tambien si el esquema esta."""
    monkeypatch.setattr(health_mod, "engine", motor_de_test)
    informe = health_mod.comprobar_dependencias()
    assert "schema" in informe["dependencies"], informe
    assert informe["dependencies"]["schema"] == "ok", informe
