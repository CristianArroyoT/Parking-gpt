"""La base de datos prohibe dos tickets activos del mismo vehículo (T-105).

POR QUÉ existe este fichero: la ingesta comprobaba antes de insertar
(un SELECT de «este vehículo ya tiene ticket activo») y después
insertaba. Eso es un «comprueba y luego hace»: dos pushes de la misma
matrícula a la vez (dos rondas solapadas, o dos peticiones
simultáneas) podían pasar las dos comprobaciones y crear **DOS tickets
activos** → el cliente cobraba dos veces.

La comprobación sigue ahí (es rápida y da un mensaje mejor), pero la
garantía **de verdad** está en la base de datos: un índice único
parcial sobre ``(vehicle_id, parking_id) WHERE status = 'activo'`` (y
otro sobre la plaza). Es lo único que una carrera no puede saltar.

Estos tests comprueban esa garantía:

1. dos tickets activos del mismo vehículo → la base lo rechaza;
2. dos tickets activos en la misma plaza → la base lo rechaza;
3. cerrar el ticket **sí** permite abrir otro (el índice es parcial:
   solo mira los activos).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.parking import Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle

AHORA = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _sembrar(db: Session) -> tuple[Parking, ParkingSpace, Vehicle]:
    parking = Parking(code="P-DUP", name="Duplicados", address="x", city="y")
    db.add(parking)
    db.flush()
    plaza = ParkingSpace(parking_id=parking.id, lane="A", number="01")
    db.add(plaza)
    db.flush()
    vehiculo = Vehicle(plate="4444-DDD")
    db.add(vehiculo)
    db.commit()
    db.refresh(parking)
    db.refresh(plaza)
    db.refresh(vehiculo)
    return parking, plaza, vehiculo


def _ticket(parking: Parking, vehiculo: Vehicle, plaza: ParkingSpace | None = None) -> Ticket:
    return Ticket(
        parking_id=parking.id,
        vehicle_id=vehiculo.id,
        parking_space_id=plaza.id if plaza else None,
        status=TicketStatus.ACTIVO,
        entry_at=AHORA,
    )


def test_no_se_pueden_crear_dos_tickets_activos_del_mismo_vehiculo(
    db_session: Session,
) -> None:
    """La base rechaza el segundo ticket activo del mismo vehículo."""
    parking, _plaza, vehiculo = _sembrar(db_session)
    db_session.add(_ticket(parking, vehiculo))
    db_session.commit()

    db_session.add(_ticket(parking, vehiculo))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_no_se_pueden_crear_dos_tickets_activos_en_la_misma_plaza(
    db_session: Session,
) -> None:
    """La base rechaza dos tickets activos en la misma plaza."""
    parking, plaza, vehiculo = _sembrar(db_session)
    db_session.add(_ticket(parking, vehiculo, plaza))
    db_session.commit()

    otro = Vehicle(plate="5555-EEE")
    db_session.add(otro)
    db_session.commit()
    db_session.add(_ticket(parking, otro, plaza))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cerrar_el_ticket_permite_abrir_otro(db_session: Session) -> None:
    """El índice es PARCIAL: solo mira los tickets activos."""
    parking, plaza, vehiculo = _sembrar(db_session)
    primero = _ticket(parking, vehiculo, plaza)
    db_session.add(primero)
    db_session.commit()

    primero.status = TicketStatus.CERRADO
    primero.exit_at = AHORA
    db_session.commit()

    segundo = _ticket(parking, vehiculo, plaza)
    db_session.add(segundo)
    db_session.commit()
    assert segundo.id is not None
