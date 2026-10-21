"""Comprobación de dependencias del backend (readiness).

POR QUÉ (2026-10-21): ``GET /health`` devolvía ``{"status": "ok"}``
**sin comprobar nada**. O sea que un stack con la base de datos caída (o
con Redis caído) se declaraba **sano**, mientras:

- con la BD caída, cualquier endpoint que toque la base devolvía 500;
- con Redis caído, el ``AuditMiddleware`` va a *fail-closed* (por
  seguridad: si no se puede consultar la blacklist de tokens, no se deja
  pasar ningún token) y **toda** petición autenticada devolvía 401 con
  *"Servicio de autenticación no disponible"*.

En los dos casos ``docker compose ps`` decía "healthy" y el operador no
tenía ni una pista. Este módulo es el que hace la comprobación de verdad
para el endpoint ``GET /health/ready``.

La distinction es la estándar:

- ``/health``      → *liveness*: ¿el proceso vive? (siempre 200)
- ``/health/ready`` → *readiness*: ¿puede servir tráfico ahora mismo?
"""
from __future__ import annotations

import logging
from typing import Any

import redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import engine

log = logging.getLogger(__name__)

#: Segundos de espera al conectar. Es una comprobación de salud: si la
#: dependencia no responde en este tiempo, a efectos de la comprobación
#: es como si no estuviera.
TIMEOUT_S = 2.0


def _comprobar_bd() -> tuple[bool, str]:
    """¿Responde la base de datos? Un ``SELECT 1`` y listo."""
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        return True, "ok"
    except SQLAlchemyError as exc:
        log.warning("health/ready: la base de datos no responde: %s", exc)
        return False, type(exc).__name__


def _comprobar_redis() -> tuple[bool, str]:
    """¿Responde Redis? Un ``PING`` con timeout corto."""
    try:
        cliente = redis.Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=TIMEOUT_S,
            socket_timeout=TIMEOUT_S,
        )
        try:
            cliente.ping()
        finally:
            cliente.close()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 — redis lanza varias familias
        log.warning("health/ready: Redis no responde: %s", exc)
        return False, type(exc).__name__


def comprobar_dependencias() -> dict[str, Any]:
    """Estado de las dependencias críticas del backend.

    Devuelve un diccionario con ``ok`` (bool) y ``dependencies`` (detalle
    por dependencia). ``ok`` es ``True`` sólo si **todas** responden.
    """
    bd_ok, bd_detalle = _comprobar_bd()
    redis_ok, redis_detalle = _comprobar_redis()
    return {
        "ok": bd_ok and redis_ok,
        "dependencies": {
            "database": "ok" if bd_ok else bd_detalle,
            "redis": "ok" if redis_ok else redis_detalle,
        },
    }


__all__ = ["comprobar_dependencias"]
