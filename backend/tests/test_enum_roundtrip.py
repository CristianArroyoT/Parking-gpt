"""Regression tests para el round-trip de enums nativos Postgres (Fase 4).

Síntoma observado en producción (Postgres + Sprint Fase 4, 2026-07-01):
al listar cámaras con ``GET /api/v1/parkings/{id}/cameras``, el backend
devolvía 500 con::

    LookupError: 'surveillance' is not among the defined enum values.
    Enum name: camerakind. Possible values: SURVEILLANC.., GATE

Causa raíz: la migración ``0009_camera_kind`` creó el tipo nativo
Postgres ``camerakind`` con valores **minúscula** (``surveillance``,
``gate``). Pero el modelo ``Camera`` declaraba
``Enum(CameraKind, name="camerakind")`` sin ``values_callable``: por
defecto SQLAlchemy usa los **nombres** del enum Python
(``SURVEILLANCE``, ``GATE`` mayúsculas) para escribir y leer. En
SQLite el bug queda oculto (la columna es VARCHAR sin constraint),
pero en Postgres el round-trip explota.

Fix (parking.py:80 + cost.py:45/54): añadir
``values_callable=lambda obj: [e.value for e in obj]`` para que
SQLAlchemy use los **values** (lowercase), que coinciden con el tipo
Postgres nativo.

Tests cubiertos:

  1. ``Camera.kind`` usa los values lowercase (configuración).
  2. Round-trip Camera con ``kind='surveillance'`` (valor nativo
     Postgres) no lanza ``LookupError``.
  3. Round-trip Camera con ``kind='gate'`` idem.
  4. ``Cost.category`` usa los values lowercase.
  5. ``Cost.periodicity`` usa los values lowercase.

Estos tests son **white-box**: no necesitan Postgres real porque
ejercitan directamente el comportamiento del mapping SQLAlchemy sobre
un valor que coincide con el almacenamiento nativo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — registro de todas las tablas en Base.metadata
from app.models.cost import Cost
from app.models.enums import (
    CameraKind,
    CostCategory,
    CostPeriod,
)
from app.models.parking import Camera, Parking


@pytest.fixture()
def db_session(motor_de_test):
    """Sesión sobre el motor del dialecto de la suite.

    En SQLite no se validan los valores del enum (los trata como VARCHAR),
    pero el comportamiento que queremos probar es el del lado Python de
    SQLAlchemy: cuando lee una columna ``kind`` con el valor
    ``'surveillance'`` (string real de Postgres), ¿lo resuelve
    correctamente al enum Python? Sin ``values_callable``, el lookup
    explota; con él, retorna ``CameraKind.SURVEILLANCE``.

    Con la fixture ``motor_de_test`` este fichero también se ejecuta
    contra PostgreSQL cuando la suite corre contra PostgreSQL.
    """
    engine = motor_de_test
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False,
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Camera.kind ──────────────────────────────────────────────────────


def test_camera_kind_column_uses_lowercase_values():
    """El mapping SQLAlchemy de ``Camera.kind`` debe tener
    ``values_callable`` configurado para usar los values lowercase del
    enum (``surveillance``, ``gate``). Sin esto, usaría los nombres
    UPPERCASE y el round-trip contra el enum nativo Postgres falla.
    """
    col_type = Camera.__table__.c.kind.type
    assert hasattr(col_type, "values_callable"), (
        "Camera.kind.type debe declarar values_callable para mapear al "
        "enum nativo Postgres (valores en minúscula)."
    )
    values = list(col_type.values_callable(CameraKind))
    assert values == ["surveillance", "gate"], (
        f"values_callable debe devolver los .value del enum en orden; "
        f"got {values}"
    )


def test_camera_kind_roundtrip_surveillance(db_session: Session):
    """Round-trip: insertar Camera con ``kind='surveillance'`` (valor
    nativo Postgres) y leerlo de vuelta debe resolver al enum Python
    correcto sin ``LookupError``.
    """
    p = Parking(code="P-RT1", name="RT-1", address="X", city="Y")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    # INSERT con el valor literal que produce Postgres (lowercase).
    # Usamos SQL crudo para bypassear SQLAlchemy ORM-side: queremos
    # asegurar que el LADO LECTURA resuelve 'surveillance' aunque el
    # INSERT no haya pasado por la conversión de SQLAlchemy.
    db_session.execute(
        insert(Camera).values(
            parking_id=p.id,
            code="CAM-RT-S",
            name="Roundtrip surveillance",
            rtsp_url="rtsp://x/y",
            fps=10,
            kind="surveillance",  # lowercase, como Postgres
        )
    )
    db_session.commit()

    # Lectura ORM: este es el path que rompía con LookupError.
    cam = db_session.execute(
        select(Camera).where(Camera.code == "CAM-RT-S")
    ).scalar_one()
    assert cam.kind == CameraKind.SURVEILLANCE
    assert cam.kind.value == "surveillance"


def test_camera_kind_roundtrip_gate(db_session: Session):
    """Idem para ``kind='gate'`` (portería)."""
    p = Parking(code="P-RT2", name="RT-2", address="X", city="Y")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    db_session.execute(
        insert(Camera).values(
            parking_id=p.id,
            code="CAM-RT-G",
            name="Roundtrip gate",
            rtsp_url="rtsp://x/y",
            fps=10,
            kind="gate",
        )
    )
    db_session.commit()

    cam = db_session.execute(
        select(Camera).where(Camera.code == "CAM-RT-G")
    ).scalar_one()
    assert cam.kind == CameraKind.GATE
    assert cam.kind.value == "gate"


# ── Cost.category / Cost.periodicity ────────────────────────────────


def test_cost_category_column_uses_lowercase_values():
    """Mismo bug latente que Camera.kind en ``Cost.category``.
    Migración 0010 creó el tipo Postgres ``costcategory`` con valores
    lowercase; el modelo debe reflejarlo.
    """
    col_type = Cost.__table__.c.category.type
    assert hasattr(col_type, "values_callable")
    values = list(col_type.values_callable(CostCategory))
    assert values == [
        "mantenimiento", "camaras", "operacion", "otros",
    ], f"values_callable debe devolver los .value de CostCategory; got {values}"


def test_cost_periodicity_column_uses_lowercase_values():
    """Mismo bug latente que Camera.kind en ``Cost.periodicity``.
    Migración 0010 creó ``costperiod`` con valores lowercase.
    """
    col_type = Cost.__table__.c.periodicity.type
    assert hasattr(col_type, "values_callable")
    values = list(col_type.values_callable(CostPeriod))
    assert values == [
        "puntual", "mensual", "trimestral", "anual",
    ], f"values_callable debe devolver los .value de CostPeriod; got {values}"


def test_cost_roundtrip(db_session: Session):
    """Round-trip Cost con valores lowercase (lo que Postgres almacena)."""
    p = Parking(code="P-RT3", name="RT-3", address="X", city="Y")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    db_session.execute(
        insert(Cost).values(
            parking_id=p.id,
            category="camaras",      # lowercase
            amount=99.5,
            periodicity="mensual",   # lowercase
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            description="RT test",
        )
    )
    db_session.commit()

    cost = db_session.execute(select(Cost)).scalar_one()
    assert cost.category == CostCategory.CAMARAS
    assert cost.category.value == "camaras"
    assert cost.periodicity == CostPeriod.MENSUAL
    assert cost.periodicity.value == "mensual"