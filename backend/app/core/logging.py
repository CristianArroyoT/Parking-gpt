"""Logger JSON estructurado para envío a Loki (sprint Fase 3A, 2026-07-01).

Configura el logger raíz de Python con dos handlers:
  - ``stdout`` (StreamHandler): legible para ``docker compose logs backend``.
    Formato ``plain`` por defecto en dev (niveles INFO arriba), o ``json``
    en producción (un JSON por línea parseable por Promtail).
  - ``file`` (RotatingFileHandler): escribe a ``/var/log/solidapp/backend.log``
    con rotación 10 MB × 5. Promtail scrapea este directorio y envía a Loki.

Activación: ``configure_logging()`` se llama en ``app/main.py`` lifespan
startup. NO se llama en tests (``pytest`` mantiene el logger en WARNING
para no contaminar el output).

Decisión: ``log_format=plain`` por defecto (desarrollo) para que el
operador pueda leer ``docker compose logs backend`` sin parsear JSON.
En ``production`` se sobreescribe vía env ``LOG_FORMAT=json``.
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path

from app.core.config import get_settings

# Ruta del archivo rotado. Coincide con el volumen ``app_logs`` del
# docker-compose que monta Promtail. Si el directorio no existe (p.ej.
# en tests), el handler ``file`` simplemente no se añade.
LOG_DIR = Path("/var/log/solidapp")
LOG_FILE = LOG_DIR / "backend.log"


def configure_logging() -> None:
    """Configura el logger raíz. Idempotente (safe re-call)."""
    settings = get_settings()
    fmt = settings.log_format

    formatters: dict = {
        "plain": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
    }
    if fmt == "json":
        formatters["json"] = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        }

    handlers: dict = {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": fmt if fmt in formatters else "plain",
            "stream": "ext://sys.stdout",
        },
    }

    if LOG_DIR.is_dir():
        # En producción: el directorio existe (montado desde el host).
        # En desarrollo sin volumen: el handler simplemente no se añade
        # (no rompe la app).
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "json" if "json" in formatters else "plain",
            "encoding": "utf-8",
        }

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": formatters,
            "handlers": handlers,
            "loggers": {
                "": {
                    "handlers": list(handlers.keys()),
                    "level": settings.log_level,
                },
                "uvicorn.access": {
                    "handlers": ["stdout"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": list(handlers.keys()),
                    "level": settings.log_level,
                    "propagate": False,
                },
                "sqlalchemy.engine": {"level": "WARNING"},
                "celery": {"level": "INFO"},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
            },
        }
    )


__all__ = ["configure_logging", "LOG_DIR", "LOG_FILE"]