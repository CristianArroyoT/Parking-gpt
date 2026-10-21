"""Tests del ámbito de usuario: vehículos vinculados y tickets del cliente.

T-19 (2026-10-21). Cubre los endpoints *user-scoped* del router de
usuarios, que son los que consume la vista "Mis vehículos" del cliente:

  - ``GET    /api/v1/users/me/vehicles``
  - ``POST   /api/v1/users/me/vehicles``
  - ``PATCH  /api/v1/users/me/vehicles/{vehicle_id}``
  - ``POST   /api/v1/users/me/vehicles/{vehicle_id}/links``
  - ``DELETE /api/v1/users/me/vehicles/{vehicle_id}/links/{user_id}``
  - ``GET    /api/v1/users/me/tickets``

Por qué existen: ``/api/v1/vehicles`` es *staff-only* (un cliente recibe
403) y ``GET /api/v1/tickets`` acota por **membresía de sucursal**, no
por vehículo: un cliente con membresía vería los tickets de vehículos
ajenos. Aquí el scope es siempre ``vehicle_users`` (propietario o
conductor).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TicketOrigin, TicketStatus, VehicleRole
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from tests._audit_helpers import (
    _login_headers,
    _seed_cliente,
    _seed_parking,
)


def _crear_vehiculo(db: Session, plate: str) -> Vehicle:
    vehiculo = Vehicle(plate=plate)
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def _vincular(db: Session, vehicle: Vehicle, user: User, role: VehicleRole) -> None:
    db.add(
        VehicleUser(
            vehicle_id=vehicle.id,
            user_id=user.id,
            role=role,
        )
    )
    db.commit()


def _crear_ticket(
    db: Session, *, parking_id: int, vehicle_id: int, minutos: int = 0,
) -> Ticket:
    entrada = datetime.now(timezone.utc) - timedelta(minutes=minutos)
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


# ── Listado ─────────────────────────────────────────────────────────────


def test_list_my_vehicles_only_returns_linked_ones(
    client: TestClient, db_session: Session,
) -> None:
    """Un cliente sólo ve los vehículos vinculados a él."""
    mio = _seed_cliente(db_session, email="veh-mio@test.es")
    otro = _seed_cliente(db_session, email="veh-otro@test.es")
    v_mio = _crear_vehiculo(db_session, "1111MIO")
    v_otro = _crear_vehiculo(db_session, "2222OTR")
    _vincular(db_session, v_mio, mio, VehicleRole.PROPIETARIO)
    _vincular(db_session, v_otro, otro, VehicleRole.PROPIETARIO)

    headers = _login_headers(client, mio.email, "cliente1234")
    r = client.get("/api/v1/users/me/vehicles", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [v["plate"] for v in body] == ["1111MIO"]
    assert body[0]["my_role"] == "propietario"
    assert body[0]["links"][0]["email"] == "veh-mio@test.es"


def test_list_my_vehicles_empty(
    client: TestClient, db_session: Session,
) -> None:
    """Sin vínculos → lista vacía (no error)."""
    cliente = _seed_cliente(db_session, email="veh-vacio@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/users/me/vehicles", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


# ── Alta ────────────────────────────────────────────────────────────────


def test_create_my_vehicle_links_as_owner(
    client: TestClient, db_session: Session,
) -> None:
    """Alta de vehículo → 201 y el usuario queda como propietario."""
    cliente = _seed_cliente(db_session, email="veh-alta@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.post(
        "/api/v1/users/me/vehicles",
        json={"plate": "3333abc", "brand": "Seat", "color": "Rojo"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plate"] == "3333ABC"  # se normaliza a mayúsculas
    assert body["my_role"] == "propietario"
    assert body["brand"] == "Seat"

    # El vínculo existe en la tabla vehicle_users.
    db_session.expire_all()
    link = (
        db_session.query(VehicleUser)
        .filter(VehicleUser.user_id == cliente.id)
        .one_or_none()
    )
    assert link is not None
    assert link.role == VehicleRole.PROPIETARIO


def test_create_my_vehicle_duplicate_plate(
    client: TestClient, db_session: Session,
) -> None:
    """Matrícula repetida → 409."""
    cliente = _seed_cliente(db_session, email="veh-dup@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.post(
        "/api/v1/users/me/vehicles",
        json={"plate": "4444DUP"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/v1/users/me/vehicles",
        json={"plate": "4444DUP"},
        headers=headers,
    )
    assert r.status_code == 409, r.text


# ── Edición ─────────────────────────────────────────────────────────────


def test_update_my_vehicle_ok(
    client: TestClient, db_session: Session,
) -> None:
    """El propietario edita su vehículo."""
    cliente = _seed_cliente(db_session, email="veh-edit@test.es")
    vehiculo = _crear_vehiculo(db_session, "5555EDI")
    _vincular(db_session, vehiculo, cliente, VehicleRole.PROPIETARIO)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        f"/api/v1/users/me/vehicles/{vehiculo.id}",
        json={"color": "Azul", "model": "Leon"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["color"] == "Azul"
    assert r.json()["model"] == "Leon"


def test_update_my_vehicle_not_linked_404(
    client: TestClient, db_session: Session,
) -> None:
    """Un vehículo que no es del usuario → 404 (no se filtra información)."""
    cliente = _seed_cliente(db_session, email="veh-edit-404@test.es")
    vehiculo = _crear_vehiculo(db_session, "6666NOP")
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        f"/api/v1/users/me/vehicles/{vehiculo.id}",
        json={"color": "Azul"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_update_my_vehicle_as_conductor_403(
    client: TestClient, db_session: Session,
) -> None:
    """Un conductor no puede editar el vehículo: sólo el propietario."""
    cliente = _seed_cliente(db_session, email="veh-cond@test.es")
    vehiculo = _crear_vehiculo(db_session, "7777CON")
    _vincular(db_session, vehiculo, cliente, VehicleRole.CONDUCTOR)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.patch(
        f"/api/v1/users/me/vehicles/{vehiculo.id}",
        json={"color": "Azul"},
        headers=headers,
    )
    assert r.status_code == 403, r.text
    assert "propietario" in r.text


# ── Vínculos de rol ─────────────────────────────────────────────────────


def test_link_vehicle_user_by_email(
    client: TestClient, db_session: Session,
) -> None:
    """El propietario vincula a otra persona por email como conductor."""
    dueno = _seed_cliente(db_session, email="veh-dueno@test.es")
    familiar = _seed_cliente(db_session, email="veh-familiar@test.es")
    vehiculo = _crear_vehiculo(db_session, "8888VIN")
    _vincular(db_session, vehiculo, dueno, VehicleRole.PROPIETARIO)
    headers = _login_headers(client, dueno.email, "cliente1234")

    r = client.post(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links",
        json={"email": "veh-familiar@test.es", "role": "conductor"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "veh-familiar@test.es"
    assert body["role"] == "conductor"

    # El vínculo queda visible en el listado del dueño.
    r = client.get("/api/v1/users/me/vehicles", headers=headers)
    assert r.status_code == 200, r.text
    links = r.json()[0]["links"]
    assert {link["email"] for link in links} == {"veh-dueno@test.es", "veh-familiar@test.es"}


def test_link_vehicle_user_unknown_email_404(
    client: TestClient, db_session: Session,
) -> None:
    """Correo que no existe en el sistema → 404."""
    dueno = _seed_cliente(db_session, email="veh-dueno-404@test.es")
    vehiculo = _crear_vehiculo(db_session, "9999UNK")
    _vincular(db_session, vehiculo, dueno, VehicleRole.PROPIETARIO)
    headers = _login_headers(client, dueno.email, "cliente1234")

    r = client.post(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links",
        json={"email": "nadie@test.es", "role": "conductor"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_link_vehicle_user_duplicate_409(
    client: TestClient, db_session: Session,
) -> None:
    """Vincular dos veces a la misma persona → 409."""
    dueno = _seed_cliente(db_session, email="veh-dueno-dup@test.es")
    familiar = _seed_cliente(db_session, email="veh-familiar-dup@test.es")
    vehiculo = _crear_vehiculo(db_session, "1212DUP")
    _vincular(db_session, vehiculo, dueno, VehicleRole.PROPIETARIO)
    headers = _login_headers(client, dueno.email, "cliente1234")

    payload = {"email": "veh-familiar-dup@test.es", "role": "conductor"}
    r = client.post(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links", json=payload, headers=headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links", json=payload, headers=headers,
    )
    assert r.status_code == 409, r.text


def test_link_vehicle_user_as_conductor_403(
    client: TestClient, db_session: Session,
) -> None:
    """Un conductor no puede vincular a terceros."""
    cliente = _seed_cliente(db_session, email="veh-cond-link@test.es")
    _seed_cliente(db_session, email="veh-otro-link@test.es")
    vehiculo = _crear_vehiculo(db_session, "1313CON")
    _vincular(db_session, vehiculo, cliente, VehicleRole.CONDUCTOR)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.post(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links",
        json={"email": "veh-otro-link@test.es", "role": "conductor"},
        headers=headers,
    )
    assert r.status_code == 403, r.text


def test_unlink_vehicle_user(
    client: TestClient, db_session: Session,
) -> None:
    """El propietario desvincula a un conductor → 204."""
    dueno = _seed_cliente(db_session, email="veh-dueno-unlink@test.es")
    familiar = _seed_cliente(db_session, email="veh-familiar-unlink@test.es")
    vehiculo = _crear_vehiculo(db_session, "1414UNL")
    _vincular(db_session, vehiculo, dueno, VehicleRole.PROPIETARIO)
    _vincular(db_session, vehiculo, familiar, VehicleRole.CONDUCTOR)
    headers = _login_headers(client, dueno.email, "cliente1234")

    r = client.delete(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links/{familiar.id}",
        headers=headers,
    )
    assert r.status_code == 204, r.text

    db_session.expire_all()
    assert (
        db_session.query(VehicleUser)
        .filter(
            VehicleUser.vehicle_id == vehiculo.id,
            VehicleUser.user_id == familiar.id,
        )
        .count()
        == 0
    )


def test_unlink_last_owner_conflict(
    client: TestClient, db_session: Session,
) -> None:
    """No se puede dejar el vehículo sin propietario → 409."""
    dueno = _seed_cliente(db_session, email="veh-dueno-owner@test.es")
    vehiculo = _crear_vehiculo(db_session, "1515OWN")
    _vincular(db_session, vehiculo, dueno, VehicleRole.PROPIETARIO)
    headers = _login_headers(client, dueno.email, "cliente1234")

    r = client.delete(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links/{dueno.id}",
        headers=headers,
    )
    assert r.status_code == 409, r.text


def test_unlink_other_user_requires_owner(
    client: TestClient, db_session: Session,
) -> None:
    """Un conductor no puede desvincular a otras personas → 403."""
    cliente = _seed_cliente(db_session, email="veh-cond-unlink@test.es")
    otro = _seed_cliente(db_session, email="veh-otro-unlink@test.es")
    vehiculo = _crear_vehiculo(db_session, "1616UNL")
    _vincular(db_session, vehiculo, cliente, VehicleRole.CONDUCTOR)
    _vincular(db_session, vehiculo, otro, VehicleRole.CONDUCTOR)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.delete(
        f"/api/v1/users/me/vehicles/{vehiculo.id}/links/{otro.id}",
        headers=headers,
    )
    assert r.status_code == 403, r.text


# ── Tickets del usuario (scope por vehículo) ────────────────────────────


def test_list_my_tickets_only_own_vehicles(
    client: TestClient, db_session: Session,
) -> None:
    """Un conductor ve los tickets del vehículo que conduce, no los ajenos."""
    parking = _seed_parking(db_session, code="P-TIC")
    conductor = _seed_cliente(db_session, email="tik-conductor@test.es")
    otro = _seed_cliente(db_session, email="tik-otro@test.es")
    v_mio = _crear_vehiculo(db_session, "1717MIO")
    v_otro = _crear_vehiculo(db_session, "1818OTR")
    _vincular(db_session, v_mio, conductor, VehicleRole.CONDUCTOR)
    _vincular(db_session, v_otro, otro, VehicleRole.PROPIETARIO)

    t_mio = _crear_ticket(
        db_session, parking_id=parking.id, vehicle_id=v_mio.id, minutos=60,
    )
    t_otro = _crear_ticket(
        db_session, parking_id=parking.id, vehicle_id=v_otro.id, minutos=10,
    )

    headers = _login_headers(client, conductor.email, "cliente1234")
    r = client.get("/api/v1/users/me/tickets", headers=headers)
    assert r.status_code == 200, r.text
    ids = [t["id"] for t in r.json()]
    assert ids == [t_mio.id]
    assert t_otro.id not in ids


def test_list_my_tickets_empty_without_vehicles(
    client: TestClient, db_session: Session,
) -> None:
    """Sin vehículos vinculados no hay tickets."""
    cliente = _seed_cliente(db_session, email="tik-sin-veh@test.es")
    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/users/me/tickets", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []
