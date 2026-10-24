"""Auto-cierre de las estancias cuya salida no se ha visto (T-124).

DECISIÓN DE PRODUCTO (2026-10-24, del usuario)
---------------------------------------------
Un vehículo entra y no se ve su salida. Antes el ticket se quedaba
**activo para siempre**, con importe 0: los informes de ocupación no
cuadraban y esa estancia no se cobraba nunca.

Decidido: **auto-cierre a las 24 h** con el **importe estimado** (la
tarifa vigente, calculada como si la salida fuese a las 24 h de la
entrada) y **aviso al cliente por correo**.

Por qué 24 h y no más: es el plazo que da tiempo a que la cámara vuelva
a funcionar (una cámara caída se recupera en minutos u horas) sin dejar
una estancia abierta indefinidamente.

OJO, lo que este servicio NO hace:
- **no cobra**: el ticket se cierra con su importe, pero el cobro sigue
  siendo el que el producto tenga definido (hoy es contable, D2);
- **no penaliza** por exceso de tiempo: el importe es el de la estancia,
  no una multa por dejar el coche;
- **no toca** los tickets con salida detectada: sólo los que siguen
  abiertos.

Usa la **única** implementación de cierre del repo
(``app.services.ticket_closing.cerrar_ticket``), que es condicional
(``UPDATE ... WHERE status='activo'``): si la cámara se adelanta y cierra
el ticket, el auto-cierre no pisa nada.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.parking import Parking
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.services.pricing import PricingError, calculate_ticket_total
from app.services.ticket_closing import TicketAlreadyClosedError, cerrar_ticket

log = logging.getLogger(__name__)

#: Horas de margen antes de cerrar un ticket sin salida.
HORAS_POR_DEFECTO = 24

#: Cuantos tickets se cierran de una vez (para no bloquear al worker).
LOTE = 500


def _aware(momento: datetime) -> datetime:
    """Un ``datetime`` con zona (SQLite devuelve los naive)."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _email_del_cliente(db: Session, vehicle_id: int) -> str | None:
    """El correo del propietario del vehículo (o del primer usuario)."""
    vinculo = (
        db.query(VehicleUser)
        .filter(VehicleUser.vehicle_id == vehicle_id)
        .order_by(VehicleUser.id)
        .first()
    )
    if vinculo is None:
        return None
    usuario = db.get(User, vinculo.user_id)
    if usuario is None:
        return None
    return usuario.email


def auto_cerrar_tickets_sin_salida(
    db: Session,
    *,
    horas: int = HORAS_POR_DEFECTO,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Cierra las estancias sin salida detectada y devuelve el resumen.

    Devuelve ``{"cerrados": n, "omitidos": m, "importe": x, "avisos": [...]}``.
    Los ``avisos`` son los datos que necesita el correo al cliente.
    """
    momento = _aware(ahora) if ahora is not None else datetime.now(timezone.utc)
    corte = momento - timedelta(hours=horas)

    # OJO: el filtro de fecha se hace **en Python**, no en SQL. Un
    # ``DateTime(timezone=True)`` vuelve *naive* en SQLite, y comparar en
    # SQL un ``datetime`` con zona contra una columna naive no es fiable
    # (es el mismo problema que el AGENTS.md repite). El número de
    # tickets abiertos sin salida está acotado por el número de vehículos
    # en el parking, así que traerlos no es un problema.
    candidatos = (
        db.query(Ticket)
        .filter(Ticket.status == TicketStatus.ACTIVO, Ticket.exit_at.is_(None))
        .all()
    )

    cerrados = 0
    omitidos = 0
    importe_total = 0.0
    avisos: list[dict[str, Any]] = []

    for ticket in candidatos:
        entrada = _aware(ticket.entry_at)
        if entrada > corte:
            continue
        salida_estimada = entrada + timedelta(hours=horas)

        try:
            total = calculate_ticket_total(
                db,
                parking_id=ticket.parking_id,
                vehicle_id=ticket.vehicle_id,
                entry_at=entrada,
                exit_at=salida_estimada,
            )
        except PricingError as exc:
            # Sin tarifa no hay importe: el ticket se deja abierto y se
            # avisa (cerrarlo a 0 sería inventarse un precio).
            omitidos += 1
            log.warning(
                "auto-cierre: no se puede calcular el importe del ticket %s "
                "(%s): se deja abierto",
                ticket.id,
                exc,
            )
            continue

        try:
            cerrar_ticket(
                db,
                ticket,
                exit_at=salida_estimada,
                amount=total.amount,
                discount=total.discount,
                total=total.total,
            )
        except TicketAlreadyClosedError:
            # La cámara (o el personal) se ha adelantado: no se pisa nada.
            continue

        cerrados += 1
        importe_total += total.total

        vehiculo = db.get(Vehicle, ticket.vehicle_id)
        plate = vehiculo.plate if vehiculo is not None else ""
        sucursal = db.get(Parking, ticket.parking_id)
        parking_name = sucursal.name if sucursal is not None else ""
        destinatario = _email_del_cliente(db, ticket.vehicle_id)
        if destinatario:
            avisos.append(
                {
                    "to_email": destinatario,
                    "plate": plate,
                    "parking_name": parking_name,
                    "ticket_id": ticket.id,
                    "entry_at": entrada.isoformat(),
                    "exit_at": salida_estimada.isoformat(),
                    "amount": total.amount,
                    "discount": total.discount,
                    "total": total.total,
                }
            )
        else:
            log.info(
                "auto-cierre: ticket %s cerrado, pero el vehiculo %s no tiene "
                "propietario con correo: no hay aviso que enviar",
                ticket.id,
                plate,
            )

    db.commit()

    log.info(
        "auto-cierre de estancias: cerrados=%s omitidos=%s importe=%s",
        cerrados,
        omitidos,
        round(importe_total, 2),
    )
    return {
        "cerrados": cerrados,
        "omitidos": omitidos,
        "importe": round(importe_total, 2),
        "horas": horas,
        "avisos": avisos,
    }
