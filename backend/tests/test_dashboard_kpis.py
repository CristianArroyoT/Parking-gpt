"""Tests del endpoint ``/admin/dashboard/kpis`` y su service
``compute_dashboard_kpis`` (Sprint UI Costes + Dashboard KPIs, 2026-07-06).

Cubre:

  1. ``compute_dashboard_kpis`` unit (sin TestClient) sobre ``db`` en
     memoria con datos sintéticos.
  2. ``GET /admin/dashboard/kpis`` HTTP-level: agregado, filtrado,
     RBAC, ventana 24 h vs 7d vs 30d, prorrateo de costes recurrentes.

Patrón sigue ``test_tickets_summary.py`` y ``test_margin_report.py``:
``_seed_*`` + ``datetime.now`` inyectable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.cost import Cost
from app.models.enums import CostCategory, CostPeriod, TicketStatus
from app.models.parking import Camera, ParkingSpace
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.services.dashboard_kpis import compute_dashboard_kpis
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_gestor,
    _seed_parking,
)


NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
DAY_START = NOW - timedelta(hours=24)
WEEK_START = NOW - timedelta(days=7)
MONTH_START = NOW - timedelta(days=30)


# ── Helpers de seed ──────────────────────────────────────────────────


def _make_vehicle(db: Session, plate: str) -> Vehicle:
    v = Vehicle(plate=plate)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _make_space(db: Session, parking_id: int, lane: str = "A",
                number: str = "1", is_broken: bool = False) -> ParkingSpace:
    sp = ParkingSpace(
        parking_id=parking_id, lane=lane, number=number,
        is_broken=is_broken,
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return sp


def _make_camera(db: Session, parking_id: int, code: str = "C1",
                 *, last_ok: bool | None = None,
                 last_at: datetime | None = None) -> Camera:
    cam = Camera(
        parking_id=parking_id, code=code, name=f"Cam {code}",
        rtsp_url="rtsp://x",
        last_heartbeat_ok=last_ok,
        last_heartbeat_at=last_at,
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def _make_ticket(
    db: Session, *,
    parking_id: int,
    vehicle_id: int,
    status: TicketStatus,
    exit_at: datetime | None,
    total: float | None,
    parking_space_id: int | None = None,
) -> Ticket:
    t = Ticket(
        parking_id=parking_id, vehicle_id=vehicle_id,
        parking_space_id=parking_space_id,
        status=status,
        entry_at=exit_at - timedelta(hours=2) if exit_at else NOW,
        exit_at=exit_at,
        total=total,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_cost(
    db: Session, *,
    parking_id: int,
    amount: float,
    category: CostCategory = CostCategory.OPERACION,
    periodicity: CostPeriod = CostPeriod.MENSUAL,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> Cost:
    c = Cost(
        parking_id=parking_id, amount=amount,
        category=category, periodicity=periodicity,
        period_start=period_start or (NOW - timedelta(days=5)),
        period_end=period_end,
        description="test cost",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ── 1. Service unit ──────────────────────────────────────────────────


def test_service_zero_state_returns_zeros_and_none(db_session: Session) -> None:
    """Sin datos: spaces/cameras en 0, revenue/costs todos None."""
    result = compute_dashboard_kpis(db_session, parking_id=None, now=NOW)
    assert result.parking_id is None
    assert result.spaces.total == 0
    assert result.spaces.occupied == 0
    assert result.spaces.free == 0
    assert result.spaces.broken == 0
    assert result.cameras.total == 0
    assert result.cameras.operational == 0
    assert result.cameras.alert == 0
    assert result.cameras.never_probed == 0
    assert result.revenue.day is None
    assert result.revenue.week is None
    assert result.revenue.month is None
    assert result.costs.day is None
    assert result.costs.week is None
    assert result.costs.month is None


def test_service_aggregated_sums_three_parkings(db_session: Session) -> None:
    """Sin parking_id agrega TODAS las sucursales."""
    p1 = _seed_parking(db_session, code="P1")
    p2 = _seed_parking(db_session, code="P2")
    p3 = _seed_parking(db_session, code="P3")
    _make_space(db_session, p1.id, number="1")
    _make_space(db_session, p1.id, number="2")
    _make_space(db_session, p2.id, number="1")
    _make_camera(db_session, p1.id, code="c1", last_ok=True,
                 last_at=NOW - timedelta(minutes=5))
    _make_camera(db_session, p2.id, code="c2", last_ok=False,
                 last_at=NOW - timedelta(minutes=5))
    _make_camera(db_session, p3.id, code="c3")  # never_probed

    result = compute_dashboard_kpis(db_session, parking_id=None, now=NOW)
    assert result.spaces.total == 3
    assert result.cameras.total == 3
    assert result.cameras.operational == 1
    assert result.cameras.alert == 1
    assert result.cameras.never_probed == 1


def test_service_filtered_by_parking_id(db_session: Session) -> None:
    """Con parking_id, sólo agrega ESA sucursal."""
    p1 = _seed_parking(db_session, code="P1")
    p2 = _seed_parking(db_session, code="P2")
    _make_space(db_session, p1.id, number="1")
    _make_space(db_session, p1.id, number="2")
    _make_space(db_session, p2.id, number="1")
    _make_camera(db_session, p1.id, code="c1")
    _make_camera(db_session, p2.id, code="c2")

    result = compute_dashboard_kpis(db_session, parking_id=p1.id, now=NOW)
    assert result.parking_id == p1.id
    assert result.spaces.total == 2
    assert result.cameras.total == 1


def test_service_revenue_24h_vs_7d_vs_30d_distinguishes_windows(
    db_session: Session,
) -> None:
    """Tickets cerrados en distintas ventanas: 24h ≠ 7d ≠ 30d."""
    p = _seed_parking(db_session, code="PR")
    v = _make_vehicle(db_session, "0001AAA")

    # Cerrado hace 12 h → cuenta en todas las ventanas.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.CERRADO,
                 exit_at=NOW - timedelta(hours=12), total=10.0)
    # Cerrado hace 3 días → cuenta en week y month, NO en day.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.CERRADO,
                 exit_at=NOW - timedelta(days=3), total=20.0)
    # Cerrado hace 15 días → cuenta sólo en month.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.CERRADO,
                 exit_at=NOW - timedelta(days=15), total=30.0)
    # Activo (no cerrado) → no cuenta nunca.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.ACTIVO, exit_at=None, total=None)

    result = compute_dashboard_kpis(db_session, parking_id=p.id, now=NOW)
    assert result.revenue.day == 10.0
    assert result.revenue.week == 30.0
    assert result.revenue.month == 60.0


def test_service_costs_prorate_recurring_within_window(
    db_session: Session,
) -> None:
    """Coste mensual de 300 € con period_start hace 15 días.

    Por la regla de prorrateo: ciclo = 30 días, 10 €/día.
    En la ventana day (1 día): 10.0 €.
    En la ventana week (7 días): 70.0 €.
    En la ventana month (15 días desde period_start hace 15 d, total
    30 días): 15 días dentro de [now-30, now] → 150.0 €.
    """
    p = _seed_parking(db_session, code="PC")
    _make_cost(
        db_session, parking_id=p.id, amount=300.0,
        category=CostCategory.OPERACION, periodicity=CostPeriod.MENSUAL,
        period_start=NOW - timedelta(days=15),
    )

    result = compute_dashboard_kpis(db_session, parking_id=p.id, now=NOW)
    assert result.costs.day == 10.0
    assert result.costs.week == 70.0
    assert result.costs.month == 150.0


def test_service_occupied_counts_active_ticket_spaces(
    db_session: Session,
) -> None:
    """Una plaza está "ocupada" si hay un ticket activo apuntando a
    ella. Plaza con ticket activo + plaza sin nada + plaza rota."""
    p = _seed_parking(db_session, code="PO")
    s1 = _make_space(db_session, p.id, number="1")
    s2 = _make_space(db_session, p.id, number="2")
    _make_space(db_session, p.id, number="3", is_broken=True)
    v = _make_vehicle(db_session, "0002BBB")

    # Ticket activo apuntando a s1.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.ACTIVO, exit_at=None,
                 total=None, parking_space_id=s1.id)

    result = compute_dashboard_kpis(db_session, parking_id=p.id, now=NOW)
    assert result.spaces.total == 3
    assert result.spaces.occupied == 1
    assert result.spaces.broken == 1
    assert result.spaces.free == 1  # s2 libre


# ── 2. HTTP-level ────────────────────────────────────────────────────


def test_http_admin_no_parking_id_succeeds(
    client: TestClient, db_session: Session,
) -> None:
    """Admin sin parking_id → 200 con KPIs agregados."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    r = client.get("/api/v1/admin/dashboard/kpis", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parking_id"] is None
    assert "spaces" in body
    assert "cameras" in body
    assert "revenue" in body
    assert "costs" in body


