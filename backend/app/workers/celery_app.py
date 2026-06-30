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

# ── Tareas reales (Fase 2 temprana) ────────────────────────────────────
# Importar el módulo registra las tareas en este `celery_app` vía los
# decoradores @celery_app.task. Ver `app/workers/tasks.py` para detalle.
from app.workers import tasks  # noqa: F401, E402


celery_app.conf.beat_schedule = {
    # Inventario cada minuto: barato y útil para detectar caídas.
    "tick-cameras-every-minute": {
        "task": "solidapp.tick_cameras",
        "schedule": crontab(minute="*/1"),
    },
    # Limpieza de frames fallidos cada 6 horas.
    "cleanup-failed-frames-every-6h": {
        "task": "solidapp.cleanup_failed_frames",
        "schedule": crontab(minute="0", hour="*/6"),
    },
}