"""Dos cierres del mismo ticket a la vez: el importe no puede depender del orden (T-121).

El defecto era un **TOCTOU**: el cierre comprobaba que el ticket estaba
``ACTIVO`` **al leerlo** y luego hacia ``commit()`` a ciegas. Si otro
cierre (el de la cámara de salida, o el de otro operador) se colaba
entre la lectura y el commit, **los dos tenían éxito** y el último que
commiteaba mandaba sobre el importe.

Aquí la intercalación se fuerza de forma determinista: el test hace que
la *otra* sesión cierre el ticket justo en el punto en que el endpoint
está calculando el importe (después de leer el estado, antes de
escribir).

Con el arreglo (UPDATE condicional ``WHERE status = 'activo'``), el
segundo cierre recibe **409** y el ticket conserva el importe del
primer cierre.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.user import ParkingMembership
from app.models.vehicle import Vehicle
from tests._audit_helpers import (
    _login_headers,
    _seed_gestor,
    _seed_parking,
)


def _tarifa(db: Session, parking_id: int) -> None:
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


def _escenario(db: Session):
    parking = _seed_parking(db, code="P-CARRERA")
    gestor = _seed_gestor(db, email="gestor@carrera.es")
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking.id))
    db.commit()
    # OJO: sin guiones ni espacios: la salida manual **normaliza** la
    # matricula (quita lo que no sea alfanumerico), asi que "2222-CARR" no
    # casaria con el vehiculo.
    vehiculo = Vehicle(plate="2222CARR")
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    _tarifa(db, parking.id)
    return parking, gestor, vehiculo


def test_dos_cierres_a_la_vez_solo_uno_puede_cobrar(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    parking, gestor, vehiculo = _escenario(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")

    entrada = datetime.now(timezone.utc) - timedelta(days=10)
    abierto = client.post(
        "/api/v1/tickets",
        headers=headers,
        json={
            "parking_id": parking.id,
            "vehicle_id": vehiculo.id,
            "entry_at": entrada.isoformat(),
        },
    )
    assert abierto.status_code == 201, abierto.text
    ticket_id = abierto.json()["id"]

    # La otra sesion: simula el cierre por camara (o de otro operador).
    # Se dispara en el punto exacto en que el endpoint esta calculando
    # el importe: DESPUES de leer el estado y ANTES de escribir.
    cerrada = {"hecho": False}

    def _cerrar_desde_otra_sesion(*args, **kwargs):
        if not cerrada["hecho"]:
            cerrada["hecho"] = True
            # OJO: la sesion tiene que ir contra **la misma base de datos**
            # que la del test. ``SessionLocal()`` apunta a la configurada
            # en el entorno (la de la app), no a la de test.
            otra = sessionmaker(bind=db_session.get_bind())()
            try:
                otra.query(Ticket).filter(Ticket.id == ticket_id).update(
                    {
                        "exit_at": datetime.now(timezone.utc),
                        "amount": 99.0,
                        "discount": 0.0,
                        "total": 99.0,
                        "status": TicketStatus.CERRADO,
                    },
                    synchronize_session=False,
                )
                otra.commit()
            finally:
                otra.close()
        # El calculo real del endpoint.
        from app.services.pricing import calculate_ticket_total as real

        return real(*args, **kwargs)

    monkeypatch.setattr(
        "app.api.v1.tickets.calculate_ticket_total", _cerrar_desde_otra_sesion
    )

    r = client.post(
        f"/api/v1/tickets/{ticket_id}/close",
        headers=headers,
        json={"exit_at": datetime.now(timezone.utc).isoformat()},
    )

    assert cerrada["hecho"], "el test no llego al punto de intercalacion"
    assert r.status_code == 409, (
        f"los dos cierres tuvieron exito (el ultimo que commite gana): {r.text}"
    )

    db_session.expire_all()
    ticket = db_session.get(Ticket, ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.total == 99.0, (
        f"el importe lo escribio el cierre que perdio: {ticket.total}"
    )


def test_la_salida_manual_no_pisa_el_cierre_de_otro(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    """T-130: la salida manual usa el mismo cierre condicional.

    El servicio de tickets manuales (``app/services/manual_tickets.py``)
    tenia su propia copia del patron "comprueba al leer + commit a
    ciegas": con un cierre a la vez (la camara de salida y el operador),
    los dos podian tener exito y el ultimo que commitea mandaba sobre el
    importe.
    """
    parking, gestor, vehiculo = _escenario(db_session)
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

    cerrado = {"hecho": False}

    def _otro_cierre(*args, **kwargs):
        if not cerrado["hecho"]:
            cerrado["hecho"] = True
            otra = sessionmaker(bind=db_session.get_bind())()
            try:
                otra.query(Ticket).filter(Ticket.id == ticket_id).update(
                    {
                        "exit_at": datetime.now(timezone.utc),
                        "amount": 99.0,
                        "discount": 0.0,
                        "total": 99.0,
                        "status": TicketStatus.CERRADO,
                    },
                    synchronize_session=False,
                )
                otra.commit()
            finally:
                otra.close()
        from app.services.pricing import calculate_ticket_total as real

        return real(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.manual_tickets.calculate_ticket_total", _otro_cierre
    )

    r = client.post(
        "/api/v1/tickets/manual",
        headers=headers_gestor,
        json={
            "plate": vehiculo.plate,
            "parking_id": parking.id,
            "direction": "exit",
            "reason": "ocr_failed",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert cerrado["hecho"], "el test no llego al punto de intercalacion"
    assert r.status_code == 409, (
        f"la salida manual escribio su importe encima del del otro cierre: {r.text}"
    )

    db_session.expire_all()
    ticket = db_session.get(Ticket, ticket_id)
    assert ticket is not None
    assert ticket.total == 99.0, (
        f"el importe lo escribio el cierre que perdio: {ticket.total}"
    )
