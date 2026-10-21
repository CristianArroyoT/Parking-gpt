"""Generación del PDF de ticket cerrado (ReportLab).

Diseño minimalista: cabecera con marca, datos del ticket en una tabla,
total destacado, pie con LOPDGDD. Optimizado para imprimirse en A4
o tiquetera de 80 mm.

Desde T-16 (2026-10-21) este módulo también renderiza los **informes**
(ingresos, ocupación, tickets, alertas y márgenes) con la misma paleta
``park`` del producto, de modo que el ticket y los informes descargables
comparten identidad visual.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.parking import Parking
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle

#: Paleta ``park`` del producto (fuente: ``frontend/tailwind.config.js``).
#:
#: Se replica aquí para que el PDF use los mismos colores que la interfaz
#: web sin depender del frontend en tiempo de build.
PALETA_PARK: dict[str, str] = {
    "libre": "#10b981",
    "ocupado": "#f43f5e",
    "alerta": "#f59e0b",
    "inactivo": "#64748b",
    "marca": "#0f172a",
    "acento": "#2563eb",
}

#: Tono de fondo de las filas alternas del PDF.
_FILA_ALTERNA = "#f8fafc"
#: Color de las líneas de la tabla.
_LINEA = "#cbd5e1"
#: Longitud máxima de una celda antes de recortar (evita celdas que no
#: caben en una página y rompen el layout de ReportLab).
_MAX_CELDA = 300



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


# ─────────────────────────── Informes (T-16) ───────────────────────────


def _texto_celda(valor: object) -> str:
    """Convierte un valor de celda en texto seguro para un ``Paragraph``.

    Recorta los textos muy largos (p. ej. el mensaje de una alerta): un
    ``Paragraph`` más alto que la página hace fallar el layout de ReportLab.
    """
    texto = "" if valor is None else str(valor)
    if len(texto) > _MAX_CELDA:
        texto = texto[: _MAX_CELDA - 1] + "…"
    return escape(texto)


def _anchos_columna(
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    disponible: float,
) -> list[float]:
    """Reparte el ancho útil entre las columnas según la longitud del texto.

    Las columnas de texto largo (mensajes, matrículas) reciben más espacio y
    todas conservan un mínimo legible.
    """
    n = len(columns)
    if n == 0:
        return []
    pesos: list[float] = []
    for i, columna in enumerate(columns):
        largo = len(columna)
        for fila in rows:
            if i < len(fila):
                largo = max(largo, min(len(str(fila[i])), 40))
        pesos.append(float(max(largo, 6)))
    total = sum(pesos) or 1.0
    anchos = [disponible * p / total for p in pesos]

    minimo = min(disponible / n, 40.0)
    deficit = sum(minimo - a for a in anchos if a < minimo)
    if deficit > 0:
        sobrantes = [i for i, a in enumerate(anchos) if a > minimo]
        sobra = sum(anchos[i] - minimo for i in sobrantes)
        if sobra > 0:
            for i in sobrantes:
                anchos[i] -= (anchos[i] - minimo) * (deficit / sobra)
        for i, a in enumerate(anchos):
            if a < minimo:
                anchos[i] = minimo
    return anchos


def _es_columna_numerica(columna: str) -> bool:
    """Las columnas ``*_eur`` y ``*_min`` se alinean a la derecha."""
    return columna.endswith("_eur") or columna.endswith("_min")


def render_report_pdf(
    *,
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    summary: Sequence[tuple[str, str]] = (),
    parking: Optional[Parking] = None,
    window: Optional[tuple[datetime, datetime]] = None,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """Renderiza un informe tabular en PDF (A4 apaisado).

    Args:
        title: título del informe (se muestra en la banda de cabecera).
        columns: cabecera de la tabla de detalle.
        rows: filas de la tabla de detalle.
        summary: pares (etiqueta, valor) del bloque de resumen.
        parking: sucursal del informe; se pintan sus datos en la cabecera.
        window: ventana temporal ``(desde, hasta)`` del informe.
        generated_at: instante de generación (por defecto, ahora).

    Returns:
        Los bytes del PDF (empiezan por ``%PDF``).
    """
    buf = BytesIO()
    margen = 15 * mm
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=margen,
        rightMargin=margen,
        topMargin=margen,
        bottomMargin=margen,
        title=f"solidAPP · {title}",
        author="solidAPP",
    )
    disponible = landscape(A4)[0] - 2 * margen

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "reportH1", parent=styles["Heading1"], fontSize=16, leading=19,
        textColor=colors.white, spaceAfter=0,
    )
    sub = ParagraphStyle(
        "reportSub", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor(_LINEA),
    )
    h2 = ParagraphStyle(
        "reportH2", parent=styles["Heading2"], fontSize=11, leading=13,
        textColor=colors.HexColor(PALETA_PARK["acento"]),
        spaceBefore=8, spaceAfter=4,
    )
    celda = ParagraphStyle(
        "reportCelda", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.HexColor(PALETA_PARK["marca"]),
    )
    celda_der = ParagraphStyle(
        "reportCeldaDer", parent=celda, alignment=TA_RIGHT,
    )
    cabecera = ParagraphStyle(
        "reportCabecera", parent=styles["Normal"], fontSize=8, leading=10,
        fontName="Helvetica-Bold", textColor=colors.white,
    )
    etiqueta = ParagraphStyle(
        "reportEtiqueta", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor(PALETA_PARK["inactivo"]),
    )
    valor = ParagraphStyle(
        "reportValor", parent=styles["Normal"], fontSize=9.5,
        fontName="Helvetica-Bold", textColor=colors.HexColor(PALETA_PARK["marca"]),
    )
    pie = ParagraphStyle(
        "reportPie", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor(PALETA_PARK["inactivo"]),
    )

    story = []

    # ── Cabecera: marca + datos de la sucursal y del periodo ──────────
    datos_sucursal = "Sucursal: —"
    if parking is not None:
        datos_sucursal = (
            f"Sucursal: {parking.code} · {parking.name} · "
            f"{parking.address}, {parking.city}"
        )
    periodo = ""
    if window is not None:
        desde, hasta = window
        periodo = f" · Periodo: {desde:%Y-%m-%d %H:%M} → {hasta:%Y-%m-%d %H:%M}"
    generado = generated_at.strftime("%Y-%m-%d %H:%M") if generated_at else "—"

    cabecera_tabla = Table(
        [
            [Paragraph(f"solidAPP · {escape(title)}", h1)],
            [Paragraph(
                f"{escape(datos_sucursal)}{escape(periodo)} · Generado: {escape(generado)}",
                sub,
            )],
        ],
        colWidths=[disponible],
        hAlign="LEFT",
    )
    cabecera_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PALETA_PARK["marca"])),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story.append(cabecera_tabla)
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor(PALETA_PARK["acento"]),
        spaceBefore=4, spaceAfter=2,
    ))

    # ── Resumen ───────────────────────────────────────────────────────
    if summary:
        story.append(Paragraph("Resumen", h2))
        datos_resumen = [
            [Paragraph(escape(str(k)), etiqueta), Paragraph(escape(str(v)), valor)]
            for k, v in summary
        ]
        tabla_resumen = Table(
            datos_resumen,
            colWidths=[disponible * 0.28, disponible * 0.72],
            hAlign="LEFT",
        )
        tabla_resumen.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor(_LINEA)),
        ]))
        story.append(tabla_resumen)

    # ── Detalle ───────────────────────────────────────────────────────
    story.append(Paragraph("Detalle", h2))
    if not rows:
        story.append(Paragraph(
            "Sin datos en el periodo seleccionado.", pie,
        ))
    else:
        cabecera_fila = [
            Paragraph(escape(str(c)), cabecera) for c in columns
        ]
        cuerpo = [
            [
                Paragraph(
                    _texto_celda(fila[i] if i < len(fila) else ""),
                    celda_der if _es_columna_numerica(str(columns[i])) else celda,
                )
                for i in range(len(columns))
            ]
            for fila in rows
        ]
        anchos = _anchos_columna(columns, rows, disponible)
        tabla = Table(
            [cabecera_fila] + cuerpo,
            colWidths=anchos,
            repeatRows=1,
            hAlign="LEFT",
        )
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PALETA_PARK["marca"])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(_LINEA)),
        ]
        for indice in range(len(cuerpo)):
            if indice % 2 == 0:
                estilo.append(("BACKGROUND", (0, indice + 1), (-1, indice + 1),
                               colors.HexColor(_FILA_ALTERNA)))
        tabla.setStyle(TableStyle(estilo))
        story.append(tabla)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "solidAPP · Documento generado automáticamente. Datos protegidos bajo "
        "LOPDGDD (ES) y GDPR (UE). Reclamaciones a <b>no-reply@solidapp.es</b>.",
        pie,
    ))

    doc.build(story)
    return buf.getvalue()


__all__ = [
    "render_ticket_pdf",
    "save_ticket_pdf",
    "render_report_pdf",
    "PALETA_PARK",
]


# Evitar warnings de imports no usados al linter.
_ = Ticket
_ = Vehicle