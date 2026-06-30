"""Tareas Celery reales (sustituyen al heartbeat placeholder de Fase 1).

Estado en MVP (Fase 2 cerrada):
- `tick_cameras` consulta el modelo Camera y loguea totales.
- `ping_camera` distingue dos modos de fallo (sprint CAMERA_OFFLINE):
    * `grab_frame` devuelve ``None`` → cámara caída: alerta CRITICAL al
      admin, NO se envía a OCR. Resetea el contador de OCR_FAILED para
      que el fallback al placeholder 1×1 no contamine la métrica.
    * `grab_frame` devuelve bytes pero OCR no detecta → OCR_FAILED,
      alerta WARN al gestor (igual que en sprint ALERTAS).
  El frame se persiste en `plates_detected` cuando hay lecturas y se
  envía a `process_plate_hits` para crear/cerrar tickets.
- `cleanup_failed_frames` purga el directorio /tmp/ocr-failed de frames
  con más de N días. Idempotente y seguro aunque esté vacío.

`ping_camera` NUNCA lanza excepción: si el servicio OCR no responde,
el cliente devuelve [] y la tarea registra `plates_found=0` en el log.
La app prefiere un "no hay lectura" a un 500 cuando OCR está caído.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.db import SessionLocal
from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected
from app.services.alerts import (
    record_camera_offline,
    record_ocr_failure,
    reset_camera_offline,
    reset_ocr_failure,
)
from app.services.cameras.capture import grab_frame
from app.services.ingest_service import process_plate_hits
from app.services.ocr.client import get_ocr_client
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
def ping_camera(camera_id: int) -> dict[str, Any]:
    """Envía un frame al servicio OCR y persiste los hits detectados.

    Captura un frame real del stream RTSP de la cámara (vía
    `app.services.cameras.capture.grab_frame`). Si la captura falla —
    URL inválida, cámara caída, timeout — hace fallback al placeholder
    1×1 negro para mantener la tarea robusta en desarrollo (las URLs
    del seed apuntan a `demo.invalid` a propósito). En cualquier caso,
    el frame se envía a `ocr:8800/recognize` y los hits se persisten
    en `plates_detected`. Si OCR tampoco responde, `plates_found=0`.
    """
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if cam is None:
            log.warning("ping_camera: cámara %s no encontrada", camera_id)
            return {"status": "missing"}

        frame = asyncio.run(grab_frame(cam))
        if frame is None:
            # Cámara caída (RTSP inválido, timeout, codec desconocido).
            # Sprint CAMERA_OFFLINE: NO enviamos a OCR — el placeholder
            # contaminaría el detector de OCR_FAILED. Distinguimos:
            # cámara caída = CRITICAL al admin; OCR vacío = WARN al gestor.
            record_camera_offline(cam)
            # Resetear OCR counter: este fallo NO es de OCR.
            reset_ocr_failure(cam.id)
            log.warning(
                "ping_camera: id=%s code=%s CAMERA_OFFLINE (frame=None)",
                cam.id,
                cam.code,
            )
            return {
                "status": "camera_offline",
                "code": cam.code,
                "plates_found": 0,
            }

        # Cámara OK: limpiar el contador offline antes de continuar.
        reset_camera_offline(cam.id)

        ocr = get_ocr_client()
        try:
            hits = asyncio.run(ocr.recognize(frame))
        except Exception as exc:  # noqa: BLE001
            # OcrClient no debería lanzar, pero blindamos la tarea
            # igualmente: un fallo del worker no debe romper el beat.
            log.warning("ping_camera: OCR no disponible: %s", exc)
            hits = []

        if not hits:
            # Sin lecturas: notificar al detector de N consecutivos.
            # Internamente, después de N (settings.ocr_frames_before_fail)
            # creará una alerta + email + guardará el frame en /tmp/ocr-failed.
            record_ocr_failure(cam, frame)
            log.info(
                "ping_camera: id=%s code=%s source=rtsp plates_found=0",
                cam.id,
                cam.code,
            )
            return {
                "status": "ok",
                "code": cam.code,
                "source": "rtsp",
                "plates_found": 0,
            }

        # Lecturas válidas: reset del detector.
        reset_ocr_failure(cam.id)

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

        # Cruce con geocercas → ticket o skip. Cada hit abre su propia
        # transacción en process_plate_hits; un fallo aquí no debe tumbar
        # el worker. Encapsulamos por defensa (el servicio ya devuelve
        # IngestResult en lugar de propagar, pero blindamos el beat).
        try:
            ingest_results = process_plate_hits(hits, cam)
        except Exception as exc:  # noqa: BLE001 — defensiva
            log.warning("ping_camera: error en ingest_service: %s", exc)
            ingest_results = []

        created = sum(1 for r in ingest_results if r.status == "ticket_created")
        closed = sum(1 for r in ingest_results if r.status == "ticket_closed")
        if created or closed:
            log.info(
                "ping_camera: id=%s code=%s source=rtsp plates_found=%s tickets_created=%s tickets_closed=%s",
                cam.id,
                cam.code,
                len(hits),
                created,
                closed,
            )
        else:
            log.info(
                "ping_camera: id=%s code=%s source=rtsp plates_found=%s",
                cam.id,
                cam.code,
                len(hits),
            )
        return {
            "status": "ok",
            "code": cam.code,
            "source": "rtsp",
            "plates_found": len(hits),
            "tickets_created": created,
            "tickets_closed": closed,
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
