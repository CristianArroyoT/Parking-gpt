"""Tests del reporte de margen (Sprint P1 solidAPP).

Cubre la unidad de cómputo (``compute_margin``) y los dos endpoints
HTTP (``/admin/reports/margins`` JSON y CSV) con foco en:

- Prorrateo de costes recurrentes dentro del rango del reporte.
- Coste puntual: imputación proporcional al solape con el rango.
- Tickets cerrados en el rango cuentan para ingresos.
- RBAC: admin y gestor (con parking_context) ven su sucursal.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.cost import Cost
from app.models.enums import (
    CostCategory,
    CostPeriod,
    TicketOrigin,
    TicketStatus,
    VehicleRole,
)
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.services.cost import compute_margin
from tests import _audit_helpers as ah


UTC = timezone.utc


def _mk_vehicle(
    db: Session, *, plate: str = "0000-ABC",
) -> Vehicle:
    """Crea un vehículo + su propietario (N:M vía ``VehicleUser``) para
    usarlo en un ticket. ``Ticket`` no tiene campo ``plate`` — sólo
    ``vehicle_id`` FK, y ``vehicles`` no tiene ``owner_user_id`` directo."""
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
    db: Session, *, parking_id: int, entry_at: datetime,
    exit_at: datetime, total: float, status: TicketStatus = TicketStatus.CERRADO,
) -> Ticket:
    vehicle = _mk_vehicle(db)
    t = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle.id,
        entry_at=entry_at,
        exit_at=exit_at,
        total=total,
        status=status,
        origin=TicketOrigin.AUTOMATIC,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── compute_margin (unit) ────────────────────────────────────────────


def test_compute_margin_puntual_full_overlap(
    db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR1")
    db_session.add(Cost(
        parking_id=parking.id,
        category=CostCategory.MANTENIMIENTO,
        amount=100.0,
        periodicity=CostPeriod.PUNTUAL,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 10, tzinfo=UTC),
    ))
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 5, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 5, 10, tzinfo=UTC),
        total=50.0,
    )
    db_session.commit()

    report = compute_margin(
        db_session, parking.id,
        from_=datetime(2026, 1, 1, tzinfo=UTC),
        to=datetime(2026, 1, 31, tzinfo=UTC),
    )
    assert report.total_revenue == 50.0
    assert report.closed_tickets == 1
    assert report.total_costs == pytest.approx(100.0)
    assert report.margin == pytest.approx(-50.0)
    assert len(report.cost_breakdown) == 1
    assert report.cost_breakdown[0].category == CostCategory.MANTENIMIENTO


def test_compute_margin_recurrente_prorrateo(
    db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR2")
    db_session.add(Cost(
        parking_id=parking.id,
        category=CostCategory.CAMARAS,
        amount=300.0,
        periodicity=CostPeriod.MENSUAL,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=None,
    ))
    db_session.commit()

    report = compute_margin(
        db_session, parking.id,
        from_=datetime(2026, 1, 1, tzinfo=UTC),
        to=datetime(2026, 1, 16, tzinfo=UTC),  # 15 días completos
    )
    assert report.total_costs == pytest.approx(150.0)


def test_compute_margin_empty_when_invalid_range(
    db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR3")
    report = compute_margin(
        db_session, parking.id,
        from_=datetime(2026, 5, 1, tzinfo=UTC),
        to=datetime(2026, 4, 30, tzinfo=UTC),
    )
    assert report.total_revenue == 0.0
    assert report.total_costs == 0.0
    assert report.margin == 0.0
    assert report.cost_breakdown == []


# ── HTTP JSON ────────────────────────────────────────────────────────


def test_margin_report_json_admin(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR4")
    admin = ah._seed_admin(db_session, email="admin-mr4@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    client.post(
        "/api/v1/admin/costs", headers=headers,
        json={
            "parking_id": parking.id,
            "category": "operacion",
            "amount": 200.0,
            "periodicity": "puntual",
            "period_start": "2026-01-01T00:00:00+00:00",
            "period_end": "2026-01-31T00:00:00+00:00",
        },
    )
    _mk_ticket(
        db_session, parking_id=parking.id,
        entry_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        exit_at=datetime(2026, 1, 10, 10, tzinfo=UTC),
        total=75.0,
    )
    db_session.commit()

    r = client.get(
        "/api/v1/admin/reports/margins",
        headers=headers,
        params={
            "parking_id": parking.id,
            "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_revenue"] == 75.0
    assert body["closed_tickets"] == 1
    assert body["total_costs"] == pytest.approx(200.0)
    assert body["margin"] == pytest.approx(-125.0)


# ── HTTP CSV ─────────────────────────────────────────────────────────


def test_margin_report_csv_admin(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR5")
    admin = ah._seed_admin(db_session, email="admin-mr5@test.es")
    headers = ah._login_headers(client, admin.email, "admin12345")

    client.post(
        "/api/v1/admin/costs", headers=headers,
        json={
            "parking_id": parking.id,
            "category": "otros",
            "amount": 50.0,
            "periodicity": "puntual",
            "period_start": "2026-02-01T00:00:00+00:00",
            "period_end": "2026-02-15T00:00:00+00:00",
        },
    )

    r = client.get(
        "/api/v1/admin/reports/margins.csv",
        headers=headers,
        params={
            "parking_id": parking.id,
            "from": "2026-02-01T00:00:00+00:00",
            "to": "2026-02-28T23:59:59+00:00",
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "metric,value" in body
    assert "total_revenue" in body
    assert "category,amount_eur,cost_count" in body
    assert "otros" in body


# ── RBAC ─────────────────────────────────────────────────────────────


def test_margin_report_gestor_se_su_sucursal(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR6")
    gestor = ah._seed_gestor(db_session, email="gestor-mr6@test.es")
    ah._seed_membership(db_session, user=gestor, parking=parking)
    headers = ah._login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        "/api/v1/admin/reports/margins",
        headers=headers,
        params={
            "parking_id": parking.id,
            "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
        },
    )
    assert r.status_code == 200


def test_margin_report_gestor_otra_sucursal_403(
    client: TestClient, db_session: Session,
):
    parking = ah._seed_parking(db_session, code="P-MR7")
    otra = ah._seed_parking(db_session, code="P-MR7-OTRA")
    gestor = ah._seed_gestor(db_session, email="gestor-mr7@test.es")
    ah._seed_membership(db_session, user=gestor, parking=parking)
    headers = ah._login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        "/api/v1/admin/reports/margins",
        headers=headers,
        params={
            "parking_id": otra.id,
            "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
        },
    )
    assert r.status_code == 403