"""T-159 (2026-10-24): la matricula se normaliza en los dos altos.

EL DEFECTO
----------
El T-122 normalizo la matricula **en la ingesta** (canonica: mayusculas y
solo alfanumericos, «1234ABC»). Pero el **alta del cliente**
(``POST /users/me/vehicles``) hacia ``strip().upper()``: «1234 ABC» se
guardaba como «1234 ABC» y el OCR de la camara canoniza a «1234ABC».

Como ``vehicles.plate`` es UNIQUE, **coexisten las dos filas**: la ingesta
crea un vehiculo nuevo («1234ABC») y cuelga ahi el ticket. El cliente se
queda con su vehiculo («1234 ABC») **sin ningun ticket para siempre** (la
purga de fantasmas no lo toca: tiene dueno), y ``/cliente/plazas`` y
``/cliente/tickets`` filtran por los ids de vehiculo del cliente => **el
cliente ve «Fuera» mientras esta dentro, y no ve ni el ticket ni el
importe**.

Y «1234 ABC» es justo lo que escribe una persona: el frontend tampoco
normaliza (el input es de texto libre).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle
from tests._audit_helpers import _login_headers, _seed_cliente


def test_el_alta_del_cliente_normaliza_la_matricula(
    client: TestClient, db_session: Session
) -> None:
    """«1234 ABC» se guarda como «1234ABC»: el mismo coche que ve el OCR."""
    cliente = _seed_cliente(db_session, email="cliente@t159.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    respuesta = client.post(
        "/api/v1/users/me/vehicles",
        headers=headers,
        json={"plate": "1234 ABC", "brand": "Seat"},
    )
    assert respuesta.status_code in (200, 201), respuesta.text

    filas = db_session.query(Vehicle).all()
    assert len(filas) == 1, f"deberia haber un solo vehiculo: {filas}"
    assert filas[0].plate == "1234ABC", (
        f"la matricula deberia quedar normalizada: {filas[0].plate!r}"
    )


def test_el_alta_del_cliente_no_crea_un_coche_duplicado(
    client: TestClient, db_session: Session
) -> None:
    """Dos escrituras de la misma matricula = el mismo vehiculo."""
    cliente = _seed_cliente(db_session, email="cliente2@t159.es")
    headers = _login_headers(client, cliente.email, "cliente1234")

    primera = client.post(
        "/api/v1/users/me/vehicles",
        headers=headers,
        json={"plate": "1234 ABC"},
    )
    assert primera.status_code in (200, 201), primera.text

    segunda = client.post(
        "/api/v1/users/me/vehicles",
        headers=headers,
        json={"plate": "1234abc"},
    )
    # O bien lo rechaza por duplicado, o bien devuelve el mismo vehiculo:
    # lo que **no** puede hacer es crear un segundo.
    assert db_session.query(Vehicle).count() == 1, (
        "la misma matricula escrita de dos formas ha creado dos vehiculos"
    )
