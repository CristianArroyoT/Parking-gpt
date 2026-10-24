"""T-150 (2026-10-24): el lock de la ronda de heartbeats no puede caducar
con la ronda viva.

El defecto
----------
``_tomar_lock`` usa ``SET NX EX 120`` (T-102, para que dos rondas no se
solapen), pero el TTL es **fijo** y la ronda **no tiene duracion
acotada**. Si la ronda vive mas de 120 s, el lock caduca **con la ronda
en marcha** y la ronda siguiente (el beat publica cada 60 s) puede
tomarlo: dos rondas a la vez, que es justo lo que el T-102 queria
evitar (los fallos se cuentan dos veces por minuto, se duplican las
filas de auditoria y los eventos, y dos rondas pueden tomar a la vez el
lock de alerta de una camara).

El arreglo
----------
**Renovar** el TTL mientras la ronda vive, de forma atomica (Lua): si el
lock ya no es nuestro, no se toca.
"""
from __future__ import annotations

import time

import pytest
import redis as redis_lib

from app.core.config import get_settings
from app.workers import tasks as tasks_mod


def _redis() -> redis_lib.Redis | None:
    """El Redis de los tests (o ``None`` si no hay)."""
    try:
        rds = redis_lib.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        rds.ping()
        return rds
    except Exception:  # noqa: BLE001
        return None


def test_el_lock_se_renueva_mientras_la_ronda_vive() -> None:
    """El TTL tiene que volver a su valor: si no, la ronda pierde el lock."""
    rds = _redis()
    if rds is None:
        pytest.skip("no hay Redis en este entorno")

    nombre = "prueba_t150"
    clave = f"celery:lock:{nombre}"
    token = tasks_mod._tomar_lock(nombre, ttl=10)
    assert token is not None
    try:
        ttl_antes = rds.ttl(clave)
        assert 0 < ttl_antes <= 10, (
            f"el lock no deberia durar mas de 10 s (era {ttl_antes})"
        )

        # OJO: Redis devuelve el TTL como **entero** (redondeado), asi que
        # un margen de un segundo no distingue nada. Se espera lo
        # suficiente para que el TTL **baje** de forma visible y se
        # comprueba que, tras renovar, ha **subido**.
        time.sleep(3.0)
        ttl_medio = rds.ttl(clave)
        assert ttl_medio < ttl_antes, (
            f"el TTL deberia haber bajado ({ttl_antes} -> {ttl_medio})"
        )

        assert tasks_mod._renovar_lock(nombre, token, ttl=10) is True

        ttl_despues = rds.ttl(clave)
        assert ttl_despues > ttl_medio, (
            f"el TTL no se ha renovado ({ttl_medio} -> {ttl_despues}): una "
            "ronda larga perderia el lock con la ronda en marcha"
        )
    finally:
        tasks_mod._soltar_lock(nombre, token)
        rds.delete(clave)


def test_el_lock_ajeno_no_se_renueva() -> None:
    """Si el lock ya es de otra ronda, no se toca (comparacion atomica)."""
    rds = _redis()
    if rds is None:
        pytest.skip("no hay Redis en este entorno")

    nombre = "prueba_t150_ajeno"
    clave = f"celery:lock:{nombre}"
    token = tasks_mod._tomar_lock(nombre, ttl=5)
    assert token is not None
    try:
        assert tasks_mod._renovar_lock(nombre, "token-de-otra-ronda", ttl=5) is False
        assert rds.get(clave) == token, "se ha tocado el lock de otra ronda"
    finally:
        tasks_mod._soltar_lock(nombre, token)
        rds.delete(clave)


def test_soltar_el_lock_no_toca_el_de_otra_ronda() -> None:
    """Igual al soltar: si no es nuestro, se deja como estaba."""
    rds = _redis()
    if rds is None:
        pytest.skip("no hay Redis en este entorno")

    nombre = "prueba_t150_soltar"
    clave = f"celery:lock:{nombre}"
    token = tasks_mod._tomar_lock(nombre, ttl=5)
    assert token is not None
    try:
        tasks_mod._soltar_lock(nombre, "token-de-otra-ronda")
        assert rds.get(clave) == token, "se ha soltado el lock de otra ronda"
        tasks_mod._soltar_lock(nombre, token)
        assert rds.get(clave) is None, "el lock propio no se ha soltado"
    finally:
        rds.delete(clave)
