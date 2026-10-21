"""Test de integración: cierre de ticket con cálculo de tarifa + /users/me.

Crea una sucursal, plaza, vehículo y un ticket activo, luego cierra el
ticket y comprueba que amount/discount/total quedan rellenos. Aprovecha
para verificar el nuevo endpoint GET /api/v1/users/me que consume el
frontend al hidratar la sesión.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import get_db
from app.core.security import hash_password
from app.main import create_app
from app.models.enums import UserRole
from app.models.parking import Parking, ParkingSpace
from app.models.pricing import Tariff
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.models.vehicle import Vehicle


def test_close_ticket_computes_pricing(motor_de_test):
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()

    admin = User(
        email="admin@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    parking = Parking(code="MAD-T", name="Madrid Test", address="Calle 1", city="Madrid")
    db.add_all([admin, parking])
    db.flush()
    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    veh = Vehicle(plate="0000-ZZZ")
    db.add_all([space, veh])
    db.flush()
    db.add(Tariff(
        parking_id=parking.id, name="Estándar",
        price_per_hour=2.0, price_per_fraction=0.5, fraction_minutes=15,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    entry = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    db.add(Ticket(
        parking_id=parking.id, vehicle_id=veh.id, parking_space_id=space.id,
        status=TicketStatus.ACTIVO, entry_at=entry,
    ))
    db.commit()

    app = create_app()

    def _override():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.es", "password": "admin12345"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/api/v1/users/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == "admin@test.es"

        lst = client.get("/api/v1/tickets", headers=headers, params={"only_active": True})
        assert lst.status_code == 200
        assert len(lst.json()) == 1
        ticket_id = lst.json()[0]["id"]

        exit_at = (entry + timedelta(hours=1, minutes=30)).isoformat()
        close = client.post(
            f"/api/v1/tickets/{ticket_id}/close",
            json={"exit_at": exit_at, "payment_method": "card"},
            headers=headers,
        )
        assert close.status_code == 200, close.text
        body = close.json()
        # 1 h (2 €) + ceil(30/15)=2 fracciones (1 €) = 3 €
        assert body["amount"] == 3.0
        assert body["discount"] == 0.0
        assert body["total"] == 3.0
        assert body["status"] == "cerrado"
        assert body["payment_method"] == "card"

    db.close()
    engine.dispose()