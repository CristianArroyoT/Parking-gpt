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


#: URL publica real del frontend (T-61): en produccion es obligatoria.
URL_REAL = "https://app.solidapp.es"


def _ajustar(entorno: str, secreto: str, url: str = URL_REAL) -> Settings:
    return Settings(  # type: ignore[call-arg]
        ENVIRONMENT=entorno, JWT_SECRET=secreto, FRONTEND_BASE_URL=url
    )


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


# ── T-61: la URL publica del frontend ─────────────────────────────────────
#
# OJO (2026-10-22): el correo de recuperar contrasena llevaba un enlace a
# http://localhost:5173 (constante en el servicio de correo). En
# produccion el cliente pulsaba el enlace y no llegaba a nada. Ahora la URL
# sale de FRONTEND_BASE_URL y, en staging/produccion, la aplicacion NO
# ARRANCA si no es una URL real por HTTPS.


def test_en_produccion_rechaza_la_url_por_defecto() -> None:
    with pytest.raises(ValidationError) as exc:
        _ajustar("production", SECRETO_REAL, url="http://localhost:5173")
    assert "FRONTEND_BASE_URL" in str(exc.value)


def test_en_produccion_rechaza_una_url_sin_https() -> None:
    with pytest.raises(ValidationError) as exc:
        _ajustar("production", SECRETO_REAL, url="http://app.solidapp.es")
    assert "https" in str(exc.value)


def test_en_produccion_acepta_una_url_real() -> None:
    ajustes = _ajustar("production", SECRETO_REAL)
    assert ajustes.frontend_base_url == URL_REAL


def test_en_desarrollo_no_se_comprueba_la_url() -> None:
    """El equipo de QA usa el valor por defecto a proposito."""
    ajustes = _ajustar("development", SECRETO_DE_EJEMPLO, url="http://localhost:5173")
    assert ajustes.frontend_base_url == "http://localhost:5173"


# ── T-64: las listas se configuran con comas (y también con JSON) ─────────
#
# OJO (2026-10-22): ``pydantic-settings`` sólo entiende JSON para los
# campos de tipo lista, así que el formato que documenta el propio
# ``config.py`` (``TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8"``) fallaba
# al arrancar. Sin ``TRUSTED_PROXIES`` el backend no sabe qué IP es la del
# cliente: el rate-limit de login se comparte para toda la sucursal.


def test_las_listas_se_configuran_con_comas() -> None:
    ajustes = Settings(  # type: ignore[call-arg]
        TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8",
        HEARTBEAT_SKIP_URL_PREFIXES="rtsp://demo.invalid,rtsp://test.local",
    )
    assert ajustes.trusted_proxies_list == ["172.16.0.0/12", "10.0.0.0/8"]
    assert ajustes.heartbeat_skip_url_prefixes_list == [
        "rtsp://demo.invalid",
        "rtsp://test.local",
    ]


def test_las_listas_son_strings_y_no_se_parsean() -> None:
    """T-75: con una ``list[str]``, pydantic-settings parseaba el valor
    del entorno como JSON y hacia fallar el ARRANQUE del backend."""
    ajustes = Settings(  # type: ignore[call-arg]
        TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8",
    )
    assert ajustes.trusted_proxies == "172.16.0.0/12,10.0.0.0/8"


def test_una_lista_vacia_se_queda_vacia() -> None:
    ajustes = Settings(TRUSTED_PROXIES="")  # type: ignore[call-arg]
    assert ajustes.trusted_proxies_list == []
