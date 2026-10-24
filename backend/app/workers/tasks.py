"""Tareas Celery reales (sustituyen al heartbeat placeholder de Fase 1).

Estado en MVP (Fase 2 cerrada):
- `tick_cameras` consulta el modelo Camera y loguea totales.
- `ping_cameras` (T-177, 2026-10-24) es el **despacho**: cada 10 min
  (ajuste `PING_CAMERA_INTERVAL_SECONDS`) encola un `ping_camera` por
  cada cámara activa. Va en el `beat_schedule` de `celery_app.py`.
- `ping_camera` distingue dos modos de fallo (sprint CAMERA_OFFLINE):
    * `grab_frame` devuelve ``None`` → cámara caída: alerta CRITICAL al
      admin, NO se envía a OCR. Resetea el contador de OCR_FAILED para
      que el fallback al placeholder 1×1 no contamine la métrica.
    * `grab_frame` devuelve bytes pero OCR no detecta → OCR_FAILED,
      alerta WARN al gestor (igual que en sprint ALERTAS).
  El frame se persiste en `plates_detected` cuando hay lecturas y se
  envía a `process_plate_hits` para crear/cerrar tickets.
- `cleanup_failed_frames` purga los frames con más de N días de **los
  dos** directorios: /tmp/ocr-failed (el normal) y /tmp/solidapp-alerts-test
  (el de respaldo, T-168). Idempotente y seguro aunque estén vacíos.

`ping_camera` NUNCA lanza excepción: si el servicio OCR no responde,
la tarea registra `plates_found=0` en el log y **no** cuenta un fallo
de OCR (T-177: un servicio caído no dice nada de las cámaras; si no,
51 cámaras caídas daría 51 alarmas por un solo servicio roto). La app
prefiere un "no hay lectura" a un 500 cuando OCR está caído.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.audit import AuditLog
from app.models.parking import Camera
from app.models.password_reset_token import PasswordResetToken
from app.models.plates_detected import PlatesDetected
from app.services.alerts import (
    FALLBACK_FRAMES_DIR,
    FAILED_FRAMES_DIR,
    una_vez_por_hora,
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
from app.services.plates import parece_matricula
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

# Retención de frames fallidos (días) — corte limpio cada pasada.
FAILED_FRAMES_RETENTION_DAYS = 30
#: Directorio **normal** de los frames fallidos (el que escribe
#: ``alerts._save_frame``).
DEFAULT_OCR_FAILED_DIR = FAILED_FRAMES_DIR
#: Directorio de **respaldo** (donde caen los frames cuando el normal no
#: se puede escribir). T-168: antes esta tarea sólo purgaba el normal, y
#: los frames del respaldo se quedaban **para siempre**.
FALLBACK_OCR_FAILED_DIR = FALLBACK_FRAMES_DIR


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


async def _reconocer(ocr: Any, frame: bytes) -> tuple[list[Any], bool, str]:
    """Llama al OCR y devuelve ``(hits, respondio, motivo)``.

    ``respondio`` dice si el servicio OCR dio una **respuesta
    utilizable** (HTTP 200 con una lista): es la diferencia entre «el OCR
    no leyó nada» (problema de la cámara) y «el OCR no dio una respuesta
    utilizable» (problema del servicio, que no dice nada de la cámara).

    ``motivo`` explica el por qué (``no_disponible``, ``status_400``,
    ``no_json``, ``formato``, ``sin_lecturas``…): sin él, el log diría
    «el OCR no respondió» también cuando lo que pasó es que el servicio
    **contestó y rechazó la imagen**.

    T-177: si el cliente no sabe decirlo (p.ej. el doble de un test que
    sólo implementa ``recognize``), se asume que respondió: es el
    comportamiento de siempre y no se puede acusar a una cámara sin
    pruebas.
    """
    reconocer = getattr(ocr, "reconocer", None)
    if callable(reconocer):
        resultado = await reconocer(frame)
        return (
            list(resultado.hits),
            bool(resultado.respondio),
            str(getattr(resultado, "motivo", "") or ""),
        )
    hits = await ocr.recognize(frame)
    return list(hits), True, ""


#: ``ignore_result=True`` (T-177): el ping es de «dispara y olvida»
#: —nadie lee su resultado— y el fan-out encola **51** mensajes por
#: ronda. Sin esto, cada publicación abre conexion con el result
#: store para reservar sitio, y con ese Redis lento la llamada se
#: queda reintentando (medido el 2026-10-23: **23 s** por envio,
#: T-103): el fan-out entero se quedaria bloqueado.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="solidapp.ping_camera", ignore_result=True,
)
def ping_camera(camera_id: int, token: str | None = None) -> dict[str, Any]:
    """Envía un frame al servicio OCR y persiste los hits detectados.

    Captura un frame real del stream RTSP de la cámara (vía
    `app.services.cameras.capture.grab_frame`). Si la captura falla —
    URL inválida, cámara caída, timeout — **no** se envía nada al OCR:
    se avisa de la cámara caída (``record_camera_offline``) y se
    resetea el contador de fallos de OCR (a la cámara no le vale la
    pena el OCR si no hay frame). Si la captura va bien, el frame se
    envía a `ocr:8800/recognize` y los hits se persisten en
    `plates_detected`.

    T-177 (2026-10-24): se distingue **«el OCR no respondió»** de
    **«el OCR respondió y no leyó nada»**. Lo primero es un problema
    del servicio y **no** cuenta como fallo de OCR (si no, un servicio
    caído daría una alarma ``OCR_FAILED`` por cámara: 51 en este
    repo). Lo segundo sí: es un problema de la cámara.

    ``token`` es el del lock por cámara que tomó ``ping_cameras`` al
    encolar este ping: al terminar, la cámara queda libre para la
    siguiente ronda.

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
            hits, respondio, motivo = asyncio.run(_reconocer(ocr, frame))
        except Exception as exc:  # noqa: BLE001
            # OcrClient no debería lanzar, pero blindamos la tarea
            # igualmente: un fallo del worker no debe romper el beat.
            log.warning(
                "ping_camera: OCR no disponible: %s", exc,
                extra={"correlation_id": cid, "camera_id": cam.id},
            )
            hits, respondio, motivo = [], False, "error"

        if not respondio:
            # T-177 (2026-10-24): el servicio OCR **no respondió**. Esto
            # no dice NADA de la cámara: si lo contáramos como fallo de
            # OCR, un servicio caído daría una alarma OCR_FAILED por
            # cámara (51 en este repo): ruido falso que culpa a las
            # cámaras de un problema que es del servicio.
            reset_ocr_failure(cam.id)
            log.error(
                "ping_camera: id=%s code=%s el servicio OCR no dio una "
                "respuesta utilizable (motivo=%s); no se cuenta como "
                "fallo de OCR de la cámara",
                cam.id, cam.code, motivo or "desconocido",
                extra={"correlation_id": cid, "camera_id": cam.id},
            )
            return {
                "status": "ocr_no_disponible",
                "motivo": motivo or "desconocido",
                "code": cam.code,
                "plates_found": 0,
            }

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

        # El OCR devuelve TEXTO, no matrículas: también lee el timestamp
        # quemado de la cámara o el rótulo de la marca (2026-10-22). Con
        # el vídeo de QA del repo devolvió "t=105.0sframe=2625". Se
        # filtra ANTES de persistir: la columna ``plates_detected.plate``
        # es de 16 caracteres, así que un texto más largo revienta el
        # INSERT, y uno más corto crearía un vehículo fantasma.
        hits_validos = []
        for h in hits:
            if not parece_matricula(h.plate):
                log.warning(
                    "ping_camera: el OCR no leyó una matrícula (se ignora): %r",
                    h.plate,
                    extra={"correlation_id": cid, "camera_id": cam.id},
                )
                continue
            hits_validos.append(h)
        if len(hits_validos) != len(hits):
            log.info(
                "ping_camera: id=%s code=%s leídos=%s descartados=%s (no eran matrículas)",
                cam.id,
                cam.code,
                len(hits),
                len(hits) - len(hits_validos),
                extra={"correlation_id": cid, "camera_id": cam.id},
            )

        now = datetime.now(timezone.utc)
        for h in hits_validos:
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
            ingest_results = process_plate_hits(hits_validos, cam)
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
                "ping_camera: id=%s code=%s source=rtsp plates_found=%s "
                "tickets_created=%s tickets_closed=%s",
                cam.id,
                cam.code,
                len(hits_validos),
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
                "ping_camera: id=%s code=%s source=rtsp plates_found=%s "
                "descartadas=%s",
                cam.id,
                cam.code,
                len(hits_validos),
                len(hits) - len(hits_validos),
                extra={"correlation_id": cid, "camera_id": cam.id},
            )
        return {
            "status": "ok",
            "code": cam.code,
            "source": "rtsp",
            # Matrículas **válidas** (las que el OCR leyó y que además
            # tienen forma de matrícula). Las descartadas van aparte: no
            # son matrículas, son texto quemado en la imagen.
            "plates_found": len(hits_validos),
            "plates_descartadas": len(hits) - len(hits_validos),
            "tickets_created": created,
            "tickets_closed": closed,
        }
    finally:
        db.close()
        # T-177: el lock por cámara (lo tomó ``ping_cameras`` al
        # encolar este ping) se suelta **si sigue siendo nuestro**, para
        # que la cámara pueda volver a pingarse en la siguiente ronda.
        if token is not None:
            _soltar_lock(f"ping_camera:{camera_id}", token)


