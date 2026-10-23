"""Endpoints de reporte operativo: márgenes, ingresos, ocupación, tickets y alertas.

Rutas del router (``/admin/reports``):

===========================  ==========================================
``GET /margins``             → JSON (Sprint P1, histórico).
``GET /margins.csv``         → CSV descargable (Sprint P1, histórico).
``GET /margins.pdf``         → PDF descargable (T-16).
``GET /{informe}.csv``       → CSV descargable (T-16).
``GET /{informe}.pdf``       → PDF descargable (T-16).
===========================  ==========================================

con ``informe`` ∈ ``ingresos | ocupacion | tickets | alertas | margins``.

Filtros (idénticos en todas las rutas): ``parking_id`` (obligatorio),
``from`` y ``to`` (ventana temporal obligatoria, ISO 8601).

RBAC: admin ve cualquier sucursal. Gestor sólo la suya (validación manual
contra ``ParkingMembership`` para poder devolver el id validado en lugar de
``User``). Operador y cliente reciben 403.

Naming de las rutas (decisión documentada)
------------------------------------------
El criterio de aceptación del plan maestro escribe ``/admin/reports/{informe}.pdf``.
**No** se implementa una ruta genérica ``/{informe}.pdf`` porque FastAPI evalúa
las rutas **en orden de declaración** y el path param ``[^/]+`` también
encaja con ``"margins.csv"``: una genérica ``/{informe}.csv`` declarada
después de la literal ``/margins.csv`` nunca llegaría a ejecutarse, y
declarada antes la sombrearía. Además el resto del router ya usa rutas
literales (``/margins``, ``/margins.csv``), que documentan el contrato real
en el OpenAPI.

Por eso los exportes se declaran como **rutas literales** (``/ingresos.csv``,
``/ingresos.pdf``, ``/ocupacion.csv``, ...). El resultado observable es
idéntico al del criterio (``GET /admin/reports/ingresos.pdf``) y no hay
ambigüedad de routing.

Convención de los exportes
--------------------------
- CSV con cabecera y separador ``,`` (convención del repo: el CSV histórico
  de márgenes usa el ``csv.writer`` por defecto). Parseable con
  ``csv.DictReader``.
- PDF con la paleta ``park`` del producto y los datos de la sucursal
  (generador: ``app.services.pdf.render_report_pdf``).
- ``Content-Disposition: attachment; filename="..."`` en ambos formatos.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.services.endpoint_rate_limit import enforce_endpoint_rate_limit
from app.models.parking import Parking
from app.models.user import ParkingMembership, User
from app.schemas.reports import MarginReportRead
from app.services.cost import compute_margin
from app.services.pdf import render_report_pdf
from app.services.reports import (
    FILE_BASENAMES,
    InformeDemasiadoGrandeError,
    REPORT_BUILDERS,
    escapar_celda_csv,
    render_report_csv,
    to_utc,
)

#: Tope de dias que puede abarcar un informe (T-100).
MAX_DIAS_VENTANA = 366


def _limite_de_informes(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """T-100: los informes son caros (BD + PDF + CSV): se limitan por actor.

    Como **dependencia del router**, aplica a todos sus endpoints sin
    repetir la llamada once veces (el mismo patron que el rate-limit
    unico de T-69: una sola implementacion, no once copias).
    """
    enforce_endpoint_rate_limit(request, db, scope="informe", actor_id=user.id)


router = APIRouter(
    prefix="/admin/reports",
    tags=["admin-reports"],
    dependencies=[Depends(get_current_user), Depends(_limite_de_informes)],
)

#: Roles con acceso a los informes: admin (cualquier sucursal) o gestor
#: (sólo las suyas). Operador y cliente quedan fuera con 403.
_ROLES_INFORME = {"admin", "gestor"}


def _resolve_parking_id(
    requested: int, user: User, db: Session,
) -> int:
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    if role_value == "admin":
        return requested
    membership = (
        db.query(ParkingMembership)
        .filter(
            ParkingMembership.user_id == user.id,
            ParkingMembership.parking_id == requested,
        )
        .one_or_none()
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="No tiene acceso a esta sucursal",
        )
    return requested


def _autorizar_informe(user: User, db: Session, parking_id: int) -> None:
    """Control de acceso de los informes (admin o gestor de esa sucursal).

    Es el mismo filtro por rol que usa ``/admin/reports/margins``: primero
    se comprueba el rol y después la pertenencia a la sucursal, de modo que
    un cliente sin acceso recibe 403 (y no 404) aunque la sucursal exista.
    """
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_value not in _ROLES_INFORME:
        raise HTTPException(
            status_code=403,
            detail="No tiene permisos para consultar informes",
        )
    _resolve_parking_id(parking_id, user, db)


def _parse_window(
    from_: Optional[datetime], to: Optional[datetime],
) -> tuple[datetime, datetime]:
    if not from_ or not to:
        raise HTTPException(
            status_code=422,
            detail="Parámetros 'from' y 'to' obligatorios (ISO 8601)",
        )
    # La comparación se hace sobre los valores normalizados a UTC: comparar
    # un datetime naive con uno aware lanza TypeError (500). Los valores
    # devueltos NO se normalizan aquí para no alterar el JSON de /margins.
    if to_utc(to) < to_utc(from_):
        raise HTTPException(
            status_code=422,
            detail="'to' debe ser posterior a 'from'",
        )
    # T-100: la ventana no puede ser arbitrariamente larga. Un informe de
    # 30 años carga (y dibuja en el PDF) toda la historia de la sucursal:
    # con 50.000 tickets el PDF multiplica por doce el numero de objetos y
    # el proceso se queda sin memoria. Y si se queda sin memoria, se cae
    # la API **entera**, que es lo que hay que evitar.
    if (to_utc(to) - to_utc(from_)).days > MAX_DIAS_VENTANA:
        raise HTTPException(
            status_code=422,
            detail=(
                f"el rango pedido es de mas de {MAX_DIAS_VENTANA} dias: "
                "acota las fechas del informe"
            ),
        )
    return from_, to


def _ventana(
    parking_id: int,
    from_: Optional[datetime],
    to: Optional[datetime],
    user: User,
    db: Session,
) -> tuple[int, datetime, datetime]:
    """Valida el scope y devuelve ``(parking_id, desde, hasta)`` en UTC."""
    _autorizar_informe(user, db, parking_id)
    f, t = _parse_window(from_, to)
    return parking_id, to_utc(f), to_utc(t)


def _nombre_fichero(
    informe: str, parking_id: int, desde: datetime, hasta: datetime,
) -> str:
    """Nombre del fichero exportado (sin extensión)."""
    base = FILE_BASENAMES.get(informe, informe)
    return f"{base}-{parking_id}-{desde:%Y-%m-%d}-{hasta:%Y-%m-%d}"


def _csv_response(
    informe: str,
    parking_id: int,
    from_: Optional[datetime],
    to: Optional[datetime],
    user: User,
    db: Session,
) -> Response:
    """Genera el exporte CSV del informe pedido."""
    pid, f, t = _ventana(parking_id, from_, to, user, db)
    try:
        report = REPORT_BUILDERS[informe](db, pid, f, t)
    except InformeDemasiadoGrandeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return Response(
        content=render_report_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_nombre_fichero(informe, pid, f, t)}.csv"'
            ),
        },
    )


def _pdf_response(
    informe: str,
    parking_id: int,
    from_: Optional[datetime],
    to: Optional[datetime],
    user: User,
    db: Session,
) -> Response:
    """Genera el exporte PDF del informe pedido."""
    pid, f, t = _ventana(parking_id, from_, to, user, db)
    try:
        report = REPORT_BUILDERS[informe](db, pid, f, t)
    except InformeDemasiadoGrandeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    parking = db.get(Parking, pid)
    return Response(
        content=render_report_pdf(
            title=report.title,
            columns=report.columns,
            rows=report.rows,
            summary=report.summary,
            parking=parking,
            window=(f, t),
            generated_at=datetime.now(timezone.utc),
        ),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_nombre_fichero(informe, pid, f, t)}.pdf"'
            ),
        },
    )


@router.get("/margins", response_model=MarginReportRead)
def margin_report(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MarginReportRead:
    _autorizar_informe(user, db, parking_id)
    f, t = _parse_window(from_, to)
    return compute_margin(db, parking_id, from_=f, to=t)


@router.get("/margins.csv")
def margin_report_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _autorizar_informe(user, db, parking_id)
    f, t = _parse_window(from_, to)
    report = compute_margin(db, parking_id, from_=f, to=t)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["parking_id", "parking_name", "from", "to"])
    # T-77: el nombre de la sucursal lo pone un admin: sin escapar, una
    # celda que empieza por "=" seria una formula al abrir el CSV.
    writer.writerow([
        report.parking_id, escapar_celda_csv(report.parking_name),
        report.from_.isoformat(), report.to.isoformat(),
    ])
    writer.writerow([])
    writer.writerow(["metric", "value"])
    writer.writerow(["total_revenue", f"{report.total_revenue:.2f}"])
    writer.writerow(["closed_tickets", report.closed_tickets])
    writer.writerow(["total_costs", f"{report.total_costs:.2f}"])
    writer.writerow(["margin", f"{report.margin:.2f}"])
    writer.writerow([])
    writer.writerow(["category", "amount_eur", "cost_count"])
    for entry in report.cost_breakdown:
        writer.writerow([
            entry.category.value, f"{entry.amount:.2f}", entry.cost_count,
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="margin-{parking_id}-'
                f'{report.from_.date()}-{report.to.date()}.csv"'
            ),
        },
    )


# ─────────────────────── Exportes CSV y PDF (T-16) ───────────────────────


@router.get("/ingresos.csv")
def ingresos_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte CSV del informe de ingresos (tickets cerrados en el periodo)."""
    return _csv_response("ingresos", parking_id, from_, to, user, db)


