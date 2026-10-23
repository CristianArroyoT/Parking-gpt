"""Cierre de tickets: **una sola implementación**, y condicional.

POR QUÉ ESTE MÓDULO
-------------------
Hay **tres** caminos que cierran un ticket:

1. el cierre por cámara (`app/services/ingest_service.py`);
2. el cierre manual del servicio (`app/services/manual_tickets.py`);
3. el cierre manual del endpoint (`app/api/v1/tickets.py`).

Los tres comprobaban que el ticket estaba ``ACTIVO`` **al leerlo** y
luego hacian ``commit()`` **a ciegas**. Eso es un TOCTOU: entre la
lectura y el commit cabe otro cierre, y entonces **los dos tienen
éxito** y el último que commitea manda sobre el importe (T-121).

Además, cada camino tenía su propia copia de la lógica: tres sitios
donde arreglarlo y tres sitios donde se podía volver a romper.

QUÉ HACE
--------
``cerrar_ticket`` hace el cierre con un UPDATE **condicional**
(``WHERE id = ... AND status = 'activo'``): la comprobación y la
escritura son la misma sentencia, así que no hay ventana. Si otro
cierre se ha adelantado, el UPDATE no actualiza ninguna fila y se lanza
``TicketAlreadyClosedError``, que es una **carrera legítima** (no un
error): el que la gana es el que cierra.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import TicketOrigin, TicketStatus
from app.models.ticket import Ticket


class TicketAlreadyClosedError(Exception):
    """El ticket ya estaba cerrado cuando se iba a cerrar (T-121, T-130).

    No es un fallo: es una carrera legítima. El cierre por cámara y el
    cierre manual pueden coincidir, y sólo uno puede ganar.
    """

    def __init__(self, ticket_id: int) -> None:
        super().__init__(f"el ticket {ticket_id} ya estaba cerrado")
        self.ticket_id = ticket_id


def cerrar_ticket(
    db: Session,
    ticket: Ticket,
    *,
    exit_at: datetime,
    amount: float,
    discount: float,
    total: float,
    origin: TicketOrigin | None = None,
    payment_method: str | None = None,
) -> Ticket:
    """Cierra un ticket de forma atómica y devuelve el ticket actualizado.

    Lanza ``TicketAlreadyClosedError`` si el ticket ya no estaba activo
    (otro cierre se ha adelantado): en ese caso **no** se escribe nada.
    """
    # Las claves son **columnas** (no cadenas): asi el tipo del UPDATE es
    # el que espera SQLAlchemy (y no hay forma de escribir una columna
    # que no exista).
    campos: dict[Any, Any] = {
        Ticket.exit_at: exit_at,
        Ticket.amount: amount,
        Ticket.discount: discount,
        Ticket.total: total,
        Ticket.status: TicketStatus.CERRADO,
    }
    if origin is not None:
        campos[Ticket.origin] = origin
    if payment_method is not None:
        campos[Ticket.payment_method] = payment_method

    actualizados = (
        db.query(Ticket)
        .filter(Ticket.id == ticket.id, Ticket.status == TicketStatus.ACTIVO)
        .update(campos, synchronize_session=False)
    )
    if not actualizados:
        # Otro cierre se ha adelantado: no se toca el ticket.
        db.rollback()
        raise TicketAlreadyClosedError(ticket.id)
    db.commit()
    db.refresh(ticket)
    return ticket