@celery_app.task(name="solidapp.ping_cameras")  # type: ignore[untyped-decorator]
def ping_cameras() -> dict[str, Any]:
    """Despacha un ping a **cada cámara activa** (T-177, 2026-10-24).

    Decisión de producto (2026-10-24): el ping a las cámaras pasa a
    ir **cada 10 minutos** (ajuste ``PING_CAMERA_INTERVAL_SECONDS``,
    por defecto 600 s). Esta tarea es la que vive en el
    ``beat_schedule``; ella encola un ``solidapp.ping_camera`` por
    cámara.

    POR QUÉ el heartbeat no basta: el heartbeat sondea cada 60 s las
    cámaras que **no** skipea (``HEARTBEAT_SKIP_URL_PREFIXES``) y crea
    la alarma ``CAMERA_OFFLINE``, así que la **liveness** del stream
    RTSP ya está cubierta. Lo que el ping añade es el **viaje al OCR**
    (detectar el motor OCR muerto aunque el push del fabricante siga
    llegando) y una segunda fuente de matrículas.

    Las **dos** sondas respetan la misma lista de URLs que se saltan
    (T-177, integración): en desarrollo el seed apunta a
    ``rtsp://demo.invalid`` a propósito, y pingear 49 cámaras de mentira
    generaba 49 alertas ``CAMERA_OFFLINE`` por hora. En **producción** la
    lista está vacía (el compose de producción no la define), así que
    allí se sigue comprobando **todas** las cámaras: una cámara caída
    tiene que dar la cara.

    Resiliente: una cámara que falle al encolarse **no** impide
    encolar las demás.

    No se acumula: si el ping de una cámara ya está encolado o en
    marcha, no se encola otro (lock por cámara en Redis, con TTL
    igual al intervalo). Sin esto, con una cámara colgada la cola se
    llenaba sola.
    """
    settings = get_settings()
    intervalo = settings.ping_camera_interval_seconds
    cid = make_worker_correlation_id()

    # Lock de **ronda**: dos rondas a la vez duplicarían los pings.
    token_ronda = _tomar_lock("ping_cameras", ttl=intervalo)
    if token_ronda is None:
        log.info(
            "ping_cameras: ya hay una ronda en curso; se omite esta",
            extra={"correlation_id": cid},
        )
        return {
            "omitida": True,
            "motivo": "ronda_en_curso",
            "encoladas": 0,
            "omitidas": 0,
            "camaras": 0,
            "intervalo": intervalo,
        }

    encoladas = 0
    omitidas = 0
    saltadas = 0
    camaras = 0
    # Las URLs que las sondas de cámara se saltan (en desarrollo, las
    # cámaras de mentira del seed). La misma lista que usa el heartbeat.
    skip_prefixes = tuple(settings.heartbeat_skip_url_prefixes_list)
    try:
        db = SessionLocal()
        try:
            cams = (
                db.query(Camera)
                .filter(Camera.is_active.is_(True))
                .order_by(Camera.id)
                .all()
            )
        finally:
            db.close()
        camaras = len(cams)
        for cam in cams:
            if skip_prefixes and (cam.rtsp_url or "").startswith(skip_prefixes):
                saltadas += 1
                continue
            token_cam = make_worker_correlation_id()
            if _tomar_lock(
                f"ping_camera:{cam.id}", ttl=intervalo, token=token_cam
            ) is None:
                # Ya hay un ping de esta cámara encolado o en marcha.
                omitidas += 1
                continue
            try:
                ping_camera.delay(cam.id, token_cam)
                encoladas += 1
            except Exception as exc:  # noqa: BLE001 — defensiva
                # Una cámara que falla NO impide encolar las demás.
                log.warning(
                    "ping_cameras: no se pudo encolar el ping de la "
                    "cámara %s: %s", cam.id, exc,
                    extra={"correlation_id": cid, "camera_id": cam.id},
                )
                omitidas += 1
                _soltar_lock(f"ping_camera:{cam.id}", token_cam)
    finally:
        _soltar_lock("ping_cameras", token_ronda)

    log.info(
        "ping_cameras: camaras=%s encoladas=%s omitidas=%s saltadas=%s "
        "intervalo=%s",
        camaras, encoladas, omitidas, saltadas, intervalo,
        extra={
            "correlation_id": cid,
            "encoladas": encoladas,
            "omitidas": omitidas,
            "saltadas": saltadas,
        },
    )
    return {
        "encoladas": encoladas,
        "omitidas": omitidas,
        "saltadas": saltadas,
        "camaras": camaras,
        "intervalo": intervalo,
    }


