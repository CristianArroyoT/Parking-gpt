"""Fixtures compartidas: cliente HTTP contra la app en memoria + BD SQLite en memoria."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ASYNC_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — fuerza el registro de todas las tablas en Base.metadata
from app.core.db import Base, get_db
from app.main import create_app


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Sustituir SessionLocal que ``app.services.manual_tickets``,
    # ``app.services.incidents`` y ``app.services.ingest_service`` abren
    # internamente, para que apunten al motor de prueba y vean los datos
    # sembrados.
    from app.services import manual_tickets as mt_mod
    from app.services import ingest_service as ingest_mod
    from app.services import incidents as inc_mod
    monkeypatch.setattr(mt_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ingest_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(inc_mod, "SessionLocal", SessionLocal)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _clean_redis_counters():
    """Limpia todas las claves de Redis usadas por ``app.services.alerts``.

    Sin esto, los contadores

    - ``camera:{id}:consecutive_fails`` y ``camera:{id}:ocr_alert_lock``
      (escritos por ``record_ocr_failure`` / ``reset_ocr_failure``),
    - ``camera:{id}:consecutive_offline`` y ``camera:{id}:offline_lock``
      (escritos por ``record_camera_offline`` / ``reset_camera_offline``),

    se acumulan entre tests porque la BD usa StaticPool (los IDs se
    reinician) pero Redis NO se resetea. Un test que cree cámara id=1
    después de otro que tocó cámara id=1 hereda su contador.

    Sólo barremos IDs 1..200 porque los tests crean cámaras con IDs
    bajos en la práctica. Si Redis no responde, ignoramos: el resto
    de la suite sigue funcionando y los tests que tocan Redis son
    tolerantes a fallos del broker.
    """
    try:
        from app.services.alerts import (
            _consecutive_key, _lock_key,
            _consecutive_offline_key, _offline_lock_key,
            _redis_client,
        )
        client = _redis_client()
        for cam_id in range(1, 200):
            client.delete(
                _consecutive_key(cam_id), _lock_key(cam_id),
                _consecutive_offline_key(cam_id), _offline_lock_key(cam_id),
            )
        # Sprint Fase 3C: rate-limit de login. Las claves usan como
        # sufijo la IP y el email (no el cam_id), pero las borramos
        # también con un SCAN para no contaminar entre tests.
        for key in client.scan_iter("rl:login:*"):
            client.delete(key)
        # Sprint Fase 3D: token blacklist + rate-limit de endpoints.
        # - ``jwt:blacklist:*``: jti de tokens invalidados en logout.
        # - ``rl:{scope}:*``: buckets genéricos del ``EndpointRateLimiter``
        #   (``users_create``, ``users_update``, ``vehicles_create``,
        #   ``vehicles_update``, ...).
        for key in client.scan_iter("jwt:blacklist:*"):
            client.delete(key)
        for key in client.scan_iter("rl:users_*"):
            client.delete(key)
        for key in client.scan_iter("rl:vehicles_*"):
            client.delete(key)
        # Sprint R5 (2026-07-06): rate-limit en parkings/tariffs/cameras.
        for prefix in ("rl:parkings_*", "rl:tariffs_*", "rl:cameras_*",
                       "rl:geofences_*"):
            for key in client.scan_iter(prefix):
                client.delete(key)
        # Sprint R2-followup: set de jtis activos por usuario que mantiene
        # ``session_tracker`` para que ``POST /auth/logout/all`` pueda
        # invalidarlos. Sin esto, los jtis de tests previos contaminan
        # el set del user_id usado por otros tests.
        for key in client.scan_iter("user:*:active_jtis"):
            client.delete(key)
    except Exception:
        pass
    return


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client