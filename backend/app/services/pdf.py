"""Generación del PDF de ticket cerrado (ReportLab).

Diseño minimalista: cabecera con marca, datos del ticket en una tabla,
total destacado, pie con LOPDGDD. Optimizado para imprimirse en A4
o tiquetera de 80 mm.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.ticket import Ticket
from app.models.vehicle import Vehicle


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d/%m/%Y %H:%M")


def render_ticket_pdf(ticket: Ticket, vehicle: Vehicle | None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Ticket solidAPP #{ticket.id}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=8)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=12,
                        textColor=colors.HexColor("#0f172a"))
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           textColor=colors.HexColor("#64748b"))

    story = []
    story.append(Paragraph("solidAPP · Ticket de parking", h1))
    story.append(Paragraph(
        f"<b>Ticket #{ticket.id}</b> &nbsp;&nbsp; Estado: <b>{ticket.status}</b>",
        h3,
    ))
    story.append(Spacer(1, 6 * mm))

    data = [
        ["Concepto", "Detalle"],
        ["ID Ticket", f"#{ticket.id}"],
        ["Sucursal", str(ticket.parking_id)],
        ["Plaza", str(ticket.parking_space_id) if ticket.parking_space_id else "—"],
        ["Vehículo (matrícula)", vehicle.plate if vehicle else "—"],
        ["Vehículo (marca/modelo)",
         " ".join(filter(None, [vehicle.brand if vehicle else "",
                                vehicle.model if vehicle else ""])) or "—"],
        ["Entrada", _fmt_dt(ticket.entry_at)],
        ["Salida", _fmt_dt(ticket.exit_at)],
        ["Método de pago", ticket.payment_method or "—"],
    ]
    table = Table(data, colWidths=[55 * mm, 100 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    totals = [
        ["Subtotal", _fmt_money(ticket.amount)],
        ["Descuento aplicado", f"-{_fmt_money(ticket.discount)}"],
        ["TOTAL", _fmt_money(ticket.total)],
    ]
    totals_table = Table(totals, colWidths=[120 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 1), (1, 1), colors.HexColor("#10b981")),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 12 * mm))

    story.append(Paragraph(
        "solidAPP · Datos protegidos bajo LOPDGDD (ES) y GDPR (UE). "
        "Conserve este justificante durante 1 año. Reclamaciones a "
        "<b>no-reply@solidapp.es</b>.",
        small,
    ))

    doc.build(story)
    return buf.getvalue()


def save_ticket_pdf(ticket: Ticket, vehicle: Vehicle | None,
                    base_dir: str = "/tmp/solidapp-tickets") -> str:
    """Escribe el PDF a disco y devuelve la ruta. El caller guarda la ruta en Ticket.pdf_path."""
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    pdf_path = Path(base_dir) / f"ticket-{ticket.id}.pdf"
    pdf_path.write_bytes(render_ticket_pdf(ticket, vehicle))
    return str(pdf_path)


__all__ = ["render_ticket_pdf", "save_ticket_pdf"]


# Evitar warnings de imports no usados al linter.
_ = Ticket
_ = Vehicle