#: ``ignore_result=True`` por lo mismo que ``send_alert_email``: el
#: que encola el correo de reset no mira el resultado, y abrir el
#: result store en la publicacion puede bloquearlo (T-103).
@celery_app.task(  # type: ignore[untyped-decorator]
    name="solidapp.send_password_reset_email", ignore_result=True,
)
def enviar_correo_reset(
    to_email: str,
    full_name: str,
    raw_token: str,
    expires_minutes: int,
    token_id: int,
) -> dict[str, Any]:
    """Envia el correo de reset de contrasena (T-94).

    Vive en una tarea de Celery para que el SMTP **no** este dentro del
    ciclo del request: con un SMTP lento, la peticion de
    forgot-password tardaba **5,03 s** (medido el 2026-10-23 con un SMTP
    de mentira que acepta la conexion y no contesta) y bloqueaba el
    worker de la API.

    Si el envio falla, el token se borra: un token que el usuario nunca
    recibio no debe quedar valido en la base de datos.
    """
    from app.services.password_reset_email import (
        send_password_reset_email as _enviar,
    )

    enviado = _enviar(
        to_email=to_email,
        full_name=full_name,
        raw_token=raw_token,
        expires_minutes=expires_minutes,
    )
    if not enviado:
        with SessionLocal() as db:
            fila = db.get(PasswordResetToken, token_id)
            if fila is not None:
                db.delete(fila)
                db.commit()
        log.error(
            "enviar_correo_reset: no se pudo enviar el correo a %s "
            "(token %s eliminado)",
            to_email, token_id,
        )
    return {"enviado": enviado, "token_id": token_id}


