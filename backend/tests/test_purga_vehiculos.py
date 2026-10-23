"""La purga de vehículos «fantasma» (T-125).

Un vehículo fantasma es el que creó la ingesta (matrícula desconocida) y
que se quedó **sin dueño y sin ticket**. Nadie los borraba: medido el
2026-10-23 en la base de datos de QA, había 3 con cero dueños y cero
tickets, creados cuatro meses antes.

Aquí se fija el criterio, que son **tres** condiciones:

1. sin dueño (``vehicle_users`` vacío): un vehículo que el cliente dio de
   alta en la app tiene dueño y **no** se toca;
2. sin tickets (ni activos ni cerrados);
3. antiguo: el vehículo de un coche que acaba de entrar puede quedarse
   sin ticket un momento (su ticket se escribe después), así que no se
   borra hasta que tiene edad.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle, VehicleUser
from app.services.vehicle_purge import purgar_vehiculos_fantasma
from tests._audit_helpers import _seed_cliente

ANTIGUEDAD = timedelta(days=3)
AHORA = datetime.now(timezone.utc)


def _vehiculo(db: Session, plate: str, *, dias: int = 5) -> Vehicle:
    """Un vehículo creado ``dias`` días atrás."""
    vehiculo = Vehicle(
        plate=plate,
        created_at=AHORA - timedelta(days=dias),
    )
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def test_borra_el_vehiculo_fantasma_antiguo(
    client: TestClient, db_session: Session
) -> None:
    """Sin dueño, sin tickets y viejo → se borra."""
    vehiculo = _vehiculo(db_session, "1111FAN")

    resultado = purgar_vehiculos_fantasma(db_session)

    assert resultado["deleted"] == 1, resultado
    db_session.expire_all()
    assert db_session.get(Vehicle, vehiculo.id) is None


def test_no_borra_un_vehiculo_con_dueno(
    client: TestClient, db_session: Session
) -> None:
    """Un coche dado de alta por un cliente tiene dueño → se queda."""
    vehiculo = _vehiculo(db_session, "2222PRO")
    usuario = _seed_cliente(db_session, email="dueno@purga.es")
    db_session.add(VehicleUser(user_id=usuario.id, vehicle_id=vehiculo.id))
    db_session.commit()

    resultado = purgar_vehiculos_fantasma(db_session)

    assert resultado["deleted"] == 0, resultado
    db_session.expire_all()
    assert db_session.get(Vehicle, vehiculo.id) is not None


def test_no_borra_un_vehiculo_con_ticket(
    client: TestClient, db_session: Session
) -> None:
    """Un vehículo que ha entrado alguna vez tiene ticket → se queda."""
    vehiculo = _vehiculo(db_session, "3333CON")
    db_session.add(
        Ticket(
            parking_id=1,
            vehicle_id=vehiculo.id,
            status=TicketStatus.ACTIVO,
            entry_at=AHORA - ANTIGUEDAD,
        )
    )
    db_session.commit()

    resultado = purgar_vehiculos_fantasma(db_session)

    assert resultado["deleted"] == 0, resultado
    db_session.expire_all()
    assert db_session.get(Vehicle, vehiculo.id) is not None


def test_no_borra_un_vehiculo_reciente(
    client: TestClient, db_session: Session
) -> None:
    """Sin dueño y sin tickets, pero **reciente** → se queda.

    El coche puede haber entrado ahora mismo: su ticket se escribe un
    momento después.
    """
    vehiculo = _vehiculo(db_session, "4444NUE", dias=0)

    resultado = purgar_vehiculos_fantasma(db_session)

    assert resultado["deleted"] == 0, resultado
    db_session.expire_all()
    assert db_session.get(Vehicle, vehiculo.id) is not None


def test_la_purga_es_idempotente(
    client: TestClient, db_session: Session
) -> None:
    """La segunda pasada no borra nada (y no falla)."""
    _vehiculo(db_session, "5555IDEM")

    primera = purgar_vehiculos_fantasma(db_session)
    segunda = purgar_vehiculos_fantasma(db_session)

    assert primera["deleted"] == 1, primera
    assert segunda["deleted"] == 0, segunda


def test_la_purga_respeta_el_corte_explicito(
    client: TestClient, db_session: Session
) -> None:
    """Con ``max_age_hours`` se decide qué es viejo (y qué no)."""
    viejo = _vehiculo(db_session, "6666COR", dias=5)
    reciente = _vehiculo(db_session, "7777COR", dias=0)

    resultado = purgar_vehiculos_fantasma(db_session, max_age_hours=48)

    assert resultado["deleted"] == 1, resultado
    db_session.expire_all()
    assert db_session.get(Vehicle, viejo.id) is None
    assert db_session.get(Vehicle, reciente.id) is not None
