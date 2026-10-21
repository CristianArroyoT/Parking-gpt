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

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.audit import AuditLog
from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected
from app.services.alerts import (
    record_camera_offline,
    record_ocr_failure,
    reset_camera_offline,
    reset_ocr_failure,
)
from app.services.event_bus import EventType, publish as publish_event
from app.services.audit import (
    make_worker_correlation_id,
    record_audit_worker,
)
from app.services.cameras.capture import grab_frame
from app.services.cameras.heartbeat import probe_camera
from app.services.ingest_service import process_plate_hits
from app.services.ocr.client import get_ocr_client
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

# Retención de frames fallidos (días) — corte limpio cada pasada.
FAILED_FRAMES_RETENTION_DAYS = 30
DEFAULT_OCR_FAILED_DIR = Path("/tmp/ocr-failed")


@celery_app.task(name="solidapp.tick_cameras")  # type: ignore[untyped-decorator]
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


@celery_app.task(name="solidapp.ping_camera")  # type: ignore[untyped-decorator]
def ping_camera(camera_id: int) -> dict[str, Any]:
    """Envía un frame al servicio OCR y persiste los hits detectados.

    Captura un frame real del stream RTSP de la cámara (vía
    `app.services.cameras.capture.grab_frame`). Si la captura falla —
    URL inválida, cámara caída, timeout — hace fallback al placeholder
    1×1 negro para mantener la tarea robusta en desarrollo (las URLs
    del seed apuntan a `demo.invalid` a propósito). En cualquier caso,
    el frame se envía a `ocr:8800/recognize` y los hits se persisten
    en `plates_detected`. Si OCR tampoco responde, `plates_found=0`.

    Sprint Fase 3C (2026-07-01): un único ``correlation_id`` por
    invocación se pasa a TODOS los ``record_audit_worker`` y a todos
    los ``log.warning/info`` (vía ``extra=``). Permite correlación
    end-to-end entre ``audit_logs`` y logs estructurados (Loki).
    """
    cid = make_worker_correlation_id()
    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if cam is None:
            log.warning(
                "ping_camera: cámara %s no encontrada",
                camera_id,
                extra={"correlation_id": cid, "camera_id": camera_id},
            )
            return {"status": "missing"}

        frame = asyncio.run(grab_frame(cam))
        if frame is None:
            # Cámara caída (RTSP inválido, timeout, codec desconocido).
            # Sprint CAMERA_OFFLINE: NO enviamos a OCR — el placeholder
            # contaminaría el detector de OCR_FAILED. Distinguimos:
            # cámara caída = CRITICAL al admin; OCR vacío = WARN al gestor.
            record_camera_offline(cam, kind="frame")
            # Sprint Fase 3B: audit del evento crítico con ip="worker".
            try:
                record_audit_worker(
                    db,
                    action="camera_offline_frame",
                    parking_id=cam.parking_id,
                    resource=f"cameras/{cam.id}",
                    payload={"code": cam.code},
                    result="failure",
                    correlation_id=cid,
                )
                db.commit()
            except Exception as exc:
                log.warning("ping_camera: audit no persistido camera=%s: %s",
                            cam.id, exc)
                db.rollback()
            # Resetear OCR counter: este fallo NO es de OCR.
            reset_ocr_failure(cam.id)
            log.warning(
                "ping_camera: id=%s code=%s CAMERA_OFFLINE (frame=None)",
                cam.id,
                cam.code,
                extra={
                    "correlation_id": cid,
                    "camera_id": cam.id,
                    "camera_code": cam.code,
                },
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
            log.warning(
                "ping_camera: OCR no disponible: %s", exc,
                extra={"correlation_id": cid, "camera_id": cam.id},
            )
            hits = []

        if not hits:
            # Sin lecturas: notificar al detector de N consecutivos.
            # Internamente, después de N (settings.ocr_frames_before_fail)
            # creará una alerta + email + guardará el frame en /tmp/ocr-failed.
            new_alert = record_ocr_failure(cam, frame)
            # Sprint Fase 3B-parte-2 (2026-07-01): si ``record_ocr_failure``
            # acaba de crear la alerta (umbral cruzado + lock libre),
            # dejamos constancia en ``audit_logs``. ``user_id=None`` e
            # ``ip="worker"`` los fija ``record_audit_worker``. El payload
            # lleva camera_id + camera_code para correlación con el Alert
            # subyacente (``alerts/{id}`` en resource).
            if new_alert is not None:
                try:
                    record_audit_worker(
                        db,
                        action="ocr_failure_consecutive",
                        parking_id=cam.parking_id,
                        resource=f"alerts/{new_alert.id}",
                        payload={
                            "camera_id": cam.id,
                            "camera_code": cam.code,
                            "consecutive_fails": (
                                new_alert.context or {}
                            ).get("consecutive_fails"),
                        },
                        result="failure",
                        correlation_id=cid,
                    )
                    db.commit()
                except Exception as exc:
                    log.warning(
                        "ping_camera: audit ocr_failure_consecutive no "
                        "persistido camera=%s: %s",
                        cam.id, exc,
                    )
                    db.rollback()
            log.info(
                "ping_camera: id=%s code=%s source=rtsp plates_found=0",
                cam.id,
                cam.code,
                extra={"correlation_id": cid, "camera_id": cam.id},
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
            log.warning(
                "ping_camera: error en ingest_service: %s", exc,
                extra={"correlation_id": cid, "camera_id": cam.id},
            )
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
                extra={
                    "correlation_id": cid,
                    "camera_id": cam.id,
                    "created": created,
                    "closed": closed,
                },
            )
        else:
            log.info(
                "ping_camera: id=%s code=%s source=rtsp plates_found=%s",
                cam.id,
                cam.code,
                len(hits),
                extra={"correlation_id": cid, "camera_id": cam.id},
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


@celery_app.task(name="solidapp.cleanup_failed_frames")  # type: ignore[untyped-decorator]
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


@celery_app.task(name="solidapp.purge_audit_logs")  # type: ignore[untyped-decorator]
def purge_audit_logs(retention_days: int | None = None) -> dict[str, Any]:
    """Borra ``audit_logs`` con ``created_at < now - retention_days``.

    Sprint Fase 3C (2026-07-01). Defensivo: ``db.commit()`` envuelto en
    try/except, NUNCA propaga. Idempotente: si no hay nada que borrar
    devuelve ``{deleted: 0}``. Necesita el índice ``ix_audit_logs_created_at``
    añadido en migración 0008.

    Si ``retention_days`` es ``None`` usa ``settings.audit_log_retention_days``
    (default 365). Aceptar el kwarg permite pasar valores distintos en
    tests sin tocar settings.
    """
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.audit_log_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = db.query(AuditLog).filter(
            AuditLog.created_at < cutoff,
        ).delete(synchronize_session=False)
        db.commit()
        log.info(
            "purge_audit_logs: days=%s cutoff=%s deleted=%s",
            days, cutoff.isoformat(), deleted,
        )
        return {
            "deleted": deleted,
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("purge_audit_logs: error (%s)", exc)
        db.rollback()
        return {
            "deleted": 0,
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "error": str(exc),
        }
    finally:
        db.close()


@celery_app.task(name="solidapp.probe_heartbeats")  # type: ignore[untyped-decorator]
def probe_heartbeats() -> dict[str, Any]:
    """Heartbeat batch: sondea todas las cámaras activas cada 60 s.

    Para cada cámara:
      - Skipea si su ``rtsp_url`` empieza por algún prefijo de
        ``settings.heartbeat_skip_url_prefixes`` (típicamente
        ``rtsp://demo.invalid`` del seed local).
      - Si ``probe_camera(cam)`` pasa → ``reset_camera_offline(cam.id)``.
      - Si falla → ``record_camera_offline(cam, kind="heartbeat")``,
        que incrementa el contador Redis y crea alerta CRITICAL al
        admin tras ``settings.heartbeat_failures_before_alert`` fallos.
      - Persiste ``last_heartbeat_at`` y ``last_heartbeat_ok`` en BD
        (sprint Camera Health 2026-07-01) para que el endpoint
        ``GET /cameras/{id}/health`` pueda derivar el estado.

    Una sola tarea batch (no una por cámara). Si el sistema tiene
    50 cámaras y cada probe tarda ~1 s, la ronda tarda ~50 s. Está
    bien: el threshold mide fallos consecutivos, no ventana de tiempo.

    ``ping_camera`` sigue corriendo en paralelo con ``kind="frame"``;
    ambos comparten el lock de 1 h de CAMERA_OFFLINE, así que sólo
    se crea UNA alerta cuando hay caída real (no doble).

    Sprint Fase 3C (2026-07-01): un único ``correlation_id`` por
    invocación se propaga a TODOS los audit_logs + logs estructurados
    de esta ronda (coherente con ``ping_camera``).
    """
    cid = make_worker_correlation_id()
    settings = get_settings()
    skip_prefixes: tuple[str, ...] = tuple(
        settings.heartbeat_skip_url_prefixes or ()
    )

    db = SessionLocal()
    probed = skipped = ok = failed = 0
    health_updates = 0
    now_utc = datetime.now(timezone.utc)
    # Sprint O2 (2026-07-06): cambios de health por cámara, publicados
    # tras el commit. Estructura: list[(parking_id, camera_id, last_ok)].
    health_changes: list[tuple[int, int, bool]] = []
    try:
        cams = (
            db.query(Camera)
            .filter(Camera.is_active.is_(True))
            .order_by(Camera.id)
            .all()
        )

        # ── Sondeo EN PARALELO (T-13+4) ────────────────────────────────
        # Antes se sondeaba de uno en uno, con un ``asyncio.run()`` por
        # cámara: con 50 cámaras y 5 s de timeout por cámara la ronda
        # tardaba hasta ~250 s y **monopolizaba un slot del pool** de
        # Celery. El healthcheck (``celery inspect ping``) no se
        # respondía en 10 s, el contenedor pasaba a *unhealthy* y en
        # Swarm/K8s el worker se reiniciaba en bucle sin llegar a
        # terminar la ronda.
        #
        # ``probe_camera`` es async y delega en ``to_thread``, así que
        # ``gather`` las sondea a la vez; el nº de threads concurrentes
        # lo limita el propio pool de asyncio (min(32, cpu+4)).
        candidatas = [
            cam
            for cam in cams
            if not any(cam.rtsp_url.startswith(p) for p in skip_prefixes)
        ]
        skipped = len(cams) - len(candidatas)
        probed = len(candidatas)

        async def _sondear_todas() -> list[bool]:
            resultados = await asyncio.gather(
                *(probe_camera(cam) for cam in candidatas),
                return_exceptions=True,
            )
            salida: list[bool] = []
            for cam, resultado in zip(candidatas, resultados, strict=True):
                if isinstance(resultado, BaseException):
                    log.warning(
                        "probe_heartbeats: probe lanzó excepción camera=%s: %s",
                        cam.id,
                        resultado,
                    )
                    salida.append(False)
                else:
                    salida.append(bool(resultado))
            return salida

        estados = asyncio.run(_sondear_todas()) if candidatas else []

        for cam, is_alive in zip(candidatas, estados, strict=True):
            # Persistir último probe en BD (sprint Camera Health).
            # Commit batch al final del bucle para evitar 50 commits/min
            # de churn en el WAL de Postgres.
            # Sprint O2: capturar el valor previo para detectar cambios.
            prev_ok = cam.last_heartbeat_ok
            cam.last_heartbeat_at = now_utc
            cam.last_heartbeat_ok = is_alive
            db.add(cam)
            health_updates += 1
            # Cambio de estado (incluye None → bool): publicar tras commit.
            if prev_ok != is_alive:
                health_changes.append((cam.parking_id, cam.id, is_alive))

            if is_alive:
                ok += 1
                reset_camera_offline(cam.id)
            else:
                failed += 1
                # ``record_camera_offline`` incrementa el contador y crea
                # la alerta CRITICAL sólo si supera el threshold. Si el
                # lock de 1 h está tomado (porque ``ping_camera`` ya
                # disparó), omite.
                record_camera_offline(cam, kind="heartbeat")
                # Sprint Fase 3B: audit del evento crítico con ip="worker".
                try:
                    record_audit_worker(
                        db,
                        action="camera_offline_heartbeat",
                        parking_id=cam.parking_id,
                        resource=f"cameras/{cam.id}",
                        payload={"code": cam.code},
                        result="failure",
                        correlation_id=cid,
                    )
                except Exception as exc:
                    log.warning(
                        "probe_heartbeats: audit no persistido camera=%s: %s",
                        cam.id, exc,
                        extra={"correlation_id": cid, "camera_id": cam.id},
                    )

        # Commit batch de los health fields. Si falla, se hace rollback
        # silencioso: el worker NUNCA propaga, y la siguiente ronda del
        # beat (60 s después) sobrescribirá cualquier valor obsoleto.
        if health_updates:
            try:
                db.commit()
            except Exception as exc:  # noqa: BLE001 — defensiva
                log.warning(
                    "probe_heartbeats: fallo en commit health fields (%s updates): %s",
                    health_updates, exc,
                )
                db.rollback()
    finally:
        db.close()

    # Sprint O2 (2026-07-06): publicar cambios de health en bus SSE.
    # Fire-and-forget (publish ya es defensivo: un fallo de Redis no
    # rompe el worker). FUERA del `try/finally` para no anidar con el
    # cierre de sesión.
    for parking_id, camera_id, last_ok in health_changes:
        publish_event(
            parking_id,
            EventType.CAMERA_HEALTH_CHANGED,
            {"camera_id": camera_id, "last_ok": last_ok},
        )

    log.info(
        "probe_heartbeats: probed=%s skipped=%s ok=%s failed=%s threshold=%s health_updates=%s",
        probed, skipped, ok, failed, settings.heartbeat_failures_before_alert,
        health_updates,
        extra={
            "correlation_id": cid,
            "probed": probed,
            "ok": ok,
            "failed": failed,
        },
    )
    return {"probed": probed, "skipped": skipped, "ok": ok, "failed": failed}
