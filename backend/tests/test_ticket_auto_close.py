"""T-124 (2026-10-24): el auto-cierre de las estancias sin salida.

DECISIÓN DE PRODUCTO (del usuario, 2026-10-24): auto-cierre a las 24 h
con el importe estimado y aviso al cliente.

Antes, un vehículo que entraba y cuya salida no se veía dejaba el
ticket **activo para siempre**, con importe 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.enums import TicketOrigin, TicketStatus
from app.models.pricing import Tariff
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle, VehicleUser
from app.services.ticket_auto_close import auto_cerrar_tickets_sin_salida
from tests._audit_helpers import _seed_cliente, _seed_parking


def _escenario(db: Session, *, con_tarifa: bool = True):
    parking = _seed_parking(db, code="P-AUTO")
    cliente = _seed_cliente(db, email="cliente@autocierre.es")
    vehiculo = Vehicle(plate="2222-BBB")
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    db.add(VehicleUser(user_id=cliente.id, vehicle_id=vehiculo.id, role="propietario"))
    if con_tarifa:
        db.add(
            Tariff(
                parking_id=parking.id,
                name="tarifa de test",
                price_per_hour=1.5,
                price_per_fraction=0.05,
                valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
    db.commit()
    return parking, cliente, vehiculo


def _ticket(db: Session, parking_id: int, vehicle_id: int, entrada: datetime) -> Ticket:
    ticket = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle_id,
        status=TicketStatus.ACTIVO,
        entry_at=entrada,
        origin=TicketOrigin.AUTOMATIC,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def test_un_ticket_sin_salida_se_cierra_a_las_24_horas(db_session: Session) -> None:
    """La regla: a las 24 h sin salida, el ticket se cierra con su importe."""
    parking, _cliente, vehiculo = _escenario(db_session)
    entrada = datetime.now(timezone.utc) - timedelta(hours=25)
    ticket = _ticket(db_session, parking.id, vehiculo.id, entrada)

    resultado = auto_cerrar_tickets_sin_salida(db_session)

    assert resultado["cerrados"] == 1
    assert resultado["omitidos"] == 0
    db_session.refresh(ticket)
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.exit_at is not None
    # La salida estimada es 24 h despues de la entrada.
    # OJO: en SQLite el datetime releido de la BD vuelve *naive*: hay que
    # normalizarlo antes de compararlo (el patron del repo).
    entrada_aware = entrada if entrada.tzinfo else entrada.replace(tzinfo=timezone.utc)
    esperado = entrada_aware + timedelta(hours=24)
    salida = ticket.exit_at
    if salida.tzinfo is None:
        salida = salida.replace(tzinfo=timezone.utc)
    assert abs((salida - esperado).total_seconds()) < 2
    # 24 h a 1,50 €/h = 36 € (sin descuento).
    assert ticket.amount is not None and abs(ticket.amount - 36.0) < 0.01
    assert ticket.total is not None and abs(ticket.total - 36.0) < 0.01


def test_un_ticket_reciente_no_se_toca(db_session: Session) -> None:
    """Un vehiculo que acaba de entrar no se cierra."""
    parking, _cliente, vehiculo = _escenario(db_session)
    entrada = datetime.now(timezone.utc) - timedelta(hours=2)
    ticket = _ticket(db_session, parking.id, vehiculo.id, entrada)

    resultado = auto_cerrar_tickets_sin_salida(db_session)

    assert resultado["cerrados"] == 0
    db_session.refresh(ticket)
    assert ticket.status == TicketStatus.ACTIVO
    assert ticket.exit_at is None


def test_sin_tarifa_el_ticket_se_queda_abierto(db_session: Session) -> None:
    """Sin tarifa no hay importe: se deja abierto y se avisa (no se inventa un precio)."""
    parking, _cliente, vehiculo = _escenario(db_session, con_tarifa=False)
    entrada = datetime.now(timezone.utc) - timedelta(hours=25)
    ticket = _ticket(db_session, parking.id, vehiculo.id, entrada)

    resultado = auto_cerrar_tickets_sin_salida(db_session)

    assert resultado["cerrados"] == 0
    assert resultado["omitidos"] == 1
    db_session.refresh(ticket)
    assert ticket.status == TicketStatus.ACTIVO
    assert ticket.exit_at is None


def test_el_aviso_lleva_el_correo_del_propietario(db_session: Session) -> None:
    """El aviso al cliente se prepara con su correo, su matricula y el importe."""
    parking, cliente, vehiculo = _escenario(db_session)
    entrada = datetime.now(timezone.utc) - timedelta(hours=25)
    _ticket(db_session, parking.id, vehiculo.id, entrada)

    resultado = auto_cerrar_tickets_sin_salida(db_session)

    assert resultado["cerrados"] == 1
    avisos = resultado["avisos"]
    assert len(avisos) == 1
    aviso = avisos[0]
    assert aviso["to_email"] == cliente.email
    assert aviso["plate"] == "2222-BBB"
    assert aviso["parking_name"] == parking.name
    assert abs(aviso["total"] - 36.0) < 0.01
    assert aviso["entry_at"] and aviso["exit_at"]


def test_un_ticket_ya_cerrado_no_se_pisa(db_session: Session) -> None:
    """Si otro cierre se ha adelantado, el auto-cierre no lo pisa."""
    parking, _cliente, vehiculo = _escenario(db_session)
    entrada = datetime.now(timezone.utc) - timedelta(hours=25)
    ticket = _ticket(db_session, parking.id, vehiculo.id, entrada)
    # La camara lo cerro antes (con su propio importe).
    ticket.status = TicketStatus.CERRADO
    ticket.exit_at = datetime.now(timezone.utc)
    ticket.total = 12.0
    db_session.commit()

    resultado = auto_cerrar_tickets_sin_salida(db_session)

    assert resultado["cerrados"] == 0
    db_session.refresh(ticket)
    assert ticket.total == 12.0
