"""El importe de un ticket tiene que **cuadrar** (T-131).

Antes el total se calculaba con los valores SIN redondear y despues
``amount`` y ``discount`` se redondeaban por separado. Con una tarifa de
2,50 €/hora + 0,175 € por fracción de 15 minutos y un plan del 50 %:

    importe   2,675 €      ->  2,67 €
    descuento 1,3375 €     ->  1,34 €   (calculado sobre 2,675)
    total (antes) = round(2,675 - 1,3375, 2) = 1,34 €   <-- no cuadra
                          (2,67 - 1,34 = 1,33)

Es decir, el PDF del ticket enseñaba "2,67 - 1,34 = 1,34": una cuenta
que no suma. Ahora se redondea **una sola vez y en este orden**: el
descuento se calcula sobre el importe ya redondeado y el total es la
diferencia de los dos valores redondeados, así que siempre cuadra.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.enums import UserRole, VehicleRole
from app.models.parking import Parking
from app.models.pricing import Plan, Subscription, Tariff
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.services.pricing import calculate_ticket_total


def _escenario(db: Session) -> tuple[int, int]:
    """Parking, tarifa (2,50 + 0,175), plan del 50 %, usuario y vehículo."""
    parking = Parking(code="P-REDONDEO", name="R", address="x", city="y")
    db.add(parking)
    db.flush()
    db.add(
        Tariff(
            parking_id=parking.id,
            name="Estándar",
            price_per_hour=2.5,
            price_per_fraction=0.175,
            fraction_minutes=15,
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    usuario = User(
        email="redondeo@test.es",
        full_name="Redondeo",
        role=UserRole.CLIENTE,
        hashed_password="x",
    )
    plan = Plan(
        code="MEDIO",
        name="Medio",
        monthly_price=100.0,
        discount_percent=50.0,
        included_vehicles=5,
        is_active=True,
    )
    db.add_all([usuario, plan])
    db.flush()
    db.add(
        Subscription(
            user_id=usuario.id,
            plan_id=plan.id,
            starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ends_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        )
    )
    vehiculo = Vehicle(plate="7777RED")
    db.add(vehiculo)
    db.flush()
    db.add(
        VehicleUser(
            vehicle_id=vehiculo.id,
            user_id=usuario.id,
            role=VehicleRole.PROPIETARIO,
        )
    )
    db.commit()
    return parking.id, vehiculo.id


def test_el_total_cuadra_con_el_importe_menos_el_descuento(
    db_session: Session,
) -> None:
    """El caso que descuadraba: importe - descuento = total."""
    parking_id, vehicle_id = _escenario(db_session)

    entrada = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    salida = entrada + timedelta(hours=1, minutes=15)  # 2,675 € antes de redondear

    total = calculate_ticket_total(
        db_session,
        parking_id=parking_id,
        vehicle_id=vehicle_id,
        entry_at=entrada,
        exit_at=salida,
    )

    assert total.amount == 2.67, total
    assert total.discount == 1.33, total
    assert total.total == 1.34, total
    # La propiedad: el total ES el importe menos el descuento.
    # (Con `round`: en binario, 2,67 - 1,33 = 1,3399999999999998.)
    assert total.total == round(total.amount - total.discount, 2), total


def test_el_total_cuadra_en_todas_las_estancias(
    db_session: Session,
) -> None:
    """La propiedad se cumple para cualquier estancia (no sólo para la que descuadraba)."""
    parking_id, vehicle_id = _escenario(db_session)
    entrada = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)

    for minutos in (5, 15, 30, 45, 60, 75, 120, 135, 330, 615):
        total = calculate_ticket_total(
            db_session,
            parking_id=parking_id,
            vehicle_id=vehicle_id,
            entry_at=entrada,
            exit_at=entrada + timedelta(minutes=minutos),
        )
        assert round(total.amount, 2) == total.amount, total
        assert round(total.discount, 2) == total.discount, total
        assert total.total == round(total.amount - total.discount, 2), (
            f"no cuadra con {minutos} minutos: {total}"
        )
