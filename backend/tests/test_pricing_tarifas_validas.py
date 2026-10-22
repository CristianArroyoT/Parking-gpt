"""T-84: la API de tarifas no puede meter valores que rompen el calculo.

Medido (2026-10-22): el esquema aceptaba precios negativos,
``fraction_minutes=0`` (ZeroDivisionError al cerrar un ticket) y
``max_daily`` negativo (importe negativo). Y la tarifa queda en la base de
datos: ``_find_tariff`` toma la mas reciente, asi que afecta a todos los
tickets de esa sucursal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.pricing import Tariff
from app.schemas.pricing import TariffCreate, TariffUpdate
from app.services.pricing import _compute_amount

BASE = {
    "parking_id": 1,
    "name": "Tarifa",
    "price_per_hour": 2.5,
    "price_per_fraction": 0.70,
    "fraction_minutes": 15,
    "max_daily": 25.0,
    "valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
}


def _crear(**kwargs) -> TariffCreate:
    datos = {**BASE, **kwargs}
    return TariffCreate(**datos)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("price_per_hour", -5.0),
        ("price_per_fraction", -1.0),
        ("fraction_minutes", 0),
        ("fraction_minutes", -15),
        ("max_daily", -1.0),
    ],
)
def test_el_esquema_rechaza_los_valores_invalidos(campo: str, valor: object) -> None:
    with pytest.raises(ValidationError):
        _crear(**{campo: valor})


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("price_per_hour", -5.0),
        ("price_per_fraction", -1.0),
        ("fraction_minutes", 0),
        ("max_daily", -1.0),
    ],
)
def test_el_patch_tambien_rechaza_los_valores_invalidos(
    campo: str, valor: object
) -> None:
    with pytest.raises(ValidationError):
        TariffUpdate(**{campo: valor})  # type: ignore[arg-type]


def test_una_tarifa_valida_se_acepta() -> None:
    tarifa = _crear()
    assert tarifa.price_per_hour == 2.5
    assert tarifa.fraction_minutes == 15


def _tarifa_en_bd(**kwargs) -> Tariff:
    entrada = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    datos = {
        "parking_id": 1,
        "name": "Rota",
        "price_per_hour": 2.5,
        "price_per_fraction": 0.70,
        "fraction_minutes": 15,
        "max_daily": 25.0,
        "valid_from": entrada - timedelta(days=1),
    }
    datos.update(kwargs)
    return Tariff(**datos)  # type: ignore[arg-type]


def test_una_fraccion_de_cero_no_peta() -> None:
    """Defensa en profundidad: una tarifa de 0 que ya este en la base de
    datos no puede tumbar el cierre de un ticket."""
    entrada = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    importe = _compute_amount(
        _tarifa_en_bd(fraction_minutes=0), entrada, entrada + timedelta(hours=2)
    )
    assert importe >= 0.0


def test_un_precio_negativo_no_cobra_de_menos() -> None:
    """El importe de un ticket nunca es negativo."""
    entrada = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    importe = _compute_amount(
        _tarifa_en_bd(price_per_hour=-5.0, price_per_fraction=-1.0),
        entrada,
        entrada + timedelta(hours=2, minutes=30),
    )
    assert importe == 0.0