@router.get("/ingresos.pdf")
def ingresos_pdf(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte PDF del informe de ingresos (tickets cerrados en el periodo)."""
    return _pdf_response("ingresos", parking_id, from_, to, user, db)


@router.get("/ocupacion.csv")
def ocupacion_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte CSV de la ocupación de plazas en el fin del periodo."""
    return _csv_response("ocupacion", parking_id, from_, to, user, db)


@router.get("/ocupacion.pdf")
def ocupacion_pdf(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte PDF de la ocupación de plazas en el fin del periodo."""
    return _pdf_response("ocupacion", parking_id, from_, to, user, db)


@router.get("/tickets.csv")
def tickets_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte CSV de los tickets con entrada en el periodo."""
    return _csv_response("tickets", parking_id, from_, to, user, db)


@router.get("/tickets.pdf")
def tickets_pdf(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte PDF de los tickets con entrada en el periodo."""
    return _pdf_response("tickets", parking_id, from_, to, user, db)


@router.get("/alertas.csv")
def alertas_csv(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte CSV de las alertas creadas en el periodo."""
    return _csv_response("alertas", parking_id, from_, to, user, db)


@router.get("/alertas.pdf")
def alertas_pdf(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte PDF de las alertas creadas en el periodo."""
    return _pdf_response("alertas", parking_id, from_, to, user, db)


@router.get("/margins.pdf")
def margins_pdf(
    parking_id: Annotated[int, Query(ge=1)],
    from_: Annotated[Optional[datetime], Query(alias="from")] = None,
    to: Annotated[Optional[datetime], Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Exporte PDF del informe de margen (ingresos − costes prorrateados)."""
    return _pdf_response("margins", parking_id, from_, to, user, db)


__all__ = ["router"]
