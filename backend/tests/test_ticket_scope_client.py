"""Regresión del ámbito de ``GET /api/v1/tickets`` para el rol cliente.

**Fuga de datos entre clientes** (detectada en la revisión de T-19):

``_scoped_query`` acotaba los tickets de cualquier usuario no-admin por sus
**membresías de sucursal**. Para gestor y operador eso es correcto, pero un
cliente también puede tener membresía (el admin puede dársela desde
``POST /users/{id}/memberships``) y entonces veía **los tickets de todos los
vehículos de esa sucursal**, incluidos los de otros clientes: matrículas,
importes y horas de entrada deConductores ajenos.

El ámbito correcto del cliente son **sus vehículos** (relación
``vehicle_users``), no la sucursal.

Estos tests fijan ese contrato: con membresía de sucursal o sin ella, un
cliente sólo ve los tickets de los vehículos que posee o conduce.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus, TicketOrigin, VehicleRole
from app.models.ticket import Ticket
from app.models.user import ParkingMembership
from app.models.vehicle import Vehicle, VehicleUser
from tests._audit_helpers import (
    _login_headers,
    _seed_cliente,
    _seed_parking,
)


def _vehiculo(db: Session, plate: str) -> Vehicle:
    vehiculo = Vehicle(plate=plate)
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def _vincular(db: Session, vehicle: Vehicle, user_id: int, role: VehicleRole) -> None:
    db.add(
        VehicleUser(vehicle_id=vehicle.id, user_id=user_id, role=role)
    )
    db.commit()


def _ticket(db: Session, *, parking_id: int, vehicle_id: int) -> Ticket:
    entrada = datetime.now(timezone.utc) - timedelta(minutes=90)
    ticket = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle_id,
        status=TicketStatus.CERRADO,
        entry_at=entrada,
        exit_at=entrada + timedelta(minutes=30),
        amount=2.5,
        total=2.5,
        origin=TicketOrigin.AUTOMATIC,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _escenario(db: Session):
    """Dos clientes, un vehículo cada uno, y un ticket por vehículo."""
    parking = _seed_parking(db, code="P-SCOPE")
    cliente_a = _seed_cliente(db, email="a@scope.es")
    cliente_b = _seed_cliente(db, email="b@scope.es")

    veh_a = _vehiculo(db, "1111-AAA")
    veh_b = _vehiculo(db, "2222-BBB")
    _vincular(db, veh_a, cliente_a.id, VehicleRole.PROPIETARIO)
    _vincular(db, veh_b, cliente_b.id, VehicleRole.PROPIETARIO)

    ticket_a = _ticket(db, parking_id=parking.id, vehicle_id=veh_a.id)
    ticket_b = _ticket(db, parking_id=parking.id, vehicle_id=veh_b.id)
    return parking, cliente_a, cliente_b, ticket_a, ticket_b


def test_un_cliente_sin_membrescia_solo_ve_sus_tickets(
    client: TestClient, db_session: Session
) -> None:
    """Sin membresía, el cliente ya veía sólo lo suyo (no debe cambiar)."""
    _parking, cliente, _otro, ticket_propio, _ticket_ajeno = _escenario(db_session)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.get("/api/v1/tickets", headers=headers)

    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert ids == [ticket_propio.id]


def test_un_cliente_con_membrescia_de_sucursal_no_ve_tickets_ajenos(
    client: TestClient, db_session: Session
) -> None:
    """Con membresía de sucursal, el cliente NO puede ver tickets ajenos.

    Este es el caso que arregla el arreglo: antes, la membresía le daba
    acceso a los tickets de **todos** los vehículos de la sucursal.
    """
    parking, cliente, _otro, ticket_propio, ticket_ajeno = _escenario(db_session)
    db_session.add(
        ParkingMembership(user_id=cliente.id, parking_id=parking.id)
    )
    db_session.commit()

    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/tickets", headers=headers)

    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert ticket_propio.id in ids
    assert ticket_ajeno.id not in ids, (
        "el cliente ve tickets de vehículos que no son suyos: fuga de datos "
        "entre clientes (LOPDGDD)"
    )


def test_el_filtro_por_sucursal_no_amplia_la_vista_del_cliente(
    client: TestClient, db_session: Session
) -> None:
    """``?parking_id=`` no puede ampliar el ámbito del cliente."""
    parking, cliente, _otro, ticket_propio, ticket_ajeno = _escenario(db_session)
    db_session.add(
        ParkingMembership(user_id=cliente.id, parking_id=parking.id)
    )
    db_session.commit()

    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get(f"/api/v1/tickets?parking_id={parking.id}", headers=headers)

    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert ids == [ticket_propio.id]
    assert ticket_ajeno.id not in ids


def test_un_gestor_sigue_viendo_los_tickets_de_su_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """El cambio NO debe tocar el ámbito del gestor: sigue viendo la sucursal."""
    from tests._audit_helpers import _seed_gestor

    parking, _cliente_a, _cliente_b, ticket_a, ticket_b = _escenario(db_session)
    gestor = _seed_gestor(db_session, email="gestor@scope.es")
    db_session.add(
        ParkingMembership(user_id=gestor.id, parking_id=parking.id)
    )
    db_session.commit()

    headers = _login_headers(client, gestor.email, "gestor1234")
    r = client.get(f"/api/v1/tickets?parking_id={parking.id}", headers=headers)

    assert r.status_code == 200
    ids = {t["id"] for t in r.json()}
    assert ticket_a.id in ids
    assert ticket_b.id in ids


def test_el_ambito_no_depende_del_rol_concreto(
    client: TestClient, db_session: Session
) -> None:
    """El cliente sólo ve sus vehículos, con o sin membresía de sucursal."""
    parking, cliente, _otro, _propio, ticket_ajeno = _escenario(db_session)
    db_session.add(
        ParkingMembership(user_id=cliente.id, parking_id=parking.id)
    )
    db_session.commit()

    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/tickets", headers=headers)

    assert r.status_code == 200
    assert ticket_ajeno.id not in [t["id"] for t in r.json()]
