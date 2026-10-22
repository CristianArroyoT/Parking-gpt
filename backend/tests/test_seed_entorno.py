"""T-83: el seed de demo se niega a correr en staging/produccion.

El seed crea ``admin@solidapp.es`` con la contrasena ``admin12345``, escrita
en el README y en este repositorio publico: en una sucursal eso es un
administrador accesible.
"""
from __future__ import annotations

import pytest

from app.scripts.seed import motivo_rechazo


def test_en_desarrollo_se_puede_sembrar() -> None:
    assert motivo_rechazo("development", False) is None
    assert motivo_rechazo("test", False) is None


@pytest.mark.parametrize("entorno", ["staging", "production"])
def test_en_staging_y_produccion_se_rechaza(entorno: str) -> None:
    motivo = motivo_rechazo(entorno, False)
    assert motivo is not None
    # El motivo tiene que decir QUE hacer, no solo que no se puede.
    assert "admin@solidapp.es" in motivo
    assert "--allow-demo-users" in motivo


@pytest.mark.parametrize("entorno", ["staging", "production"])
def test_con_el_flag_explicito_se_permite(entorno: str) -> None:
    """Quien quiera datos de prueba en un staging puede decirlo."""
    assert motivo_rechazo(entorno, True) is None
