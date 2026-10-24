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
    # T-151 (2026-10-24): con ``acks_late`` y SIN esto, si el worker
    # muere de forma abrupta (OOM, el contenedor lo mata) el mensaje no se
    # reentrega hasta que vence el ``visibility_timeout`` de Redis (1
    # hora), y el beat publica la ronda de heartbeats cada 60 s: la cola
    # crece sin que nadie la consuma. Con esto, el broker lo reentrega
    # enseguida.
    # OJO: solo funciona con el pool **prefork** (el que usa el compose).
    task_reject_on_worker_lost=True,
    # T-151: ninguna tarea puede ocupar un slot del pool para siempre
    # (una camara que no responde, un ``asyncio.wait_for`` que no puede
    # matar un hilo). El limite blando lanza ``SoftTimeLimitExceeded``
    # dentro de la tarea; el duro mata el proceso (el mensaje se
    # reentrega, por ``task_reject_on_worker_lost``).
    task_soft_time_limit=1800,   # 30 min
    task_time_limit=1860,        # 31 min (algo por encima del blando)
    # T-151: con ``acks_late``, una tarea que **falla** se reentrega, y sin
    # limite de intentos eso es un bucle (un error permanente se reintenta
    # para siempre). Con esto, la falla se confirma y no se reintenta; las
    # tareas que deben reintentarse lo hacen con ``autoretry_for``.
    task_acks_on_failure_or_timeout=True,
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
    # Heartbeat real (sprint CAMERA_OFFLINE v2): sondea cada cámara
    # con ``cv2.VideoCapture.open() + grab()`` (sin decodificar).
    # Tras N fallos consecutivos (``heartbeat_failures_before_alert``)
    # crea alerta CAMERA_OFFLINE con ``context.kind="heartbeat"``.
    #
    # OJO (2026-10-22, actualizado el 2026-10-24): el detector por
    # ``kind="frame"`` (``solidapp.ping_camera``) **ya se despacha**: lo
    # encola ``solidapp.ping_cameras`` (ver más abajo). Los dos
    # detectores comparten el lock de 1 h de ``CAMERA_OFFLINE``, así que
    # no duplican la alerta. La puerta
    # ``tools/verificar_tareas_celery.py`` lo comprueba.
    "probe-heartbeats-every-minute": {
        "task": "solidapp.probe_heartbeats",
        "schedule": 60.0,  # cada 60 segundos exactos
    },
    # T-177 (2026-10-24): el ping a las cámaras pasa a despacharse
    # **cada 10 minutos por cámara** (decisión de producto del
    # 2026-10-24). El intervalo sale de un **ajuste**
    # (``PING_CAMERA_INTERVAL_SECONDS``), no de un número escrito a
    # fuego: si cambia, cambian el beat, el TTL del lock por cámara y el
    # TTL del contador de fallos de OCR (``app/services/alerts.py``).
    #
    # ``solidapp.ping_cameras`` encola un ``solidapp.ping_camera`` por
    # cada cámara activa, con un lock por cámara (Redis, TTL igual al
    # intervalo) para que los pings no se acumulen si una cámara se
    # queda colgada.
    #
    # OJO: el heartbeat de arriba ya cubre la **liveness** del stream
    # RTSP. Lo que el ping añade es el **viaje al OCR** (detectar el
    # motor OCR muerto aunque el push del fabricante siga llegando).
    "ping-cameras-every-10min": {
        "task": "solidapp.ping_cameras",
        "schedule": settings.ping_camera_interval_seconds,
    },
    # T-95 (2026-10-23): purga diaria de las fotos de incidentes que han
    # pasado la retencion (90 dias por defecto, LOPDGDD). Antes era un
    # script manual que nadie lanzaba.
    "purge-incident-attachments-daily": {
        "task": "solidapp.purge_incident_attachments",
        "schedule": crontab(minute=17, hour=3),  # 3:17 AM, hora valle.
    },
    # T-125 (2026-10-23): purga diaria de los vehiculos «fantasma» (los
    # que creo la ingesta y que se quedaron sin dueno y sin ticket).
    # Antes no habia ninguna tarea que los borrara: medido en la base de
    # datos de QA, 3 vehiculos con cero duenos y cero tickets, creados
    # cuatro meses antes.
    "purge-ghost-vehicles-daily": {
        "task": "solidapp.purge_ghost_vehicles",
        "schedule": crontab(minute=23, hour=4),  # 4:23 AM, hora valle.
    },
    # T-141 (2026-10-24): barrida diaria de los ficheros HUERFANOS del
    # volumen (los que ya no tienen fila). Antes la funcion existia pero
    # no la llamaba nadie: no habia tarea ni entrada en el beat, asi que
    # cualquier fichero que se quedara sin fila se quedaba en disco para
    # siempre. A las 4:47 AM, con 1 h de margen para no competir con una
    # subida en curso (el fichero se escribe antes que la fila).
    "purge-orphan-attachments-daily": {
        "task": "solidapp.purge_orphan_attachments",
        "schedule": crontab(minute=47, hour=4),  # 4:47 AM, hora valle.
    },
    # T-124 (2026-10-24): auto-cierre de las estancias sin salida
    # detectada (decision de producto: 24 h con el importe estimado y
    # aviso al cliente). Antes el ticket se quedaba activo para siempre,
    # con importe 0, y los informes de ocupacion no cuadraban.
    # Cada hora, al minuto 10 (hora valle).
    "auto-close-tickets-hourly": {
        "task": "solidapp.auto_close_tickets",
        "schedule": crontab(minute=10),  # cada hora, al minuto 10.
    },
    # T-164 (2026-10-24): vigilar que las camaras **sigan empujando
    # lecturas**. El push externo es el camino real de datos y no tenia
    # ninguna vigilancia (la unica alarma de OCR cuelga de
    # ``ping_camera``, que no se despacha).
    "check-camera-pushes": {
        "task": "solidapp.check_camera_pushes",
        "schedule": crontab(minute="*/15"),  # cada 15 minutos.
    },
    # Sprint Fase 3C: rotación de audit_logs (sprint 2026-07-01).
    # Borra ``audit_logs`` con ``created_at < now - audit_log_retention_days``
    # (default 365). Necesita el índice ``ix_audit_logs_created_at``
    # añadido en migración 0008 para no hacer seq scan.
    "purge-audit-logs-daily": {
        "task": "solidapp.purge_audit_logs",
        "schedule": crontab(minute=0, hour=3),  # 3 AM hora valle.
    },
}