"""Tests unitarios del servicio de pricing.

Cubren: horas completas, fracciones, tope diario, descuento por plan
y errores (sin tarifa, salida anterior a entrada).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import UserRole, VehicleRole
from app.models.parking import Parking
from app.models.pricing import Plan, Subscription, Tariff
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.services.pricing import PricingError, calculate_ticket_total


@pytest.fixture()
def db(motor_de_test):
    """Sesión sobre el motor del dialecto de la suite.

    Antes creaba su propio SQLite en memoria, así que este fichero
    seguía pasándose por SQLite aunque la suite completa corriera
    contra PostgreSQL.

    Se crea además la sucursal (id=1) de la que cuelgan las tarifas:
    SQLite **no aplica claves foráneas por defecto**, así que antes
    las tarifas apuntaban a un parking inexistente sin que nadie se
    enterara. En PostgreSQL la FK sí se aplica y el test reventaba con
    ``ForeignKeyViolation`` — el dialecto de producción estaba sin
    cubrir.
    """
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    session.add(
        Parking(code="MAD-P", name="Parking Test", address="Calle 1", city="Madrid")
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _seed_tariff(db, price_hour=2.5, price_frac=0.7, fraction=15, max_daily=None, when=None):
    when = when or datetime(2026, 6, 1, tzinfo=timezone.utc)
    db.add(
        Tariff(
            parking_id=1,
            name="Estándar",
            price_per_hour=price_hour,
            price_per_fraction=price_frac,
            fraction_minutes=fraction,
            max_daily=max_daily,
            valid_from=when,
        )
    )
    db.commit()


def test_two_full_hours_no_fraction(db):
    _seed_tariff(db)
    total = calculate_ticket_total(
        db,
        parking_id=1,
        vehicle_id=1,
        entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
    )
    assert total.amount == pytest.approx(5.0)
    assert total.discount == pytest.approx(0.0)
    assert total.total == pytest.approx(5.0)


def test_one_hour_plus_fraction(db):
    _seed_tariff(db)
    total = calculate_ticket_total(
        db,
        parking_id=1,
        vehicle_id=1,
        entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 6, 1, 10, 20, tzinfo=timezone.utc),
    )
    # 1h + 20min → ceil(20/15) = 2 fracciones
    assert total.amount == pytest.approx(2.5 + 2 * 0.7)


def test_max_daily_cap(db):
    _seed_tariff(db, max_daily=10.0)
    total = calculate_ticket_total(
        db,
        parking_id=1,
        vehicle_id=1,
        entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
    )
    # 5 h → 12.50 €, cap a 10 €
    assert total.amount == pytest.approx(10.0)


def test_discount_with_active_plan(db):
    _seed_tariff(db)
    user = User(email="cliente@x.es", full_name="C", role=UserRole.CLIENTE, hashed_password="x")
    db.add(user)
    db.flush()
    plan = Plan(
        code="basico", name="Básico",
        monthly_price=30.0, discount_percent=5.0, included_vehicles=0, is_active=True,
    )
    db.add(plan)
    db.flush()
    veh = Vehicle(plate="1234-ABC")
    db.add(veh)
    db.flush()
    db.add(VehicleUser(vehicle_id=veh.id, user_id=user.id, role=VehicleRole.PROPIETARIO))
    db.add(
        Subscription(
            user_id=user.id, plan_id=plan.id,
            starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ends_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        )
    )
    db.commit()

    total = calculate_ticket_total(
        db,
        parking_id=1,
        vehicle_id=veh.id,
        entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
    )
    assert total.amount == pytest.approx(5.0)
    assert total.discount == pytest.approx(0.25)   # 5 % de 5 €
    assert total.total == pytest.approx(4.75)


def test_no_tariff_raises(db):
    with pytest.raises(PricingError):
        calculate_ticket_total(
            db,
            parking_id=999,
            vehicle_id=1,
            entry_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        )


def test_exit_before_entry_raises(db):
    _seed_tariff(db)
    with pytest.raises(PricingError):
        calculate_ticket_total(
            db,
            parking_id=1,
            vehicle_id=1,
            entry_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
            exit_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        )