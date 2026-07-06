"""Tests del resumen operativo de tickets por sucursal.

Sprint Fase 4-parte-2 (2026-07-06).

Cubre:
- Métricas básicas (counts + revenue + avg) sobre datos sintéticos.
- Ventana móvil de 24 h (tickets fuera de ventana se excluyen).
- RBAC: cliente sin membresía -> 403; admin sin membresía -> 200.

Nota: el estado "cancelado" del dominio se modela como ``TicketStatus.ANULADO``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.models.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_gestor,
    _seed_membership,
    _seed_parking,
)


NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
T0 = NOW - timedelta(hours=12)   # dentro de ventana (24 h)
T_OLD = NOW - timedelta(hours=25)  # fuera de ventana


def _make_vehicle(db, plate: str) -> Vehicle:
    v = Vehicle(plate=plate)
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _seed_ticket(
    db,
    *,
    parking_id: int,
    vehicle_id: int,
    status: TicketStatus,
    entry_at: datetime,
    exit_at: datetime | None = None,
    total: float | None = None,
) -> Ticket:
    t = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle_id,
        status=status,
        entry_at=entry_at,
        exit_at=exit_at,
        total=total,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ────────────────────────────────────────────────────────────────────────
# Servicio unitario (sin HTTP)
# ────────────────────────────────────────────────────────────────────────


def test_summary_empty_parking_returns_zeros(db_session):
    """Parking sin tickets: counts=0, revenue y avg = None."""
    from app.services.ticket_summary import compute_ticket_summary

    parking = _seed_parking(db_session, code="P-EMPTY")

    summary = compute_ticket_summary(db_session, parking.id, now=NOW)

    assert summary.total_tickets_24h == 0
    assert summary.active_tickets_now == 0
    assert summary.closed_tickets_24h == 0
    assert summary.cancelled_tickets_24h == 0
    assert summary.total_revenue_24h is None  # sin muestra
    assert summary.average_duration_minutes is None
    assert summary.window_hours == 24


def test_summary_counts_active_closed_cancelled(db_session):
    """2 activos + 1 cerrado + 1 cancelado en ventana."""
    from app.services.ticket_summary import compute_ticket_summary

    parking = _seed_parking(db_session, code="P-CT")
    v1, v2, v3, v4 = (_make_vehicle(db_session, f"CT-{i}") for i in range(1, 5))
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v1.id,
        status=TicketStatus.ACTIVO, entry_at=T0,
    )
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v2.id,
        status=TicketStatus.ACTIVO, entry_at=T0 - timedelta(hours=2),
    )
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v3.id,
        status=TicketStatus.CERRADO,
        entry_at=T0 - timedelta(hours=1),
        exit_at=T0 + timedelta(hours=1),
        total=5.0,
    )
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v4.id,
        status=TicketStatus.ANULADO, entry_at=T0,
        exit_at=T0,
    )

    summary = compute_ticket_summary(db_session, parking.id, now=NOW)

    assert summary.total_tickets_24h == 4  # todos entry_at >= T0 - 24h
    assert summary.active_tickets_now == 2
    assert summary.closed_tickets_24h == 1
    assert summary.cancelled_tickets_24h == 1


def test_summary_revenue_sums_closed_in_window(db_session):
    """SUM(total) sobre cerrados en últimos 24 h."""
    from app.services.ticket_summary import compute_ticket_summary

    parking = _seed_parking(db_session, code="P-RV")
    v1, v2 = (_make_vehicle(db_session, f"RV-{i}") for i in range(1, 3))
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v1.id,
        status=TicketStatus.CERRADO,
        entry_at=T0 - timedelta(minutes=30),
        exit_at=T0 + timedelta(minutes=30),
        total=12.5,
    )
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v2.id,
        status=TicketStatus.CERRADO,
        entry_at=T0 - timedelta(hours=2),
        exit_at=T0 - timedelta(hours=1),
        total=7.5,
    )

    summary = compute_ticket_summary(db_session, parking.id, now=NOW)

    assert summary.total_revenue_24h == 20.0


def test_summary_average_duration_minutes(db_session):
    """Media de (exit_at - entry_at) en minutos sobre cerrados en ventana."""
    from app.services.ticket_summary import compute_ticket_summary

    parking = _seed_parking(db_session, code="P-AVG")
    v1, v2 = (_make_vehicle(db_session, f"AVG-{i}") for i in range(1, 3))
    # Ticket 1: 60 min de duración.
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v1.id,
        status=TicketStatus.CERRADO,
        entry_at=T0 - timedelta(minutes=30),
        exit_at=T0 + timedelta(minutes=30),
        total=2.0,
    )
    # Ticket 2: 120 min de duración.
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v2.id,
        status=TicketStatus.CERRADO,
        entry_at=T0 - timedelta(hours=2),
        exit_at=T0,
        total=3.0,
    )

    summary = compute_ticket_summary(db_session, parking.id, now=NOW)

    # Media = (60 + 120) / 2 = 90 minutos
    assert summary.average_duration_minutes == 90.0


def test_summary_window_excludes_tickets_older_than_24h(db_session):
    """Tickets con exit_at/entry_at fuera de la ventana no cuentan."""
    from app.services.ticket_summary import compute_ticket_summary

    parking = _seed_parking(db_session, code="P-WIN")
    v1 = _make_vehicle(db_session, "WIN-1")
    # Ticket cerrado hace 25 h: NO debe contar.
    _seed_ticket(
        db_session, parking_id=parking.id, vehicle_id=v1.id,
        status=TicketStatus.CERRADO,
        entry_at=T_OLD - timedelta(hours=1),
        exit_at=T_OLD,
        total=99.0,
    )

    summary = compute_ticket_summary(db_session, parking.id, now=NOW)

    assert summary.total_tickets_24h == 0
    assert summary.closed_tickets_24h == 0
    assert summary.total_revenue_24h is None


# ────────────────────────────────────────────────────────────────────────
# Endpoint HTTP + RBAC
# ────────────────────────────────────────────────────────────────────────


def test_summary_endpoint_returns_200_for_admin(db_session, client: TestClient):
    """Admin sin membresía puede ver el summary (parking_context bypass)."""
    parking = _seed_parking(db_session, code="P-EP")
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.get(f"/api/v1/parkings/{parking.id}/tickets/summary", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_tickets_24h"] == 0
    assert body["window_hours"] == 24


def test_summary_endpoint_403_for_cliente_without_membership(
    db_session, client: TestClient,
):
    """Cliente sin membresía queda bloqueado por parking_context (403)."""
    parking = _seed_parking(db_session, code="P-CL")
    cliente = _seed_cliente(db_session)
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.get(f"/api/v1/parkings/{parking.id}/tickets/summary", headers=headers)

    assert r.status_code == 403


def test_summary_endpoint_403_for_gestor_without_membership(
    db_session, client: TestClient,
):
    """Gestor sin membresía en el parking objetivo -> 403."""
    parking = _seed_parking(db_session, code="P-GX")
    gestor = _seed_gestor(db_session)  # sin _seed_membership
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get(f"/api/v1/parkings/{parking.id}/tickets/summary", headers=headers)

    assert r.status_code == 403


def test_summary_endpoint_200_for_gestor_with_membership(
    db_session, client: TestClient,
):
    """Gestor CON membresía ve el summary de su parking."""
    parking = _seed_parking(db_session, code="P-GM")
    gestor = _seed_gestor(db_session)
    _seed_membership(db_session, user=gestor, parking=parking)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get(f"/api/v1/parkings/{parking.id}/tickets/summary", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {
        "total_tickets_24h", "active_tickets_now", "closed_tickets_24h",
        "cancelled_tickets_24h", "total_revenue_24h",
        "average_duration_minutes", "window_hours",
    }