def test_http_admin_with_parking_id_filters(
    client: TestClient, db_session: Session,
) -> None:
    """Admin con parking_id → devuelve parking_id en respuesta."""
    admin = _seed_admin(db_session)
    p = _seed_parking(db_session, code="PF")
    _make_space(db_session, p.id, number="1")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.get(
        f"/api/v1/admin/dashboard/kpis?parking_id={p.id}", headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parking_id"] == p.id
    assert body["spaces"]["total"] == 1


def test_http_gestor_forbidden(
    client: TestClient, db_session: Session,
) -> None:
    """Gestor (no admin) → 403. El endpoint es admin-only en este sprint."""
    gestor = _seed_gestor(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")
    r = client.get("/api/v1/admin/dashboard/kpis", headers=headers)
    assert r.status_code == 403, r.text


def test_http_cliente_forbidden(
    client: TestClient, db_session: Session,
) -> None:
    """Cliente (no admin) → 403."""
    cliente = _seed_cliente(db_session)
    headers = _login_headers(client, cliente.email, "cliente1234")
    r = client.get("/api/v1/admin/dashboard/kpis", headers=headers)
    assert r.status_code == 403, r.text


def test_http_unauthenticated_forbidden(client: TestClient) -> None:
    """Sin Authorization → 401."""
    r = client.get("/api/v1/admin/dashboard/kpis")
    assert r.status_code == 401


def test_http_revenue_day_none_when_no_closed_tickets_in_window(
    client: TestClient, db_session: Session,
) -> None:
    """Si no hay tickets cerrados en 24 h, ``revenue.day == null``."""
    admin = _seed_admin(db_session)
    p = _seed_parking(db_session, code="PN")
    v = _make_vehicle(db_session, "0003CCC")
    # Ticket cerrado hace 30 h → fuera de ventana 24 h.
    _make_ticket(db_session, parking_id=p.id, vehicle_id=v.id,
                 status=TicketStatus.CERRADO,
                 exit_at=NOW - timedelta(hours=30), total=99.0)
    headers = _login_headers(client, admin.email, "admin12345")
    r = client.get(
        f"/api/v1/admin/dashboard/kpis?parking_id={p.id}", headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["revenue"]["day"] is None
    assert body["revenue"]["month"] == 99.0