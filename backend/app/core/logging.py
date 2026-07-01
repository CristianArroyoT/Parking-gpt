# Logger JSON estructurado para envío a Loki (sprint Fase 3A, 2026-07-01).
#
# Configura el logger raíz de Python con dos handlers:
#   - ``stdout`` (StreamHandler): legible para ``docker compose logs backend``.
#     Formato ``plain`` por defecto en dev (niveles INFO arriba), o ``json``
#     en producción (un JSON por línea parseable por Promtail).
#   - ``file`` (RotatingFileHandler): escribe a ``/var/log/solidapp/backend.log``
#     con rotación 10 MB × 5. Promtail scrapea este directorio y envía a Loki.
#
# Activación: ``configure_logging()`` se llama en ``app/main.py`` lifespan
# startup.
#
# Decisión: ``log_format=plain`` por defecto (desarrollo) para que el
# operador pueda leer ``docker compose logs backend`` sin parsear JSON.
# En ``production`` se sobreescribe vía env ``LOG_FORMAT=json``.
#
# Sprint Fase 3B-parte-2 (2026-07-01): la función ahora cierra y elimina
# los handlers previos del root logger antes de reconfigurar. Esto es
# necesario porque en tests cada fixture ``client`` crea una app nueva
# que ejecuta ``lifespan`` → ``configure_logging()`` otra vez. Antes, el
# segundo ``dictConfig`` fallaba al intentar añadir un segundo
# ``RotatingFileHandler`` al mismo archivo (el directorio existe dentro
# del container desde que ``backend/Dockerfile`` lo creó en Fase 3A).
from __future__ import annotations

import logging
import logging.config
import os
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

    # En pytest (PYTEST_CURRENT_TEST lo pone pytest al ejecutar), saltamos
    # la configuración de logging: el directorio /var/log/solidapp/ existe
    # dentro del container y RotatingFileHandler abre el archivo en cada
    # ``dictConfig``. Como cada fixture ``client`` crea una app nueva
    # (que ejecuta lifespan → configure_logging otra vez), el sistema
    # operativo acaba rechazando la apertura del archivo en el segundo
    # test ("ValueError: Unable to configure handler 'file'"). El logger
    # por defecto de pytest mantiene la salida limpia sin que nosotros
    # configuremos nada.
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    # Idempotencia: cerrar y eliminar handlers previos del root logger
    # antes de reconfigurar. Sin esto, dictConfig añade handlers
    # duplicados en cada llamada y RotatingFileHandler falla al reabrir
    # el mismo archivo (segundo test en adelante).
    root = logging.getLogger()
    for _h in list(root.handlers):
        root.removeHandler(_h)
        try:
            _h.close()
        except Exception:
            pass

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

    if LOG_DIR.is_dir() and os.access(LOG_DIR, os.W_OK):
        # En producción: el directorio existe (montado desde el host).
        # Si el volumen se montó con ownership root (típico de named
        # volumes creados por el daemon Docker), el container que corre
        # como USER ``app`` no podrá escribir y el handler fallará al
        # abrir el archivo. Comprobamos ``os.W_OK`` antes de añadirlo
        # para degradar con elegancia a sólo-stdout en lugar de romper
        # el startup del backend.
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

    # Defensa de profundidad: si por alguna razón el handler "file" falla
    # (p.ej. permisos del volumen cambiaron en runtime), degradamos a
    # sólo-stdout para que el backend NO rompa su startup. Los logs
    # estructurados críticos (alertas, audit) se seguirán viendo en
    # stdout — docker compose logs los captura igual.
    if "file" in handlers:
        root = logging.getLogger()
        for _h in list(root.handlers):
            if getattr(_h, "name", None) == "file" and not isinstance(
                _h, logging.StreamHandler
            ):
                try:
                    _h.close()
                except Exception:
                    pass
                root.removeHandler(_h)
                logging.getLogger(__name__).warning(
                    "RotatingFileHandler no se pudo inicializar "
                    "(permisos de volumen?). Continuando sólo con stdout."
                )


__all__ = ["configure_logging", "LOG_DIR", "LOG_FILE"]