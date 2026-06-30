"""Tareas Celery reales (sustituyen al heartbeat placeholder de Fase 1).

Estado en MVP (Fase 2 temprana):
- `tick_cameras` consulta el modelo Camera y loguea totales.
- `ping_camera` envía un frame placeholder al servicio OCR separado
  (`ocr:8800`) y persiste los hits en `plates_detected`. En Fase 2
  el placeholder 1×1 se sustituye por el frame real del pull RTSP.
- `cleanup_failed_frames` purga el directorio /tmp/ocr-failed de frames
  con más de N días. Idempotente y seguro aunque esté vacío.

`ping_camera` NUNCA lanza excepción: si el servicio OCR no responde,
el cliente devuelve [] y la tarea registra `plates_found=0` en el log.
La app prefiere un "no hay lectura" a un 500 cuando OCR está caído.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.db import SessionLocal
from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected
from app.services.ocr.client import get_ocr_client
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

# Retención de frames fallidos (días) — corte limpio cada pasada.
FAILED_FRAMES_RETENTION_DAYS = 30
DEFAULT_OCR_FAILED_DIR = Path("/tmp/ocr-failed")


def _placeholder_frame_jpeg() -> bytes:
    """Genera un JPEG 1×1 negro en memoria.

    Placeholder temporal hasta enchufar el pull RTSP real. Sirve para
    ejercitar la ruta cliente-OCR → BD sin depender del driver de
    cámara (que se decide en otra iteración de Fase 2).
    """
    img = Image.new("RGB", (1, 1), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


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
def ping_camera(camera_id: int) -> dict[str, Any]:
    """Envía un frame al servicio OCR y persiste los hits detectados.

    Sustituye al stub anterior: en lugar de un sleep simulado, ahora
    genera un JPEG 1×1 (placeholder), lo envía a `ocr:8800/recognize`
    y guarda cada hit en `plates_detected`. Si el servicio no
    responde, `OcrClient.recognize` ya devuelve [] y la tarea termina
    con `plates_found=0` en lugar de fallar.
    """
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if cam is None:
            log.warning("ping_camera: cámara %s no encontrada", camera_id)
            return {"status": "missing"}

        frame = _placeholder_frame_jpeg()
        ocr = get_ocr_client()
        try:
            hits = asyncio.run(ocr.recognize(frame))
        except Exception as exc:  # noqa: BLE001
            # OcrClient no debería lanzar, pero blindamos la tarea
            # igualmente: un fallo del worker no debe romper el beat.
            log.warning("ping_camera: OCR no disponible: %s", exc)
            hits = []

        if not hits:
            log.info(
                "ping_camera: id=%s code=%s plates_found=0",
                cam.id,
                cam.code,
            )
            return {"status": "ok", "code": cam.code, "plates_found": 0}

        now = datetime.now(timezone.utc)
        for h in hits:
            db.add(
                PlatesDetected(
                    camera_id=cam.id,
                    plate=h.plate,
                    confidence=h.confidence,
                    bbox_x1=h.bbox[0],
                    bbox_y1=h.bbox[1],
                    bbox_x2=h.bbox[2],
                    bbox_y2=h.bbox[3],
                    detected_at=now,
                    raw_response=h.model_dump(),
                )
            )
        db.commit()
        log.info(
            "ping_camera: id=%s code=%s plates_found=%s",
            cam.id,
            cam.code,
            len(hits),
        )
        return {
            "status": "ok",
            "code": cam.code,
            "plates_found": len(hits),
        }
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