#: ``ignore_result=True``: estas tareas son de "dispara y olvida" (el
#: que encola no mira el resultado). Sin esto, al publicar el mensaje
#: Celery abre conexion con el **result store** para reserving sitio
#: para el resultado: si ese Redis no responde, la llamada se queda
#: reintentando (medido el 2026-10-23: **23 s** por envio, que es
#: PEOR que el SMTP que queria quitar) y el que encola (la ronda de
#: heartbeat) se queda bloqueado.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="solidapp.send_alert_email", ignore_result=True,
)
def enviar_correo_alerta(
    alert_id: int,
    destinatario: str | None,
    template_kind: str = "ocr_failed",
    parking_name: str = "",
    camera_code: str = "",
    count: int = 0,
    threshold: int = 0,
    frame_path: str | None = None,
) -> dict[str, Any]:
    """Envia el correo de una alerta FUERA de la ronda (T-103).

    La ronda de heartbeat mandaba el correo en linea: con el SMTP lento,
    cada alerta caida costaba **2,42 s** (medido el 2026-10-23) y con 50
    camaras caidas la ronda tardaba mas de dos minutos, con el beat
    lanzandola cada 60 s (se solapaba sola).

    Aqui el SMTP lo toca el worker, que es quien puede tardar sin que
    nadie se entere.
    """
    from app.models.audit import Alert
    from app.services.email import send_alert_email

    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None:
            log.warning(
                "enviar_correo_alerta: la alerta %s ya no existe", alert_id,
            )
            return {"enviado": False, "motivo": "alerta_no_existe"}
        enviado = send_alert_email(
            alert,
            destinatario,
            template_kind=template_kind,  # type: ignore[arg-type]
            parking_name=parking_name,
            camera_code=camera_code,
            count=count,
            threshold=threshold,
            frame_path=frame_path,
        )
    return {"enviado": enviado, "alert_id": alert_id}


