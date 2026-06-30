"""Instancia Celery compartida por worker y beat.

Configuración leída de `Settings` (variables de entorno) — mismo origen
que la app FastAPI, así no duplicamos parámetros en el compose.
Las tareas reales llegan en Fase 2; este módulo existe hoy para que el
CMD de `docker/celery/Dockerfile` tenga algo que arrancar.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "solidapp",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Madrid",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# ── Tareas placeholder Fase 1 ──────────────────────────────────────────
@celery_app.task(name="solidapp.heartbeat")
def heartbeat() -> dict[str, str]:
    """Heartbeat periódico usado por el beat para verificar el pipeline.

    En Fase 2 se sustituirá por tareas reales (OCR pull, reportes, alertas).
    """
    return {"status": "ok"}


celery_app.conf.beat_schedule = {
    "heartbeat-every-minute": {
        "task": "solidapp.heartbeat",
        "schedule": crontab(minute="*/1"),
    },
}