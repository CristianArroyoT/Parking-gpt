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

    # Sustituir SessionLocal que ``app.services.manual_tickets`` y
    # ``app.services.ingest_service`` abren internamente, para que apunten
    # al motor de prueba y vean los datos sembrados.
    from app.services import manual_tickets as mt_mod
    from app.services import ingest_service as ingest_mod
    monkeypatch.setattr(mt_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ingest_mod, "SessionLocal", SessionLocal)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


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