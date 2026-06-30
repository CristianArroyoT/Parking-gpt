"""Tareas Celery reales (sustituyen al heartbeat placeholder de Fase 1).

Estado en MVP (Fase 2 temprana):
- `tick_cameras` y `ping_camera` sólo consultan el modelo Camera y loguean
  estado. NO se hace pull RTSP ni OCR todavía — PaddleOCR requiere
  decisión arquitectónica (Docker-servicio-separado vs in-proc) y un
  modelo nuevo `PlatesDetected` con migración Alembic.
- `cleanup_failed_frames` purga el directorio /tmp/ocr-failed de frames
  con más de N días. Idempotente y seguro aunque esté vacío.

Estos stubs permiten que el beat schedule tenga periodicidad real y que
el healthcheck de celery-worker/celery-beat deje de marcarse como
"unhealthy" cuando se enchufe la lógica de Fase 2.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.db import SessionLocal
from app.models.parking import Camera
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

# Retención de frames fallidos (días) — corte limpio cada pasada.
FAILED_FRAMES_RETENTION_DAYS = 30
DEFAULT_OCR_FAILED_DIR = Path("/tmp/ocr-failed")


@celery_app.task(name="solidapp.tick_cameras")
def tick_cameras() -> dict[str, int]:
    """Revisa el estado del inventario de cámaras y loguea totales.

    En Fase 2 cada cámara tendrá un último `heartbeat_at` y un
    `status` (active | degraded | offline) — aquí sólo contamos
    activas vs inactivas para validar que el pipeline corre.
    """
    db = SessionLocal()
    try:
        active = db.query(Camera).filter(Camera.is_active.is_(True)).count()
        inactive = db.query(Camera).filter(Camera.is_active.is_(False)).count()
    finally:
        db.close()
    payload = {"active": active, "inactive": inactive}
    log.info("tick_cameras: %s", payload)
    return payload


@celery_app.task(name="solidapp.ping_camera")
def ping_camera(camera_id: int) -> dict[str, str]:
    """Stub de health-check de una cámara concreta.

    En Fase 2 abrirá el RTSP con FFmpeg / OpenCV y medirá latencia.
    Aquí sólo verifica que la cámara existe y devuelve su `rtsp_url`
    enmascarada para no loguear credenciales.
    """
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if cam is None:
            log.warning("ping_camera: cámara %s no encontrada", camera_id)
            return {"status": "missing"}
        masked = cam.rtsp_url.split("@")[-1] if "@" in cam.rtsp_url else cam.rtsp_url
        log.info("ping_camera: id=%s code=%s url=...%s", cam.id, cam.code, masked[-32:])
        # Pequeño sleep simula I/O. Quitar al enchufar el pull real.
        time.sleep(0.05)
        return {"status": "ok", "code": cam.code}
    finally:
        db.close()


@celery_app.task(name="solidapp.cleanup_failed_frames")
def cleanup_failed_frames() -> dict[str, int]:
    """Purga /tmp/ocr-failed/*.jpg con mtime > N días.

    Idempotente y tolerante a directorio inexistente (no falla el
    worker si todavía no se ha creado).
    """
    if not DEFAULT_OCR_FAILED_DIR.exists():
        return {"deleted": 0, "kept": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=FAILED_FRAMES_RETENTION_DAYS)
    deleted = 0
    kept = 0
    for entry in DEFAULT_OCR_FAILED_DIR.iterdir():
        if not entry.is_file():
            continue
        mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                entry.unlink()
                deleted += 1
            except OSError as exc:
                log.warning("No se pudo borrar %s: %s", entry, exc)
        else:
            kept += 1
    log.info("cleanup_failed_frames: deleted=%s kept=%s", deleted, kept)
    return {"deleted": deleted, "kept": kept}
