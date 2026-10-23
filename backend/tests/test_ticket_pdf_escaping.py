"""T-106: el PDF del ticket aguanta el texto que rompe un Paragraph (T-106).

POR QUÉ existe este fichero: en la auditoría se sospechó que el PDF del
ticket no escapaba el texto del usuario y que eso lo rompía. **Medido el
2026-10-23: no es un defecto**:

- el PDF del ticket pone los datos del vehiculo en **celdas de tabla**
  (cadenas de texto), y reportlab no las interpreta como XML;
- el PDF de informes ya escapa todo lo que mete en ``Paragraph``
  (``escape(...)``).

O sea: una matricula como ``1234&<>'"ABC`` genera el PDF sin problema
(medido: 2701 bytes, empieza por ``%PDF-``).

Este test **fija ese comportamiento**: si alguien metiera un dato del
usuario dentro de un ``Paragraph`` sin escapar, este test se caeria
((reportlab parsea el XML y el PDF no se genera).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.services.pdf import render_ticket_pdf


def test_el_pdf_aguanta_texto_que_rompe_xml() -> None:
    """Matricula y marca con ``& < > ' "`` no rompen el PDF."""
    ticket = Ticket(
        id=999,
        parking_id=1,
        vehicle_id=1,
        status=TicketStatus.CERRADO,
        entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
        amount=5.0, total=5.0, payment_method="tarjeta",
    )
    vehiculo = Vehicle(plate="1234&<>'\"ABC", brand='Peugeot "307" <b>', model="")

    pdf = render_ticket_pdf(ticket, vehiculo)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000
