"""Tests de integración contra PostgreSQL (el motor de producción).

POR QUÉ existe este fichero (T-04, plan maestro 2026-10-21)
-------------------------------------------------------------
Hasta el 2026-10-21 TODA la suite corría contra SQLite en memoria,
también en el CI (que levantaba un PostgreSQL real que nadie usaba).
Por eso un ``strftime()`` —función que sólo existe en SQLite— pasó el
CI, llegó a ``main`` y en Docker devolvió HTTP 500:

    function strftime(character varying, timestamp with time zone) does not exist

Estos tests son el "canario" del motor real:

1. Comprueban que, cuando ``TEST_DATABASE_URL`` apunta a PostgreSQL, la
   suite **efectivamente** usa PostgreSQL (no un SQLite disfrazado).
2. Comprueban que el esquema lo crea y destruye la propia sesión de
   tests (sin depender de que alguien se haya acordado de ejecutar
   ``alembic upgrade head``).
3. Ejecutan el endpoint que devolvía 500 en producción y comprueban que
   la duración media de los tickets se calcula bien (el bug era
   exactamente ese cálculo).
4. Demuestran, con un test, **por qué** hace falta el detector de
   funciones sólo de SQLite: en PostgreSQL, ``strftime()`` es un error.

En local se ejecuta así (la base ``parking_test`` es aislada):

    docker exec -e TEST_DATABASE_URL=postgresql+psycopg://parking:parking@db:5432/parking_test \\
        parking-backend-1 pytest -q

En el CI lo hace el job ``integration`` de ``.github/workflows/ci.yml``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from tests._audit_helpers import _login_headers, _seed_admin, _seed_parking
from tests.conftest import ES_POSTGRES

#: Marca los tests que sólo tienen sentido contra PostgreSQL.
pytestmark = pytest.mark.postgres

#: Saltar los tests cuando la suite corre contra SQLite (default local).
solo_postgres = pytest.mark.skipif(
    not ES_POSTGRES,
    reason="Requiere TEST_DATABASE_URL con PostgreSQL (motor de producción)",
)


# ── 1. la suite usa de verdad PostgreSQL ──────────────────────────────────

@solo_postgres
def test_el_motor_de_la_suite_es_postgresql(db_session: Session) -> None:
    """Si esto falla, el job ``integration`` del CI no está probando nada."""
    assert db_session.get_bind().dialect.name == "postgresql"


@solo_postgres
def test_el_esquema_lo_crea_la_propia_sesion_de_tests(db_session: Session) -> None:
    """El esquema existe sin que nadie haya ejecutado Alembic.

    En el CI la base ``parking_test`` arranca VACÍA: si la sesión de tests
    no crease las tablas, todos los tests fallarían con
    ``relation "tickets" does not exist``.
    """
    tablas = set(inspect(db_session.get_bind()).get_table_names())
    assert "tickets" in tablas
    assert "users" in tablas
    assert "parkings" in tablas


@solo_postgres
def test_las_tablas_estan_vacias_al_empezar_cada_test(db_session: Session) -> None:
    """Aislamiento entre tests: ``TRUNCATE`` + ``RESTART IDENTITY``."""
    assert db_session.query(Ticket).count() == 0
    assert db_session.query(Vehicle).count() == 0


@solo_postgres
def test_el_motor_de_la_app_es_el_de_la_bd_de_test(db_session: Session) -> None:
    """``app.core.db`` no puede apuntar a la BD de desarrollo.

    Si el motor de la app apuntase a otra base, un test que se escapase
    del override escribiría datos de prueba en la BD de desarrollo.
    """
    from app.core.db import engine as engine_app

    assert engine_app.url.database == db_session.get_bind().url.database


# ── 2. por qué hace falta el detector de funciones sólo de SQLite ─────────

@solo_postgres
def test_una_funcion_solo_de_sqlite_falla_en_postgres(db_session: Session) -> None:
    """``strftime()`` es un error en PostgreSQL: el canario del bug de 500.

    Este test es la demostración de por qué existe
    ``test_sqlite_only_functions.py``: si el detector no existiera, este
    ``strftime()`` podría colarse en la app y devolver HTTP 500 en
    producción sin que nadie se entere.
    """
    with pytest.raises(DatabaseError) as exc_info:
        db_session.execute(text("SELECT strftime('%Y', NOW())"))
    assert "strftime" in str(exc_info.value).lower()


@solo_postgres
def test_extract_epoch_es_el_equivalente_portable(db_session: Session) -> None:
    """``func.extract('epoch', ...)`` funciona en PostgreSQL (y en SQLite)."""
    esperado = int(datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc).timestamp())
    valor = db_session.execute(
        text("SELECT EXTRACT(EPOCH FROM TIMESTAMPTZ '2026-07-06 12:00:00+00')")
    ).scalar()
    assert int(valor) == esperado


# ── 3. regresión del bug que llegó a producción ───────────────────────────

@solo_postgres
def test_el_resumen_de_tickets_calcula_la_duracion_en_postgres(
    db_session: Session,
) -> None:
    """La duración media sale bien con el motor real (bug del ``strftime``).

    Con el ``strftime()`` de SQLite, el endpoint devolvía 500 en Docker.
    Con ``func.extract('epoch', ...)`` la media debe salir exacta: 90
    minutos (un ticket de 60 y otro de 120).
    """
    from app.services.ticket_summary import compute_ticket_summary

    ahora = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    parking = _seed_parking(db_session, code="P-PG")
    vehiculo = Vehicle(plate="PG-1")
    db_session.add(vehiculo)
    db_session.commit()
    db_session.refresh(vehiculo)

    for entrada, salida in (
        (ahora - timedelta(minutes=30), ahora + timedelta(minutes=30)),
        (ahora - timedelta(hours=2), ahora),
    ):
        ticket = Ticket(
            parking_id=parking.id,
            vehicle_id=vehiculo.id,
            status=TicketStatus.CERRADO,
            entry_at=entrada,
            exit_at=salida,
            total=5.0,
        )
        db_session.add(ticket)
    db_session.commit()

    resumen = compute_ticket_summary(db_session, parking.id, now=ahora)

    assert resumen.closed_tickets_24h == 2
    assert resumen.total_revenue_24h == 10.0
    # (60 + 120) / 2 = 90 minutos. El bug de SQLite devolvía -3514446000.
    assert resumen.average_duration_minutes == 90.0


@solo_postgres
def test_el_endpoint_del_resumen_no_devuelve_500(
    db_session: Session, client: TestClient,
) -> None:
    """El endpoint que reventó en Docker responde 200 contra PostgreSQL."""
    parking = _seed_parking(db_session, code="P-PE")
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.get(f"/api/v1/parkings/{parking.id}/tickets/summary", headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["average_duration_minutes"] is None


@solo_postgres
def test_las_fechas_vuelven_con_zona_horaria(db_session: Session) -> None:
    """PostgreSQL guarda TIMESTAMPTZ: la fecha vuelve con ``tzinfo``.

    En SQLite las ``DateTime(timezone=True)`` vuelven *naive*, así que
    comparar una fecha de la BD con ``datetime.now(timezone.utc)`` es un
    ``TypeError`` en SQLite y funciona en PostgreSQL. Es otra diferencia
    real entre los dos motores que sólo se ve corriendo contra Postgres.
    """
    parking = _seed_parking(db_session, code="P-TZ")
    vehiculo = Vehicle(plate="TZ-1")
    db_session.add(vehiculo)
    db_session.commit()
    db_session.refresh(vehiculo)

    entrada = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
    db_session.add(
        Ticket(
            parking_id=parking.id,
            vehicle_id=vehiculo.id,
            status=TicketStatus.ACTIVO,
            entry_at=entrada,
        )
    )
    db_session.commit()
    db_session.expire_all()

    ticket = db_session.query(Ticket).one()
    assert ticket.entry_at.tzinfo is not None
    assert ticket.entry_at == entrada
