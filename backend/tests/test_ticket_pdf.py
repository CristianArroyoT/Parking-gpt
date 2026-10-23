"""El PDF del ticket se sirve por la API y la ruta interna no sale (T-97).

POR QUÉ existe este fichero: la API devolvía ``pdf_path``, que era la
ruta del PDF **en el disco del servidor** (``/tmp/solidapp-tickets/
ticket-1.pdf``). Eso tenía dos consecuencias:

1. el enlace del frontend («Descargar PDF») **daba 404**: ese fichero
   vive en el contenedor del backend y no lo servía nadie;
2. la respuesta de la API enseñaba la estructura de ficheros del
   servidor (dónde están los temporales, cómo se llaman).

Ahora el PDF se pide a ``GET /tickets/{id}/pdf``, que lo **genera al
vuelo** y lo sirve con el mismo scope que el detalle del ticket: un
cliente solo descarga los PDF de sus vehículos.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import TicketStatus, UserRole
from app.models.parking import Parking
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser


def _sembrar(db: Session) -> dict[str, object]:
    """Un parking, dos vehiculos y sus usuarios."""
    admin = User(
        email="admin-pdf@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    cliente = User(
        email="cliente-pdf@test.es", full_name="Cliente",
        role=UserRole.CLIENTE, hashed_password=hash_password("cliente12345"),
    )
    otro = User(
        email="otro-pdf@test.es", full_name="Otro",
        role=UserRole.CLIENTE, hashed_password=hash_password("otro12345"),
    )
    parking = Parking(code="P-PDF", name="PDF", address="x", city="y")
    db.add_all([admin, cliente, otro, parking])
    db.flush()
    vehiculo = Vehicle(plate="1111-AAA")
    otro_vehiculo = Vehicle(plate="2222-BBB")
    db.add_all([vehiculo, otro_vehiculo])
    db.flush()
    db.add(VehicleUser(user_id=cliente.id, vehicle_id=vehiculo.id, role="propietario"))
    db.add(VehicleUser(user_id=otro.id, vehicle_id=otro_vehiculo.id, role="propietario"))
    entrada = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    ticket = Ticket(
        parking_id=parking.id, vehicle_id=vehiculo.id,
        status=TicketStatus.ACTIVO, entry_at=entrada,
    )
    ticket_cerrado = Ticket(
        parking_id=parking.id, vehicle_id=vehiculo.id,
        status=TicketStatus.CERRADO, entry_at=entrada,
        exit_at=entrada + timedelta(hours=2), amount=5.0, total=5.0,
    )
    db.add_all([ticket, ticket_cerrado])
    db.commit()
    return {
        "admin": admin, "cliente": cliente, "otro": otro,
        "ticket": ticket, "ticket_cerrado": ticket_cerrado,
    }


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_el_ticket_no_expone_la_ruta_del_pdf(
    client: TestClient, db_session: Session,
) -> None:
    """La respuesta del ticket no lleva la ruta del PDF en el servidor."""
    datos = _sembrar(db_session)
    headers = _login(client, "admin-pdf@test.es", "admin12345")

    ticket_id = datos["ticket"].id
    r = client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "pdf_path" not in cuerpo, (
        "la API no debe devolver la ruta del PDF en el disco del servidor"
    )
    assert cuerpo["pdf_available"] is False, "un ticket activo no tiene PDF"


def test_el_panel_del_cliente_no_expone_la_ruta(
    client: TestClient, db_session: Session,
) -> None:
    """El listado del panel del cliente tampoco la lleva."""
    _sembrar(db_session)
    headers = _login(client, "cliente-pdf@test.es", "cliente12345")

    r = client.get("/api/v1/cliente/tickets", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json(), "el cliente debe ver su ticket"
    for ticket in r.json():
        assert "pdf_path" not in ticket
        assert "pdf_available" in ticket


def test_el_pdf_se_sirve_como_pdf(
    client: TestClient, db_session: Session,
) -> None:
    """``GET /tickets/{id}/pdf`` devuelve el PDF generado al vuelo."""
    datos = _sembrar(db_session)
    headers = _login(client, "admin-pdf@test.es", "admin12345")

    ticket_id = datos["ticket_cerrado"].id
    r = client.get(f"/api/v1/tickets/{ticket_id}/pdf", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.content.startswith(b"%PDF"), "el cuerpo debe ser un PDF"
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_un_cliente_no_puede_descargar_el_pdf_de_otro(
    client: TestClient, db_session: Session,
) -> None:
    """El PDF de un ticket ajeno da 404 (no se revela ni que existe)."""
    datos = _sembrar(db_session)
    headers = _login(client, "otro-pdf@test.es", "otro12345")

    ticket_id = datos["ticket_cerrado"].id
    r = client.get(f"/api/v1/tickets/{ticket_id}/pdf", headers=headers)
    assert r.status_code == 404, r.text


def test_el_cliente_descarga_el_pdf_de_su_ticket(
    client: TestClient, db_session: Session,
) -> None:
    """Su propio ticket sí se descarga (el botón del panel funciona)."""
    datos = _sembrar(db_session)
    headers = _login(client, "cliente-pdf@test.es", "cliente12345")

    ticket_id = datos["ticket_cerrado"].id
    r = client.get(f"/api/v1/tickets/{ticket_id}/pdf", headers=headers)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
