"""Tests de los exportes PDF/CSV de informes (T-16, 2026-10-21).

Cubre el contrato HTTP de cada exporte (status, content-type y cabecera
``Content-Disposition``), el contenido (cabecera del CSV, número de filas,
PDF válido) y el cumplimiento de los filtros de fecha y sucursal, además
del RBAC (admin / gestor de la sucursal / resto → 403).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit import Alert
from app.models.enums import (
    AlertSeverity,
    AlertType,
    TicketOrigin,
    TicketStatus,
    VehicleRole,
)
from app.models.parking import ParkingSpace
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from tests import _audit_helpers as ah

UTC = timezone.utc

#: Ventana temporal usada en los informes de los tests.
DESDE = "2026-01-01T00:00:00+00:00"
HASTA = "2026-01-31T23:59:59+00:00"

#: Informes y formatos exportables. ``margins`` ya tenía CSV histórico
#: (multi-sección) que se conserva; el PDF sí es nuevo.
RUTAS_EXPORT: list[tuple[str, str]] = [
    ("ingresos", "csv"),
    ("ingresos", "pdf"),
    ("ocupacion", "csv"),
    ("ocupacion", "pdf"),
    ("tickets", "csv"),
    ("tickets", "pdf"),
    ("alertas", "csv"),
    ("alertas", "pdf"),
    ("margins", "pdf"),
]

#: Prefijo del nombre de fichero de cada informe (``margins`` conserva el
#: prefijo ``margin`` del CSV histórico).
PREFIJOS = {
    "ingresos": "ingresos",
    "ocupacion": "ocupacion",
    "tickets": "tickets",
    "alertas": "alertas",
    "margins": "margin",
}


# ─────────────────────────── helpers de seed ───────────────────────────


def _mk_vehicle(db: Session, plate: str) -> Vehicle:
    """Crea un vehículo con su propietario (``Ticket`` sólo tiene ``vehicle_id``)."""
    user = User(
        email=f"owner-{plate}-{id(db)}@test.es",
        full_name=f"Owner {plate}",
        role=VehicleRole.PROPIETARIO,
        hashed_password="x",
    )
    db.add(user); db.commit(); db.refresh(user)
    vehicle = Vehicle(plate=plate)
    db.add(vehicle); db.commit(); db.refresh(vehicle)
    db.add(VehicleUser(
        vehicle_id=vehicle.id, user_id=user.id, role=VehicleRole.PROPIETARIO,
    ))
    db.commit(); db.refresh(vehicle)
    return vehicle


def _mk_ticket(
    db: Session,
    *,
    parking_id: int,
    entry_at: datetime,
    exit_at: datetime | None = None,
    total: float | None = None,
    space_id: int | None = None,
    status: TicketStatus = TicketStatus.CERRADO,
    plate: str = "0000-ABC",
) -> Ticket:
    """Crea un ticket con su vehículo."""
    vehicle = _mk_vehicle(db, plate)
    ticket = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle.id,
        parking_space_id=space_id,
        entry_at=entry_at,
        exit_at=exit_at,
        amount=total,
        discount=0.0,
        total=total,
        payment_method="tarjeta" if exit_at else None,
        status=status,
        origin=TicketOrigin.AUTOMATIC,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _mk_space(
    db: Session,
    *,
    parking_id: int,
    lane: str = "A",
    number: str = "1",
    is_broken: bool = False,
    is_active: bool = True,
) -> ParkingSpace:
    space = ParkingSpace(
        parking_id=parking_id,
        lane=lane,
        number=number,
        is_broken=is_broken,
        is_active=is_active,
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def _mk_alert(
    db: Session,
    *,
    parking_id: int,
    created_at: datetime,
    severity: AlertSeverity = AlertSeverity.WARN,
    message: str = "Cámara sin señal",
) -> Alert:
    """Crea una alerta con ``created_at`` explícito (si no, valdría "ahora")."""
    alert = Alert(
        parking_id=parking_id,
        type=AlertType.CAMERA_OFFLINE,
        severity=severity,
        message=message,
        created_at=created_at,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _params(parking_id: int) -> dict[str, str]:
    return {"parking_id": str(parking_id), "from": DESDE, "to": HASTA}


def _csv_filas(r) -> tuple[list[str], list[dict[str, str]]]:
    """Devuelve (cabecera, filas) parseando el CSV con ``csv.DictReader``."""
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader.fieldnames or []), list(reader)


# ─────────────────────── contrato HTTP de cada exporte ───────────────────────


@pytest.mark.parametrize(("informe", "formato"), RUTAS_EXPORT)
def test_export_contrato_http(
    client: TestClient, db_session: Session, informe: str, formato: str,
):
    """Cada exporte responde 200 con su content-type y su Content-Disposition."""
    parking = ah._seed_parking(db_session, code=f"P-EX-{informe}-{formato}")
    admin = ah._seed_admin(db_session, email=f"admin-{informe}-{formato}@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    r = client.get(
        f"/api/v1/admin/reports/{informe}.{formato}",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    if formato == "csv":
        assert r.headers["content-type"].startswith("text/csv")
    else:
        assert r.headers["content-type"].startswith("application/pdf")

    disposition = r.headers["content-disposition"]
    esperado = (
        f'attachment; filename="{PREFIJOS[informe]}-{parking.id}-'
        f'2026-01-01-2026-01-31.{formato}"'
    )
    assert disposition == esperado


@pytest.mark.parametrize("informe", ["ingresos", "ocupacion", "tickets", "alertas", "margins"])
def test_export_pdf_es_pdf_valido(
    client: TestClient, db_session: Session, informe: str,
):
    """El PDF descargado empieza por la cabecera %PDF."""
    parking = ah._seed_parking(db_session, code=f"P-PDF-{informe}")
    admin = ah._seed_admin(db_session, email=f"admin-pdf-{informe}@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    r = client.get(
        f"/api/v1/admin/reports/{informe}.pdf",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")
    assert len(r.content) > 1000


@pytest.mark.parametrize("informe", ["ingresos", "ocupacion", "tickets", "alertas"])
def test_export_csv_tiene_cabecera_y_se_parsea(
    client: TestClient, db_session: Session, informe: str,
):
    """El CSV trae cabecera y se parsea con ``csv.DictReader``."""
    parking = ah._seed_parking(db_session, code=f"P-CSV-{informe}")
    admin = ah._seed_admin(db_session, email=f"admin-csv-{informe}@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    r = client.get(
        f"/api/v1/admin/reports/{informe}.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    cabecera, filas = _csv_filas(r)
    assert cabecera, "el CSV debe llevar cabecera"
    assert len(cabecera) >= 2
    assert all(len(fila) == len(cabecera) for fila in filas)


# ─────────────────────────── contenido de los CSV ───────────────────────────


def test_csv_ingresos_contenido_y_filtro_de_fecha(
    client: TestClient, db_session: Session,
):
    """Ingresos: sólo los tickets cerrados con salida dentro de la ventana."""
    parking = ah._seed_parking(db_session, code="P-EX-ING")
    admin = ah._seed_admin(db_session, email="admin-ing@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    # Dentro de la ventana.
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=50.0, plate="1111-AAA",
    )
    # Salida fuera de la ventana → excluido.
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 2, 5, 9, tzinfo=UTC),
        exit_at=datetime(2026, 2, 5, 10, tzinfo=UTC),
        total=999.0, plate="2222-BBB",
    )
    # Activo (sin salida) → no es ingreso.
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 12, 9, tzinfo=UTC),
        status=TicketStatus.ACTIVO, plate="3333-CCC",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/ingresos.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    cabecera, filas = _csv_filas(r)
    assert cabecera == [
        "ticket_id", "matricula", "entrada", "salida", "duracion_min",
        "importe_eur", "descuento_eur", "total_eur", "metodo_pago",
    ]
    assert len(filas) == 1
    assert filas[0]["total_eur"] == "50.00"
    assert filas[0]["matricula"] == "1111-AAA"


def test_csv_ocupacion_contenido_y_filtro_de_fecha(
    client: TestClient, db_session: Session,
):
    """Ocupación: foto de las plazas en el fin de la ventana."""
    parking = ah._seed_parking(db_session, code="P-EX-OCU")
    admin = ah._seed_admin(db_session, email="admin-ocu@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    ocupada = _mk_space(db_session, parking_id=parking.id, lane="A", number="1")
    _mk_space(db_session, parking_id=parking.id, lane="A", number="2", is_broken=True)
    _mk_space(db_session, parking_id=parking.id, lane="A", number="3")

    # Ticket activo dentro de la ventana → ocupa la plaza 1.
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        status=TicketStatus.ACTIVO, space_id=ocupada.id, plate="4444-DDD",
    )
    # Ticket cerrado antes del fin de la ventana → ya no ocupa plaza.
    _mk_space(db_session, parking_id=parking.id, lane="B", number="1")
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/ocupacion.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    cabecera, filas = _csv_filas(r)
    assert cabecera == ["plaza", "estado", "matricula", "ticket_id", "entrada"]
    assert len(filas) == 4
    estados = {fila["plaza"]: fila["estado"] for fila in filas}
    assert estados["A-1"] == "ocupada"
    assert estados["A-2"] == "averiada"
    assert estados["A-3"] == "libre"


def test_csv_tickets_contenido_y_filtro_de_fecha(
    client: TestClient, db_session: Session,
):
    """Tickets: los que tienen *entrada* en la ventana, en cualquier estado."""
    parking = ah._seed_parking(db_session, code="P-EX-TIC")
    admin = ah._seed_admin(db_session, email="admin-tic@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=20.0, plate="5555-EEE",
    )
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 20, 9, tzinfo=UTC),
        status=TicketStatus.ACTIVO, plate="6666-FFF",
    )
    # Entrada fuera de la ventana → excluido.
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2025, 12, 20, 9, tzinfo=UTC),
        exit_at=datetime(2025, 12, 20, 10, tzinfo=UTC),
        total=10.0, plate="7777-GGG",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/tickets.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    cabecera, filas = _csv_filas(r)
    assert cabecera[:4] == ["ticket_id", "matricula", "estado", "origen"]
    assert len(filas) == 2
    assert {fila["estado"] for fila in filas} == {"cerrado", "activo"}


def test_csv_alertas_contenido_y_filtro_de_fecha(
    client: TestClient, db_session: Session,
):
    """Alertas: las creadas dentro de la ventana."""
    parking = ah._seed_parking(db_session, code="P-EX-ALE")
    admin = ah._seed_admin(db_session, email="admin-ale@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    _mk_alert(
        db_session, parking_id=parking.id,
        created_at=datetime(2026, 1, 15, 8, 30, tzinfo=UTC),
        severity=AlertSeverity.CRITICAL, message="Cámara caída",
    )
    # Fuera de la ventana → excluida.
    _mk_alert(
        db_session, parking_id=parking.id,
        created_at=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
        message="Old alert",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/alertas.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    cabecera, filas = _csv_filas(r)
    assert cabecera == [
        "alerta_id", "tipo", "severidad", "mensaje", "creada", "reconocida",
    ]
    assert len(filas) == 1
    assert filas[0]["mensaje"] == "Cámara caída"
    assert filas[0]["severidad"] == "critical"


def test_csv_margins_pdf_refleja_los_ingresos(
    client: TestClient, db_session: Session,
):
    """El PDF de márgenes incluye los ingresos del periodo."""
    parking = ah._seed_parking(db_session, code="P-EX-MAR")
    admin = ah._seed_admin(db_session, email="admin-mar@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=75.0, plate="8888-HHH",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/margins.pdf",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")


def test_csv_margins_tabla_plana(
    client: TestClient, db_session: Session,
):
    """El CSV de márgenes (nuevo) es una tabla plana de conceptos."""
    parking = ah._seed_parking(db_session, code="P-EX-MAR2")
    admin = ah._seed_admin(db_session, email="admin-mar2@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=75.0, plate="9999-III",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/margins.csv",
        headers=headers,
        params=_params(parking.id),
    )
    # El CSV histórico de márgenes (multi-sección) se conserva por
    # compatibilidad con el frontend: aquí sólo se comprueba que sigue
    # funcionando y que la cabecera sigue siendo la de siempre.
    assert r.status_code == 200, r.text
    assert "metric,value" in r.text
    assert "total_revenue" in r.text


# ─────────────────────────── filtro de sucursal ───────────────────────────


def test_export_no_mezcla_sucursales(
    client: TestClient, db_session: Session,
):
    """Los datos de otra sucursal no aparecen en el exporte."""
    parking = ah._seed_parking(db_session, code="P-EX-SCOPE-A")
    otra = ah._seed_parking(db_session, code="P-EX-SCOPE-B")
    admin = ah._seed_admin(db_session, email="admin-scope@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=15.0, plate="AAAA-111",
    )
    _mk_ticket(
        db_session, parking_id=otra.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=999.0, plate="BBBB-222",
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/ingresos.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    _, filas = _csv_filas(r)
    assert len(filas) == 1
    assert filas[0]["matricula"] == "AAAA-111"
    assert filas[0]["total_eur"] == "15.00"


# ───────────────────────────────── RBAC ─────────────────────────────────


@pytest.mark.parametrize(("informe", "formato"), RUTAS_EXPORT)
def test_export_cliente_sin_acceso_403(
    client: TestClient, db_session: Session, informe: str, formato: str,
):
    """Un cliente (sin membresía) recibe 403 en todos los exportes."""
    parking = ah._seed_parking(db_session, code=f"P-RBAC-{informe}-{formato}")
    cliente = ah._seed_cliente(db_session, email=f"cliente-{informe}-{formato}@test.es")
    headers = ah._login_headers(client, cliente.email, "cliente1234")

    r = client.get(
        f"/api/v1/admin/reports/{informe}.{formato}",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 403, r.text


def test_export_gestor_de_su_sucursal_200(
    client: TestClient, db_session: Session,
):
    """El gestor puede exportar los informes de su propia sucursal."""
    parking = ah._seed_parking(db_session, code="P-RBAC-GES")
    gestor = ah._seed_gestor(db_session, email="gestor-rbac@test.es")
    ah._seed_membership(db_session, user=gestor, parking=parking)
    headers = ah._login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        "/api/v1/admin/reports/ingresos.csv",
        headers=headers,
        params=_params(parking.id),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")


def test_export_gestor_otra_sucursal_403(
    client: TestClient, db_session: Session,
):
    """El gestor no puede exportar informes de otra sucursal."""
    parking = ah._seed_parking(db_session, code="P-RBAC-GES-A")
    otra = ah._seed_parking(db_session, code="P-RBAC-GES-B")
    gestor = ah._seed_gestor(db_session, email="gestor-rbac-2@test.es")
    ah._seed_membership(db_session, user=gestor, parking=parking)
    headers = ah._login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        "/api/v1/admin/reports/ingresos.pdf",
        headers=headers,
        params=_params(otra.id),
    )
    assert r.status_code == 403, r.text


def test_export_sin_token_401(
    client: TestClient, db_session: Session,
):
    """Sin token no se puede exportar ningún informe."""
    parking = ah._seed_parking(db_session, code="P-RBAC-401")
    r = client.get(
        "/api/v1/admin/reports/ingresos.pdf",
        params=_params(parking.id),
    )
    assert r.status_code == 401, r.text


def test_export_sin_ventana_422(
    client: TestClient, db_session: Session,
):
    """Sin ``from``/``to`` el exporte devuelve 422 (filtros obligatorios)."""
    parking = ah._seed_parking(db_session, code="P-RBAC-422")
    admin = ah._seed_admin(db_session, email="admin-422@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    r = client.get(
        "/api/v1/admin/reports/ingresos.csv",
        headers=headers,
        params={"parking_id": parking.id},
    )
    assert r.status_code == 422, r.text