@celery_app.task(name="solidapp.purge_incident_attachments")  # type: ignore[untyped-decorator]
def purgar_adjuntos_incidentes(retention_days: int | None = None) -> dict[str, Any]:
    """Purga las fotos de incidentes que han pasado la retencion (T-95).

    Antes esto era un script manual (``python -m
    app.scripts.purge_incident_attachments``) que nadie se acordaba de
    lanzar: la retencion existia en el papel y no en los hechos. Y
    mientras tanto, la foto caducada **se seguia sirviendo** al
    descargarla (T-95 lo cierra tambien en el endpoint).

    Idempotente: si no hay nada que borrar, ``deleted=0``.
    """
    from app.services.incident_attachments import purgar_adjuntos_vencidos

    with SessionLocal() as db:
        resultado = purgar_adjuntos_vencidos(db, retention_days=retention_days)
    log.info("purga de adjuntos de incidentes: %s", resultado)
    # T-141 (2026-10-24): si el worker no ve el volumen de adjuntos, la
    # purga borra las filas pero los ficheros se quedan en el disco del
    # backend: la retencion no se cumple y la tarea decia `deleted: N` como
    # si todo hubiera ido bien. Aqui se grita.
    faltantes = resultado.get("files_absent_of_live", 0)
    if faltantes:
        log.error(
            "purga de adjuntos de incidentes: %s fichero(s) de adjuntos vivos "
            "no estan en el volumen de este worker. El montaje de "
            "'incident_attachments' NO es el del backend: la retencion de "
            "%s dias NO se esta cumpliendo.",
            faltantes, resultado.get("retention_days"),
        )
    return dict(resultado)


@celery_app.task(name="solidapp.purge_orphan_attachments")  # type: ignore[untyped-decorator]
def purgar_adjuntos_huerfanos(min_age_hours: int = 1) -> dict[str, Any]:
    """Recoge del volumen los ficheros que ya no tiene ninguna fila (T-141).

    Antes esta funcion existed pero **nadie la llamaba**: no habia tarea
    de Celery ni entrada en el beat. Es decir, cualquier fichero que se
    quedara sin fila (un borrado a medias, la purga de retencion con el
    volumen equivocado) se quedaba en disco **para siempre**.

    Idempotente. Con ``min_age_hours=1`` (por defecto) no toca los
    ficheros recientes: ``crear_adjunto`` escribe el fichero antes de
    crear la fila, y hay una ventana en la que un fichero recien subido
    todavia no tiene ninguna.
    """
    from app.services.incident_attachments import purgar_ficheros_huerfanos

    with SessionLocal() as db:
        resultado = purgar_ficheros_huerfanos(db, min_age_hours=min_age_hours)
    log.info("barrida de adjuntos huerfanos: %s", resultado)
    faltantes = resultado.get("files_absent_of_live", 0)
    if faltantes:
        log.error(
            "barrida de adjuntos huerfanos: %s fichero(s) de adjuntos vivos "
            "no estan en el volumen de este worker: el montaje de "
            "'incident_attachments' NO es el del backend",
            faltantes,
        )
    return dict(resultado)


@celery_app.task(name="solidapp.auto_close_tickets")  # type: ignore[untyped-decorator]
def auto_close_tickets(horas: int = 24) -> dict[str, Any]:
    """Cierra las estancias cuya salida no se ha visto (T-124).

    Decision de producto (2026-10-24): auto-cierre a las 24 h con el
    importe estimado y aviso al cliente. Antes el ticket se quedaba
    activo para siempre, con importe 0.

    El cierre usa la **unica** implementacion del repo
    (``cerrar_ticket``), que es condicional: si la camara se adelanta y
    cierra el ticket, aqui no se pisa nada.
    """
    from app.services.email import encolar_correo_cierre_automatico
    from app.services.ticket_auto_close import auto_cerrar_tickets_sin_salida

    with SessionLocal() as db:
        resultado = auto_cerrar_tickets_sin_salida(db, horas=horas)

    for aviso in resultado.get("avisos", []):
        encolar_correo_cierre_automatico(**aviso)

    log.info("auto-cierre de estancias: %s", resultado)
    return dict(resultado)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="solidapp.enviar_correo_cierre_automatico", ignore_result=True
)
def enviar_correo_cierre_automatico(
    *,
    to_email: str,
    plate: str,
    parking_name: str,
    ticket_id: int,
    entry_at: str,
    exit_at: str,
    amount: float,
    discount: float,
    total: float,
) -> dict[str, Any]:
    """Manda al cliente el aviso de que su estancia se ha cerrado sola (T-124)."""
    from app.services.email import send_auto_close_email

    enviado = send_auto_close_email(
        to_email=to_email,
        plate=plate,
        parking_name=parking_name,
        entry_at=entry_at,
        exit_at=exit_at,
        amount=amount,
        discount=discount,
        total=total,
        ticket_id=ticket_id,
    )
    return {"enviado": enviado, "ticket_id": ticket_id}


