"""Tests de la configuración: el secreto JWT tiene que ser real fuera de desarrollo.

POR QUÉ (2026-10-21): el compose trae ``JWT_SECRET:
${JWT_SECRET:-change-me-in-production}`` y ese valor por defecto está
escrito en un repositorio **público**. Si una sucursal se despliega sin
poner la variable, la API firmaría los tokens con un secreto que
cualquiera puede leer: se podría fabricar el token de un administrador.
La aplicación ahora se niega a arrancar en ``staging``/``production`` con
ese valor, en vez de fallar más tarde con un 401 sin explicación.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SECRETO_DE_EJEMPLO = "change-me-in-production"
SECRETO_REAL = "un-secreto-de-verdad-32-caracteres-min"


def _ajustar(entorno: str, secreto: str) -> Settings:
    return Settings(ENVIRONMENT=entorno, JWT_SECRET=secreto)  # type: ignore[call-arg]


def test_en_produccion_rechaza_el_secreto_de_ejemplo() -> None:
    with pytest.raises(ValidationError) as exc:
        _ajustar("production", SECRETO_DE_EJEMPLO)
    assert "JWT_SECRET" in str(exc.value)


def test_en_staging_rechaza_el_secreto_de_ejemplo() -> None:
    with pytest.raises(ValidationError):
        _ajustar("staging", SECRETO_DE_EJEMPLO)


@pytest.mark.parametrize("secreto", ["change-me", "changeme", "secret", "  ", ""])
def test_rechaza_variantes_del_secreto_de_ejemplo(secreto: str) -> None:
    with pytest.raises(ValidationError):
        _ajustar("production", secreto)


def test_en_produccion_acepta_un_secreto_real() -> None:
    ajustes = _ajustar("production", SECRETO_REAL)
    assert ajustes.jwt_secret == SECRETO_REAL
    assert ajustes.environment == "production"


def test_en_desarrollo_no_se_comprueba() -> None:
    """El equipo de QA usa el valor por defecto a propósito: no debe
    romperle el arranque."""
    ajustes = _ajustar("development", SECRETO_DE_EJEMPLO)
    assert ajustes.jwt_secret == SECRETO_DE_EJEMPLO


def test_en_test_no_se_comprueba() -> None:
    ajustes = _ajustar("test", SECRETO_DE_EJEMPLO)
    assert ajustes.environment == "test"
