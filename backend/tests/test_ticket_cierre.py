"""Cerrar un ticket es una operación de personal, no del cliente (T-120).

Medido contra el sistema en marcha (2026-10-23), antes del arreglo: un
conductor podía cerrar **su propio** ticket activo::

    [cliente] POST /tickets/620/close                    -> [200]
    [cliente] POST /tickets/621/close  (exit_at = ayer)  -> [200]  (22,50 EUR
                por una estancia de 10 dias)

Es decir: el cliente no sólo cerraba su estancia, **fijaba la hora de
salida** y por tanto **el importe de su propio cobro**. Los tickets los
cierra la cámara de salida (o el personal, a mano).

El arreglo: ``POST /tickets/{id}/close`` exige un rol de personal
(``require_role(*ROLES_STAFF)``), como ya exigía ``POST /tickets``
(que bloquea al cliente explícitamente).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.user import ParkingMembership
from app.models.vehicle import Vehicle
from tests._audit_helpers import (
    _login_headers,
    _seed_cliente,
    _seed_gestor,
    _seed_parking,
)


def _vehiculo_del_cliente(db: Session, cliente_id: int, plate: str = "1111-AAA") -> Vehicle:
    """Un vehiculo vinculado al cliente (para que el ticket sea suyo)."""
    from app.models.vehicle import VehicleUser

    vehiculo = Vehicle(plate=plate)
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    db.add(VehicleUser(user_id=cliente_id, vehicle_id=vehiculo.id, role="propietario"))
    db.commit()
    return vehiculo


def _escenario(db: Session):
    parking = _seed_parking(db, code="P-A")
    cliente = _seed_cliente(db, email="cliente@cierre.es")
    gestor = _seed_gestor(db, email="gestor@cierre.es")
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking.id))
    db.commit()
    vehiculo = _vehiculo_del_cliente(db, cliente.id)
    _tarifa(db, parking.id)
    return parking, cliente, gestor, vehiculo


def _tarifa(db: Session, parking_id: int) -> None:
    """Una tarifa vigente: sin ella, el cierre da 409 ("no hay tarifa")."""
    from app.models.pricing import Tariff

    db.add(
        Tariff(
            parking_id=parking_id,
            name="tarifa de test",
            price_per_hour=1.5,
            price_per_fraction=0.05,
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.commit()


def test_un_cliente_no_puede_cerrar_su_propio_ticket(
    client: TestClient, db_session: Session
) -> None:
    """El cierre de un ticket es del personal: el cliente recibe 403."""
    parking, cliente, _gestor, vehiculo = _escenario(db_session)
    headers_gestor = _login_headers(client, "gestor@cierre.es", "gestor1234")

    abierto = client.post(
        "/api/v1/tickets",
        headers=headers_gestor,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert abierto.status_code == 201, abierto.text
    ticket_id = abierto.json()["id"]

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers_cliente,
        json={"exit_at": datetime.now(timezone.utc).isoformat()},
    )

    assert r.status_code == 403, r.text
    db_session.expire_all()
    ticket = db_session.get(Ticket, ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.ACTIVO, "el cliente cerró su propio ticket"
    assert ticket.total is None, "se cobró una estancia que el cliente cerró"


def test_un_cliente_no_puede_fijar_la_hora_de_salida(
    client: TestClient, db_session: Session
) -> None:
    """Ni siquiera cerrando "ayer": el importe lo decide el sistema."""
    parking, cliente, _gestor, vehiculo = _escenario(db_session)
    headers_gestor = _login_headers(client, "gestor@cierre.es", "gestor1234")

    entrada = datetime.now(timezone.utc) - timedelta(days=10)
    abierto = client.post(
        "/api/v1/tickets",
        headers=headers_gestor,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": entrada.isoformat(),
        },
    )
    assert abierto.status_code == 201, abierto.text
    ticket_id = abierto.json()["id"]

    headers_cliente = _login_headers(client, cliente.email, "cliente1234")
    ayer = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers_cliente,
        json={"exit_at": ayer},
    )

    assert r.status_code == 403, r.text
    db_session.expire_all()
    ticket = db_session.get(Ticket, ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.ACTIVO
    assert ticket.exit_at is None, "se fijó la hora de salida desde el cliente"


def test_el_personal_puede_cerrar_el_ticket_de_su_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """Control: el camino bueno no se ha roto."""
    parking, _cliente, gestor, vehiculo = _escenario(db_session)
    headers_gestor = _login_headers(client, gestor.email, "gestor1234")

    abierto = client.post(
        "/api/v1/tickets",
        headers=headers_gestor,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert abierto.status_code == 201, abierto.text
    ticket_id = abierto.json()["id"]

    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers_gestor,
        json={"exit_at": datetime.now(timezone.utc).isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cerrado"


def test_un_gestor_de_otra_sucursal_no_puede_cerrar_el_ticket(
    client: TestClient, db_session: Session
) -> None:
    """El cierre tambien se acota a la sucursal."""
    parking, _cliente, _gestor, vehiculo = _escenario(db_session)
    headers_gestor = _login_headers(client, "gestor@cierre.es", "gestor1234")

    abierto = client.post(
        "/api/v1/tickets",
        headers=headers_gestor,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    ticket_id = abierto.json()["id"]

    otro = _seed_gestor(db_session, email="gestor.otro@cierre.es")
    otra_sucursal = _seed_parking(db_session, code="P-B")
    db_session.add(
        ParkingMembership(user_id=otro.id, parking_id=otra_sucursal.id)
    )
    db_session.commit()
    headers_otro = _login_headers(client, otro.email, "gestor1234")

    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers_otro,
        json={"exit_at": datetime.now(timezone.utc).isoformat()},
    )
    assert r.status_code in (403, 404), r.text


def test_el_cierre_manual_publica_el_evento_del_bus(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    """T-127: el cierre manual publica ``TICKET_CLOSED`` en el bus.

    El cierre por cámara y el alta manual ya lo hacían (para que el mapa
    del gestor se actualice al instante); el manual no, así que la app
    se enteraba hasta el poll de 30 s.
    """
    import json as _json

    publicados: list[tuple[str, str]] = []

    class _FakeRedis:
        def publish(self, channel: str, body: str) -> int:
            publicados.append((channel, body))
            return 1

    monkeypatch.setattr(
        "redis.Redis.from_url", lambda url, **kwargs: _FakeRedis()
    )

    parking, _cliente, gestor, vehiculo = _escenario(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")

    abierto = client.post(
        "/api/v1/tickets",
        headers=headers,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert abierto.status_code == 201, abierto.text
    ticket_id = abierto.json()["id"]

    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers,
        json={"exit_at": datetime.now(timezone.utc).isoformat()},
    )
    assert r.status_code == 200, r.text

    assert publicados, "el cierre manual no publicó nada en el bus"
    canal, cuerpo = publicados[0]
    assert canal == f"parking:{parking.id}:events"
    evento = _json.loads(cuerpo)
    assert evento["type"] == "ticket_closed"
    assert evento["payload"]["ticket_id"] == ticket_id