@celery_app.task(name="solidapp.check_camera_pushes")  # type: ignore[untyped-decorator]
def check_camera_pushes(minutes: int | None = None) -> dict[str, Any]:
    """Avisa de las camaras que han dejado de empujar lecturas (T-164).

    El push externo es el camino real de datos y no tenia ninguna
    vigilancia: si la camara (o el OCR del fabricante) dejan de hablar,
    no saltaba nada y se seguia sin cobrar, en silencio.

    Con el mismo patron de «una vez por hora» que las demas alarmas, para
    no avisar en cada vuelta.
    """
    from app.models.audit import Alert
    from app.models.enums import AlertSeverity, AlertType
    from app.models.parking import Parking
    from app.services.alerts import una_vez_por_hora
    from app.services.camera_push_watch import camaras_sin_push
    from app.services.email import encolar_correo_alerta

    settings = get_settings()
    minutos = (
        settings.camera_push_silence_minutes if minutes is None else minutes
    )
    skip_prefixes = tuple(settings.heartbeat_skip_url_prefixes_list)

    with SessionLocal() as db:
        silenciosas = camaras_sin_push(
            db, minutos_max=minutos, skip_prefixes=skip_prefixes
        )
        created = 0
        for camera, ultimo in silenciosas:
            if not una_vez_por_hora(f"camera:{camera.id}:push_silent_alert"):
                continue
            desde = (
                "nunca ha enviado lecturas"
                if ultimo is None
                else f"no envia lecturas desde {ultimo.isoformat()}"
            )
            alert = Alert(
                parking_id=camera.parking_id,
                type=AlertType.CAMERA_PUSH_SILENT,
                severity=AlertSeverity.CRITICAL,
                message=(
                    f"Cámara {camera.code} sin lecturas — {desde} "
                    f"(más de {minutos} min)"
                ),
                context={
                    "camera_id": camera.id,
                    "camera_code": camera.code,
                    "minutos_sin_push": minutos,
                    "ultimo_push": ultimo.isoformat() if ultimo else None,
                },
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            created += 1
            parking = db.get(Parking, camera.parking_id)
            encolar_correo_alerta(
                alert_id=alert.id,
                destinatario=None,
                template_kind="camera_offline",
                camera_code=camera.code,
                parking_name=parking.name if parking else "",
                count=minutos,
                threshold=minutos,
            )
            log.warning(
                "check_camera_pushes: alerta %s camera=%s sin lecturas",
                alert.id,
                camera.code,
            )

    log.info(
        "check_camera_pushes: silenciosas=%s alertas=%s minutos=%s",
        len(silenciosas),
        created,
        minutos,
    )
    return {
        "silenciosas": len(silenciosas),
        "alertas": created,
        "minutos": minutos,
    }


@celery_app.task(name="solidapp.cleanup_failed_frames")  # type: ignore[untyped-decorator]
def cleanup_failed_frames() -> dict[str, int]:
    """Purga los frames fallidos con mtime > N días.

    Purga **los dos** directorios (T-168, 2026-10-24):

    - ``/tmp/ocr-failed``: el normal, donde guarda ``alerts._save_frame``.
    - ``/tmp/solidapp-alerts-test``: el de **respaldo**, donde caen los
      frames cuando el normal no se puede escribir. Antes esta tarea
      sólo miraba el normal, así que los frames del respaldo se
      quedaban **para siempre** (medido: un frame de 45 días seguía
      ahí después de pasar la tarea).

    Idempotente y tolerante a directorio inexistente (no falla el
    worker si todavía no se ha creado). Devuelve el recuento con el
    mismo formato que usa el resto del repo: ``{"deleted": N,
    "kept": M}`` (sumando los dos directorios).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=FAILED_FRAMES_RETENTION_DAYS)
    deleted = 0
    kept = 0
    for directorio in (DEFAULT_OCR_FAILED_DIR, FALLBACK_OCR_FAILED_DIR):
        if not directorio.exists():
            continue
        for entry in directorio.iterdir():
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


#: Filas que borra cada lote la purga de auditoria (T-104).
AUDIT_PURGE_LOTE = 5000


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
        # T-104: la purga va **en lotes**. Un solo DELETE sobre millones
        # de filas deja un WAL enorme, una transaccion larga y bloquea
        # la tabla (con el indice de created_at no es un seq scan, pero
        # el problema es el volumen).
        deleted = 0
        while True:
            lote = (
                db.query(AuditLog.id)
                .filter(AuditLog.created_at < cutoff)
                .limit(AUDIT_PURGE_LOTE)
                .all()
            )
            if not lote:
                break
            ids = [fila[0] for fila in lote]
            borrados = (
                db.query(AuditLog)
                .filter(AuditLog.id.in_(ids))
                .delete(synchronize_session=False)
            )
            db.commit()
            deleted += borrados
            if borrados == 0:
                break
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


@celery_app.task(name="solidapp.purge_ghost_vehicles")  # type: ignore[untyped-decorator]
def purge_ghost_vehicles(max_age_hours: int | None = None) -> dict[str, Any]:
    """Borra los vehiculos «fantasma» (T-125).

    Un vehiculo fantasma es el que creo la ingesta (matricula
    desconocida) y que se quedo **sin dueno y sin ticket**: la plaza
    estaba ocupada, o averiada, o la camara no tenia geocerca
    calibrada. Nadie los borraba, asi que la tabla ``vehicles`` crecia
    sin limite.

    Medido el 2026-10-23 en la base de datos de QA: 3 vehiculos con cero
    duenos y cero tickets, creados el 2026-06-30, sin ninguna tarea que
    los purgara.

    Idempotente: si no hay nada que borrar devuelve ``deleted=0``.
    """
    from app.services.vehicle_purge import purgar_vehiculos_fantasma

    with SessionLocal() as db:
        resultado = purgar_vehiculos_fantasma(db, max_age_hours=max_age_hours)
    log.info("purga de vehiculos fantasma: %s", resultado)
    return dict(resultado)


#: Tope de segundos que se guarda el lock de una tarea periodica (T-102).
#: El beat lanza ``probe_heartbeats`` cada 60 s; el lock dura el doble
#: para que una ronda larga (una camara colgada) siga protegida.
LOCK_TTL_SEGUNDOS = 120


def _redis_client() -> redis.Redis:
    """Cliente Redis de los locks (mismo patrón que ``app.services.alerts``).

    T-177: en una función aparte para que los tests puedan sustituirla
    por un Redis en memoria (y no depender de que haya un Redis en el
    entorno).
    """
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def _tomar_lock(nombre: str, ttl: int = LOCK_TTL_SEGUNDOS,
                token: str | None = None) -> str | None:
    """Toma el lock de la tarea para que no se solape consigo misma.

    POR QUE (T-102, 2026-10-23): el beat lanza la ronda de heartbeat
    **cada 60 s**, pero una ronda puede tardar mas (una camara colgada
    hace que FFmpeg tarde en abandonar el RTSP). Con dos rondas a la vez:

    - el contador de fallos de cada camara se incrementaba **dos veces
      por minuto**, asi que la alerta saltaba al double de tiempo;
    - se duplicaban las filas de auditoria y los eventos publicados;
    - dos rondas podian tomar a la vez el lock de alerta de una camara:
      el ``SET NX`` es atomico, pero el ``INCR -> comprobar -> SET NX ->
      borrar contador -> INSERT`` no lo es, y si el INSERT fallaba la
      camara se quedaba muda una hora.

    Devuelve el **token** del lock (un identificador unico de esta
    ejecucion) o ``None`` si ya hay otra ronda en curso. Si Redis no
    responde, **no** se bloquea la tarea (sin Redis no hay ni colas ni
    rate-limit): se avisa y se sigue.

    T-177 (2026-10-24): ``token`` permite que quien toma el lock lo
    **suelte despues** (la tarea que lo encolo lo suelta al
    terminar). Sin eso, el lock de una camara quedaria tomado hasta
    que caducase (600 s) y esa camara no volveria a pingarse hasta
    el doble de intervalo.
    """
    if token is None:
        token = make_worker_correlation_id()
    try:
        rds = _redis_client()
        if rds.set(f"celery:lock:{nombre}", token, nx=True, ex=ttl):
            return token
        return None
    except RedisError as exc:
        log.warning(
            "_tomar_lock: Redis no disponible (%s); se sigue sin lock", exc,
        )
        return token


def _renovar_lock(nombre: str, token: str, ttl: int = LOCK_TTL_SEGUNDOS) -> bool:
    """Renueva el TTL del lock **si sigue siendo nuestro**.

    T-150 (2026-10-24): el TTL del lock era fijo (120 s) y la ronda de
    heartbeats **no tiene duracion acotada**. Si la ronda vivia mas que
    el TTL, el lock caducaba **con la ronda viva** y la ronda siguiente
    (el beat publica cada 60 s) podia tomarlo: dos rondas a la vez, que
    es justo lo que el T-102 queria evitar.

    Se renueva en vez de ampliar el TTL a ciegas: si el worker muere, el
    lock caduca en cuanto antes y no bloquea la siguiente ronda mas de
    lo previsto.

    Devuelve ``True`` si el TTL se ha renovado (o ``False`` si el lock
    ya no es nuestro, o si Redis no responde).
    """
    clave = f"celery:lock:{nombre}"
    try:
        rds = _redis_client()
        # Atomico: si el valor de la clave no es nuestro token, no se toca.
        resultado = rds.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1, clave, token, str(ttl),
        )
        # 0 = el lock ya no es nuestro (caduco, o lo tomo otra ronda).
        return bool(resultado)
    except RedisError as exc:
        log.warning("_renovar_lock: Redis no disponible (%s)", exc)
        return False


def _soltar_lock(nombre: str, token: str) -> None:
    """Suelta el lock **solo si es el nuestro**.

    Sin esto, el lock se queda hasta que caduca (120 s) y la ronda se
    pierde una de cada tres: el beat lanza cada 60 s, la primera ronda
    toma el lock, la segunda lo encuentra tomado y la tercera lo vuelve
    a tomar (ya caducado). Con la suelta al terminar, la ronda siguiente
    puede correr enseguida.

    La comparacion es **atomica** (Lua): si el lock es de otra
    ejecucion, no se toca.
    """
    clave = f"celery:lock:{nombre}"
    try:
        rds = _redis_client()
        rds.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1, clave, token,
        )
    except RedisError as exc:
        log.warning("_soltar_lock: Redis no disponible (%s)", exc)


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

    ``ping_camera`` detectaría las caídas por ``kind="frame"`` (decodifica
    el frame entero) y comparte el lock de 1 h de CAMERA_OFFLINE con
    este detector, así que sólo se crearía UNA alerta cuando hay caída
    real (no doble).

    T-177 (2026-10-24): ``ping_camera`` **ya se despacha** (cada 10 min
    por cámara, vía ``solidapp.ping_cameras``). Los dos detectores
    comparten el lock de 1 h de ``CAMERA_OFFLINE``, así que sólo se crea
    UNA alerta cuando hay caída real (no doble).

    Sprint Fase 3C (2026-07-01): un único ``correlation_id`` por
    invocación se propaga a TODOS los audit_logs + logs estructurados
    de esta ronda (coherente con ``ping_camera``).
    """
    # T-102: si hay otra ronda en curso, esta se omite (no se solapan).
    token_lock = _tomar_lock("probe_heartbeats")
    if token_lock is None:
        log.info("probe_heartbeats: ya hay una ronda en curso; se omite esta")
        return {"omitida": True, "motivo": "ronda_en_curso"}
    cid = make_worker_correlation_id()
    settings = get_settings()
    skip_prefixes: tuple[str, ...] = tuple(
        settings.heartbeat_skip_url_prefixes_list
    )

    db = SessionLocal()
    # T-150 (2026-10-24): renovar el lock mientras la ronda vive. Sin
    # esto, una ronda mas larga que el TTL (120 s) lo pierde **con la
    # ronda en marcha** y la ronda siguiente puede tomarlo: dos rondas a
    # la vez (los danos del T-102 vuelven).
    parar_renovacion = threading.Event()

    def _renovar_en_bucle() -> None:
        while not parar_renovacion.wait(LOCK_TTL_SEGUNDOS / 3):
            if not _renovar_lock("probe_heartbeats", token_lock):
                # El lock ya no es nuestro (o Redis no responde): no hay
                # nada que renovar.
                return

    hilo_renovacion = threading.Thread(
        target=_renovar_en_bucle, name="renueva-lock-heartbeats", daemon=True,
    )
    hilo_renovacion.start()

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
                #
                # T-104: la fila se escribe **una vez por hora** y no en
                # cada ronda. Medido: en la base de QA, 5.928 de 8.763
                # filas (el 68 %) eran de este tipo, y ningun panel las
                # usa; con 50 camaras caidas serian 72.000 filas al dia.
                if not una_vez_por_hora(f"camera:{cam.id}:offline_audit_una_vez"):
                    pass
                else:
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
        # T-150: primero se para el hilo que renueva el lock, luego se
        # suelta (si no, el hilo podria renovar un lock ya soltado).
        parar_renovacion.set()
        db.close()
        # T-102: el lock se suelta al terminar la ronda (si no, se pierde
        # una de cada tres: el beat lanza cada 60 s y el lock dura 120).
        if token_lock is not None:
            _soltar_lock("probe_heartbeats", token_lock)

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
