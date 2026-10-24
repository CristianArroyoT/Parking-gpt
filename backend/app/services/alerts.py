"""Detector de N frames consecutivos sin matrícula + rate-limit de alertas.

Pipeline:

1. ``ping_camera`` (en ``app/workers/tasks.py``) llama a
   ``record_ocr_failure(camera, frame_bytes)`` cuando ``hits == []``.
2. Esta función usa Redis como contador efímero:

   - ``camera:{id}:consecutive_fails`` — contador ``INCR`` con TTL
     **renovado en cada fallo** (ventana deslizante) y **calculado a
     partir del umbral** (T-167: el TTL ya no es un número mágico).
   - ``camera:{id}:ocr_alert_lock`` — ``SET NX EX 3600`` que evita crear
     más de una alerta por hora para la misma cámara.

3. Cuando el contador supera el umbral (``ocr_frames_before_fail`` en
   settings, 5 por defecto) **y** el lock está libre, crea un registro
   ``Alert(type=OCR_FAILED, severity=WARN)`` en BD, guarda el frame en
   ``/tmp/ocr-failed/<camera>-<ts>.jpg`` y dispara el envío de email al
   gestor de la sucursal.

4. ``reset_ocr_failure(camera_id)`` borra ambas claves cuando hay una
   lectura válida — la cámara vuelve a estar "sana".

**Garantías**:

- El worker nunca propaga excepciones: cualquier error de Redis, BD o
  email se loguea y se devuelve ``None``. Coherente con la regla
  "worker nunca propaga".
- El lock por cámara evita storm de alertas si la cámara sigue caída
  24 h.
- La resolución del email del gestor (``_resolve_manager_email``) nunca
  aborta la creación de la alerta: si no hay gestor, el email se omite.

T-177 (2026-10-24): **esta ruta ya no está dormida**. La alarma
``OCR_FAILED`` la dispara ``ping_camera``, que desde el 2026-10-24 se
despacha **cada 10 min por cámara** (``solidapp.ping_cameras``, decisión
de producto). El intervalo real (``OCR_PING_INTERVAL_SECONDS`` = 600 s)
es el que se usa aquí para derivar el TTL del contador: con el ping
cada 600 s, el TTL tiene que ser **mayor** que 600 s o el contador
caducaría justo antes de que llegara el siguiente fallo (y la alarma
no saltaría nunca). Con el umbral por defecto (5) hacen falta
5 × 600 = 3000 s de fallos, así que el TTL (5 × 600 × 2 = 6000 s)
cobra holgura de sobra.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, cast

import redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType, UserRole
from app.models.parking import Camera
from app.models.user import ParkingMembership, User
from app.services import email as email_module

log = logging.getLogger(__name__)

# ── Configuración ────────────────────────────────────────────────
#: Directorio **normal** de los frames fallidos.
FAILED_FRAMES_DIR: Final[Path] = Path("/tmp/ocr-failed")
#: Directorio de **respaldo**: donde caen los frames cuando el normal no
#: se puede escribir (p.ej. tests en Windows). T-168: la tarea de
#: limpieza tiene que purgar **los dos** (si no, estos frames se
#: quedan para siempre).
FALLBACK_FRAMES_DIR: Final[Path] = Path("/tmp/solidapp-alerts-test")

# TTL del lock de "ya alertamos en la última hora".
ALERT_LOCK_TTL_SECONDS: Final[int] = 3600
#: TTL **mínimo** del contador de fallos consecutivos: por debajo de
#: esto el contador caduca entre dos fallos aunque lleguen pegados.
MIN_COUNT_TTL_SECONDS: Final[int] = 60
#: Margen sobre (umbral × intervalo esperado). Con el margen 2, la
#: ventana del contador aguanta el doble de lo que necesita.
COUNT_TTL_MARGIN: Final[int] = 2


def ttl_contador_fallos(threshold: int, intervalo_s: int) -> int:
    """TTL del contador de fallos consecutivos, coherente con el umbral.

    POR QUÉ (T-167, 2026-10-24): el TTL eran **600 s fijos**, sea cual
    fuera el umbral. El TTL se ponía **sólo en el primer ``INCR``**, o
    sea que la ventana iba desde el primer fallo. Con el umbral por
    defecto (5) eso significa que el contador tenía que aguantar 600 s
    para llegar a 5: si los fallos llegaban más espaciados que
    ``600/5 = 120 s``, el contador caducaba **antes** de poder llegar al
    umbral y **la alerta nunca saltaba**.

    Medido (2026-10-24, contra el Redis real del stack): una serie de 5
    fallos separados 3 s con un TTL de 8 s dejó el contador en 2 y **no
    creó ninguna alerta**.

    El TTL ahora se **deriva del umbral** (``umbral × intervalo
    esperado × margen``), de modo que la ventana siempre puede guardar
    los fallos que hacen falta para cruzar el umbral, y por tanto el
    TTL **cambia con el umbral** (ya no es un número mágico).

    OJO: esto **no** contradice el T-150. Allí lo que se renovaba era
    el TTL de un **lock** (exclusión mutua entre dos rondas): la ronda
    puede tardar más que el TTL, así que renovarlo mientras la ronda
    vive es lo correcto. Aquí lo que se renueva es el TTL de un
    **contador**, y la renovación es lo que convierte la ventana fija en
    **deslizante**: el contador sobrevive mientras los fallos lleguen
    separados menos que el TTL, en vez de morir en el primero que pase
    del TTL. El "consecutivo" lo sigue marcando el reset explícito
    (``reset_ocr_failure``) cuando llega una lectura válida.
    """
    if threshold <= 0 or intervalo_s <= 0:
        return MIN_COUNT_TTL_SECONDS
    return max(
        MIN_COUNT_TTL_SECONDS,
        threshold * intervalo_s * COUNT_TTL_MARGIN,
    )


def _redis_client() -> redis.Redis:
    """Cliente Redis perezoso (una sola conexión lógica)."""
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True
    )


def _consecutive_key(camera_id: int) -> str:
    return f"camera:{camera_id}:consecutive_fails"


def _lock_key(camera_id: int) -> str:
    return f"camera:{camera_id}:ocr_alert_lock"


def _resolve_manager_email(db: Session, parking_id: int) -> str | None:
    """Email del primer gestor con membresía activa en la sucursal.

    Si no hay ninguno, retorna ``None``. La alerta se crea igualmente;
    sólo se omite el email.
    """
    row = (
        db.query(User)
        .join(ParkingMembership, ParkingMembership.user_id == User.id)
        .filter(
            ParkingMembership.parking_id == parking_id,
            User.role == UserRole.GESTOR,
            User.is_active.is_(True),
        )
        .order_by(User.id)
        .first()
    )
    return row.email if row else None


def una_vez_por_hora(clave: str, ttl: int = 3600) -> bool:
    """¿Es la primera vez dentro de la ventana? (para no escribir una fila por ronda)

    T-104 (2026-10-23): la ronda de heartbeat escribia una fila de
    auditoria **por cada camara caida y cada ronda** (la ronda va cada
    60 s). Medido en la base de QA: **5.928 de 8.763 filas (el 68 %)**
    eran ``camera_offline_heartbeat``, y **ningun panel de Grafana las
    usa**. En produccion, con 50 camaras caidas, son 72.000 filas al dia
    (y la purga las borra de una sentada, sin lotes).

    Con esta comprobacion la fila se escribe **la primera vez** (y
    luego una vez por hora mientras la camara siga caida): el rastro se
    conserva y la tabla deja de crecer sola.

    Si Redis no responde, se escribe (no se pierde el rastro).
    """
    try:
        rds = _redis_client()
        return bool(rds.set(clave, "1", nx=True, ex=ttl))
    except RedisError as exc:
        log.warning("una_vez_por_hora: Redis no disponible (%s)", exc)
        return True


def _resolve_admin_email(db: Session) -> str | None:
    """Email del primer admin activo. Usado para alertas CRITICAL
    (cámara caída) — el operador no siempre tiene gestor asignado y
    el admin necesita enterarse para movilizar soporte técnico.
    """
    row = (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .order_by(User.id)
        .first()
    )
    return row.email if row else None


def _save_frame(camera_code: str, frame_bytes: bytes) -> str | None:
    """Guarda el JPEG en ``/tmp/ocr-failed/<code>-<ts>.jpg``.

    En entornos donde ``/tmp/ocr-failed`` no se pueda escribir (tests
    en Windows), cae a ``/tmp/solidapp-alerts-test`` para no perder
    la captura ni romper el flujo.

    OJO (T-168): ese directorio de respaldo lo limpia **también** la
    tarea ``cleanup_failed_frames`` (con la misma retención); antes sólo
    se purgaba el directorio normal y estos frames se quedaban para
    siempre.
    """
    FAILED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = FAILED_FRAMES_DIR / f"{camera_code}-{ts}.jpg"
    try:
        target.write_bytes(frame_bytes)
        return str(target)
    except OSError as exc:
        log.warning(
            "alerts: no se pudo guardar frame en %s (%s) — fallback",
            target,
            exc,
        )
        try:
            FALLBACK_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
            fallback = FALLBACK_FRAMES_DIR / target.name
            fallback.write_bytes(frame_bytes)
            return str(fallback)
        except OSError as exc2:
            log.warning("alerts: fallback también falló: %s", exc2)
            return None


def record_ocr_failure(
    camera: Camera,
    frame_bytes: bytes | None = None,
    motivo: str = "sin_lecturas",
) -> Alert | None:
    """Incrementa el contador de fallos de lectura y, si llega al umbral, crea una alerta.

    T-181 (2026-10-24): el **motivo** decide el mensaje, porque no es lo
    mismo un frame sin vehículos que un servicio que no contesta:

    - ``sin_lecturas``: el OCR respondió y no leyó ninguna matrícula. Es
      el caso **normal** (una entrada sin coches) y **no** debe llegar
      hasta aquí: el ping lo resetea sin contar.
    - ``no_disponible`` (o cualquier motivo de respuesta no utilizable):
      el servicio OCR no dio una respuesta utilizable. Esto **sí** es un
      fallo de la lectura, y el mensaje lo dice para no culpar a una
      cámara sana de un problema del servicio.
    """
    settings = get_settings()
    threshold = settings.ocr_frames_before_fail
    if threshold <= 0:
        return None
    # T-167: el TTL se deriva del umbral (no es un número fijo) y se
    # renueva en cada fallo (ventana deslizante).
    #
    # T-177 (2026-10-24): el intervalo es el **real** del ping (600 s:
    # el beat despacha ``solidapp.ping_cameras`` cada 10 min). Con 60 s
    # el TTL (5 × 60 × 2 = 600 s) caducaría justo antes de que llegara
    # el siguiente fallo y la alarma no saltaría nunca.
    ttl = ttl_contador_fallos(threshold, settings.ocr_ping_interval_seconds)

    try:
        rds = _redis_client()
        # \incr\ devuelve \Awaitable[Any] | Any\ en los tipos de
        # redis-py, pero el cliente es síncrono y devuelve un int.
        count = cast(int, rds.incr(_consecutive_key(camera.id)))
        # T-167: el TTL se renueva en **cada** fallo. Antes sólo se
        # ponía en el primero (``if count == 1``), o sea que la ventana
        # iba desde el primer fallo: si los fallos llegaban más
        # espaciados que TTL/umbral, el contador caducaba antes de
        # poder llegar al umbral y la alerta NUNCA saltaba.
        rds.expire(_consecutive_key(camera.id), ttl)
    except RedisError as exc:
        log.warning(
            "alerts: Redis no disponible, alerta omitida camera=%s: %s",
            camera.id,
            exc,
        )
        return None

    if count < threshold:
        return None

    try:
        got_lock = rds.set(
            _lock_key(camera.id),
            "1",
            nx=True,
            ex=ALERT_LOCK_TTL_SECONDS,
        )
    except RedisError as exc:
        log.warning(
            "alerts: no se pudo tomar el lock camera=%s: %s",
            camera.id,
            exc,
        )
        return None

    if not got_lock:
        log.info(
            "alerts: alerta ya creada hace <1h camera=%s — se omite",
            camera.id,
        )
        return None

    try:
        rds.delete(_consecutive_key(camera.id))
    except RedisError:
        pass

    frame_path: str | None = None
    if frame_bytes:
        frame_path = _save_frame(camera.code, frame_bytes)

    try:
        with SessionLocal() as db:
            if motivo == "sin_lecturas":
                message = (
                    f"OCR sin lecturas en {camera.code} — "
                    f"{count} frames consecutivos sin matrícula"
                )
            else:
                # T-181: el problema fue el SERVICIO, no la cámara.
                message = (
                    f"El servicio OCR no respondió a {count} pings seguidos "
                    f"de la cámara {camera.code} (motivo: {motivo})"
                )
            context: dict[str, Any] = {
                "camera_id": camera.id,
                "camera_code": camera.code,
                "consecutive_fails": count,
                "threshold": threshold,
                "frame_path": frame_path,
                "motivo": motivo,
            }
            alert = Alert(
                parking_id=camera.parking_id,
                type=AlertType.OCR_FAILED,
                severity=AlertSeverity.WARN,
                message=message,
                context=context,
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)

            manager_email = _resolve_manager_email(db, camera.parking_id)
            parking = alert.parking
            parking_name = parking.name if parking else f"parking-{camera.parking_id}"

        log.warning(
            "alerts: OCR_FAILED alert id=%s camera=%s count=%s threshold=%s",
            alert.id,
            camera.code,
            count,
            threshold,
        )

        # T-103: el correo sale en una tarea de Celery (la ronda no
        # toca la red: con el SMTP lento costaba 2,42 s por alerta).
        email_module.encolar_correo_alerta(
            alert_id=alert.id,
            destinatario=manager_email,
            template_kind="ocr_failed",
            camera_code=camera.code,
            parking_name=parking_name,
            count=count,
            threshold=threshold,
            frame_path=frame_path,
        )
        return alert
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.exception(
            "alerts: fallo inesperado creando alerta camera=%s: %s",
            camera.id,
            exc,
        )
        return None


def reset_ocr_failure(camera_id: int) -> None:
    """Borra el contador y el lock de la cámara. Llamar cuando hay lectura válida."""
    try:
        rds = _redis_client()
        rds.delete(_consecutive_key(camera_id), _lock_key(camera_id))
    except RedisError as exc:
        log.warning(
            "alerts: Redis no disponible en reset camera=%s: %s",
            camera_id,
            exc,
        )


# ── Cámara offline ────────────────────────────────────────────────
# Mismo patrón que OCR_FAILED pero con claves Redis separadas y
# severidad CRITICAL. La cámara caída requiere soporte técnico, no es
# un problema operativo que el gestor pueda resolver.
def _consecutive_offline_key(camera_id: int) -> str:
    return f"camera:{camera_id}:consecutive_offline"


def _offline_lock_key(camera_id: int) -> str:
    return f"camera:{camera_id}:offline_alert_lock"


def record_camera_offline(camera: Camera, *, kind: str = "frame") -> Alert | None:
    """Incrementa el contador de capturas fallidas y, si llega al umbral,
    crea una alerta ``CAMERA_OFFLINE`` (severidad CRITICAL) con email al
    admin. Distinto de ``record_ocr_failure`` porque la cámara caída
    requiere soporte técnico, no recalibración de geocercas.

    Args:
        camera: modelo Camera de la que se sospecha caída.
        kind: ``"frame"`` cuando lo dispara ``ping_camera`` con
            ``grab_frame()`` devolviendo ``None``; ``"heartbeat"`` cuando
            lo dispara ``probe_heartbeats`` con ``probe_camera()`` fallando.
            El kind se persiste en ``alert.context.kind`` para diagnóstico.
            El umbral de fallos consecutivos depende del kind:
            ``"heartbeat"`` → ``settings.heartbeat_failures_before_alert``;
            ``"frame"`` → ``settings.ocr_frames_before_fail``.
    """
    settings = get_settings()
    threshold = (
        settings.heartbeat_failures_before_alert
        if kind == "heartbeat"
        else settings.ocr_frames_before_fail
    )
    if threshold <= 0:
        return None
    # T-167: mismo criterio que en el contador de OCR: el TTL se deriva
    # del umbral y se renueva en cada fallo (ventana deslizante). El
    # intervalo esperado es el del probe que está contando: el del
    # heartbeat (cada 60 s, ``celery_app.py``) o el del ping, según el
    # ``kind``.
    intervalo = (
        settings.ocr_ping_interval_seconds
        if kind == "frame"
        else settings.heartbeat_interval_seconds
    )
    ttl = ttl_contador_fallos(threshold, intervalo)

    try:
        rds = _redis_client()
        count = cast(int, rds.incr(_consecutive_offline_key(camera.id)))
        # T-167: el TTL se renueva en cada fallo (antes sólo en el
        # primero, con lo que la ventana moría en el primer fallo que
        # se pasara del TTL).
        rds.expire(_consecutive_offline_key(camera.id), ttl)
    except RedisError as exc:
        log.warning(
            "alerts: Redis no disponible en offline counter camera=%s: %s",
            camera.id,
            exc,
        )
        return None

    if count < threshold:
        return None

    try:
        got_lock = rds.set(
            _offline_lock_key(camera.id),
            "1",
            nx=True,
            ex=ALERT_LOCK_TTL_SECONDS,
        )
    except RedisError as exc:
        log.warning(
            "alerts: no se pudo tomar offline lock camera=%s: %s",
            camera.id,
            exc,
        )
        return None

    if not got_lock:
        log.info(
            "alerts: CAMERA_OFFLINE ya creada hace <1h camera=%s — se omite",
            camera.id,
        )
        return None

    try:
        rds.delete(_consecutive_offline_key(camera.id))
    except RedisError:
        pass

    try:
        with SessionLocal() as db:
            message = (
                f"Cámara {camera.code} sin respuesta — "
                f"{count} intentos consecutivos de captura fallidos"
            )
            context: dict[str, Any] = {
                "camera_id": camera.id,
                "camera_code": camera.code,
                "consecutive_fails": count,
                "threshold": threshold,
                "kind": kind,
            }
            alert = Alert(
                parking_id=camera.parking_id,
                type=AlertType.CAMERA_OFFLINE,
                severity=AlertSeverity.CRITICAL,
                message=message,
                context=context,
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)

            admin_email = _resolve_admin_email(db)
            parking = alert.parking
            parking_name = parking.name if parking else f"parking-{camera.parking_id}"

        log.warning(
            "alerts: CAMERA_OFFLINE alert id=%s camera=%s count=%s threshold=%s",
            alert.id,
            camera.code,
            count,
            threshold,
        )

        # T-103: idem, el correo de camara caida no se manda aqui.
        email_module.encolar_correo_alerta(
            alert_id=alert.id,
            destinatario=admin_email,
            template_kind="camera_offline",
            camera_code=camera.code,
            parking_name=parking_name,
            count=count,
            threshold=threshold,
        )
        return alert
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.exception(
            "alerts: fallo inesperado creando CAMERA_OFFLINE alert camera=%s: %s",
            camera.id,
            exc,
        )
        return None


def reset_camera_offline(camera_id: int) -> None:
    """Borra el contador y el lock de offline cuando la cámara vuelve."""
    try:
        rds = _redis_client()
        rds.delete(
            _consecutive_offline_key(camera_id),
            _offline_lock_key(camera_id),
            # T-104: tambien el freno de la auditoria, para que la
            # proxima caida se vuelva a anotar (y no una hora depois).
            f"camera:{camera_id}:offline_audit_una_vez",
        )
    except RedisError as exc:
        log.warning(
            "alerts: Redis no disponible en reset offline camera=%s: %s",
            camera_id,
            exc,
        )


__all__ = [
    "una_vez_por_hora",
    "record_ocr_failure",
    "reset_ocr_failure",
    "record_camera_offline",
    "reset_camera_offline",
    "ttl_contador_fallos",
    "FAILED_FRAMES_DIR",
    "FALLBACK_FRAMES_DIR",
    "ALERT_LOCK_TTL_SECONDS",
    "MIN_COUNT_TTL_SECONDS",
    "COUNT_TTL_MARGIN",
]
