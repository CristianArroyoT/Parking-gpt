"""Cliente de correo para alertas operativas.

Renderiza plantillas Jinja2 y envía vía SMTP. Diseñado para que **nunca
propague excepciones**: en el peor caso devuelve ``False`` y deja la
alerta ya persistida en BD visible vía el endpoint REST.

Reglas de operación:

- En ``development`` o cuando ``ALERT_EMAIL_DRY_RUN=true`` se *simula*
  el envío: log estructurado + ``return True``. Coherente con el hecho
  de que el compose local no expone SMTP real y con la regla "worker
  nunca propaga".
- El cliente SMTP es ``smtplib.SMTP`` síncrono con timeout 5 s.
  ``starttls()`` + ``login()`` sólo si hay credenciales.

Plantillas soportadas (vía ``template_kind``):

- ``ocr_failed`` (default): ``alerts/ocr_failed.{txt,html}.j2``.
- ``robery_reported``: ``alerts/robery_reported.{txt,html}.j2``.
- ``camera_offline``: ``alerts/camera_offline.{txt,html}.j2`` (alerta
  CRITICAL al administrador).
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings
from app.models.audit import Alert

log = logging.getLogger(__name__)
settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DASHBOARD_URL = "http://localhost:5173/gestor/alertas"

TemplateKind = Literal["ocr_failed", "robery_reported", "camera_offline"]

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render_ocr_failed(
    alert: Alert,
    *,
    camera_code: str,
    parking_name: str,
    count: int,
    threshold: int,
    frame_url: str | None,
    frame_path: str | None,
) -> tuple[str, str]:
    ctx: dict[str, Any] = {
        "alert_id": alert.id,
        "camera_code": camera_code,
        "parking_name": parking_name,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity),
        "count": count,
        "threshold": threshold,
        "detected_at": alert.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "dashboard_url": _DASHBOARD_URL,
        "frame_url": frame_url,
        "frame_path": frame_path,
    }
    txt = _env.get_template("alerts/ocr_failed.txt.j2").render(**ctx)
    html = _env.get_template("alerts/ocr_failed.html.j2").render(**ctx)
    return txt, html


def _render_robery_reported(
    alert: Alert,
    *,
    parking_name: str,
) -> tuple[str, str]:
    ctx = alert.context or {}
    plate = ctx.get("plate")
    space_id = ctx.get("parking_space_id")
    parking_space_label = None
    if space_id:
        from app.models.parking import ParkingSpace
        with __import__("app.core.db", fromlist=["SessionLocal"]).SessionLocal() as sdb:
            sp = sdb.get(ParkingSpace, space_id)
            if sp:
                parking_space_label = f"{sp.lane}-{sp.number}"
    ctx_render: dict[str, Any] = {
        "alert_id": alert.id,
        "parking_name": parking_name,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity),
        "detected_at": alert.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "dashboard_url": _DASHBOARD_URL,
        "reason": ctx.get("reason", "other"),
        "reported_by": ctx.get("reported_by", "operador"),
        "plate": plate,
        "parking_space_label": parking_space_label,
        "photos": ctx.get("photos") or [],
        "notes": ctx.get("notes"),
    }
    txt = _env.get_template("alerts/robery_reported.txt.j2").render(**ctx_render)
    html = _env.get_template("alerts/robery_reported.html.j2").render(**ctx_render)
    return txt, html


def _render_camera_offline(
    alert: Alert,
    *,
    camera_code: str,
    parking_name: str,
    count: int,
    threshold: int,
) -> tuple[str, str]:
    """Renderiza la plantilla de cámara caída (alerta CRITICAL al admin).

    La plantilla ``alerts/camera_offline.{txt,html}.j2`` existía desde el
    sprint CAMERA_OFFLINE (2026-07-01), pero la función que la usaba no
    llegó a definirse: el ``NameError`` lo capturaba el ``except`` de
    ``send_alert_email`` y la alerta se quedaba **sin enviar el correo**.
    """
    ctx: dict[str, Any] = {
        "alert_id": alert.id,
        "camera_code": camera_code,
        "parking_name": parking_name,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity),
        "count": count,
        "threshold": threshold,
        "detected_at": alert.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "dashboard_url": _DASHBOARD_URL,
    }
    txt = _env.get_template("alerts/camera_offline.txt.j2").render(**ctx)
    html = _env.get_template("alerts/camera_offline.html.j2").render(**ctx)
    return txt, html


def _build_message(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _is_dry_run() -> bool:
    s = get_settings()
    return s.environment != "production"


def smtp_configurado() -> bool:
    """¿Hay un SMTP de verdad al que enviar?

    T-142 (2026-10-24): en producción, un ``SMTP_HOST`` vacío o
    ``localhost`` significa que **nadie ha configurado el correo**. Es
    mejor gritarlo en el log que fingir que el correo salió: el
    llamante (por ejemplo, el reset de contraseña) toma la decisión
    según lo que devuelva esta función.

    Fuera de producción se considera que sí hay transporte: en
    desarrollo el ``localhost:1025`` es el capturador de pruebas.
    """
    s = get_settings()
    host = s.smtp_host.strip()
    if not host:
        return False
    return not (
        s.environment == "production" and host in ("localhost", "127.0.0.1", "::1")
    )


def send_alert_email(
    alert: Alert,
    manager_email: str | None,
    *,
    template_kind: TemplateKind = "ocr_failed",
    parking_name: str = "",
    camera_code: str = "",
    count: int = 0,
    threshold: int = 0,
    frame_url: str | None = None,
    frame_path: str | None = None,
) -> bool:
    """Envía el email de alerta al gestor. Devuelve ``True`` en éxito.

    Nunca lanza. Captura todas las excepciones SMTP, las loguea y
    devuelve ``False``. La alerta ya está persistida en BD aunque el
    email falle — el operador la verá por el endpoint REST.

    Refactor 2026-06-30: añadido ``template_kind`` para soportar
    múltiples plantillas (``ocr_failed`` por defecto para retro-compat).
    """
    if not manager_email:
        log.warning(
            "send_alert_email: alerta %s sin destinatario (no hay gestor)",
            alert.id,
        )
        return False

    try:
        if template_kind == "ocr_failed":
            text_body, html_body = _render_ocr_failed(
                alert,
                camera_code=camera_code,
                parking_name=parking_name,
                count=count,
                threshold=threshold,
                frame_url=frame_url,
                frame_path=frame_path,
            )
            subject = (
                f"[solidAPP] OCR sin lecturas en {camera_code} — "
                f"{parking_name} (#{alert.id})"
            )
        elif template_kind == "robery_reported":
            text_body, html_body = _render_robery_reported(
                alert, parking_name=parking_name
            )
            subject = (
                f"[solidAPP] 🚨 Reporte de robo — {parking_name} (#{alert.id})"
            )
        elif template_kind == "camera_offline":
            text_body, html_body = _render_camera_offline(
                alert,
                camera_code=camera_code,
                parking_name=parking_name,
                count=count,
                threshold=threshold,
            )
            subject = (
                f"[solidAPP] ⛔ Cámara caída {camera_code} — "
                f"{parking_name} (#{alert.id})"
            )
        else:
            log.warning(
                "send_alert_email: template_kind=%s desconocido — alerta %s",
                template_kind,
                alert.id,
            )
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "send_alert_email: error renderizando plantilla alert=%s: %s",
            alert.id,
            exc,
        )
        return False

    msg = _build_message(
        from_addr=settings.smtp_from,
        to_addr=manager_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    if _is_dry_run():
        # OJO (T-142): en 'staging' el dry-run tambien se simula, pero ahi
        # el correo tiene que salir de verdad: se avisa con un warning
        # (que alguien tiene que mirar) en vez de un info que nadie lee.
        if get_settings().environment == "development":
            log.info(
                "send_alert_email[dry-run]: alert=%s to=%s kind=%s subject=%r",
                alert.id,
                manager_email,
                template_kind,
                subject,
            )
        else:
            log.warning(
                "send_alert_email[dry-run]: alert=%s to=%s kind=%s subject=%r "
                "(ENTORNO=%s: en staging el correo tiene que salir de verdad)",
                alert.id,
                manager_email,
                template_kind,
                subject,
                get_settings().environment,
            )
        return True

    if not smtp_configurado():
        log.error(
            "send_alert_email: no hay SMTP configurado (SMTP_HOST=%r): el "
            "correo NO se ha enviado (alert=%s)",
            settings.smtp_host,
            alert.id,
        )
        return False

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            smtp.ehlo()
            if settings.smtp_user and settings.smtp_password:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        log.info(
            "send_alert_email: alert=%s enviado a %s (kind=%s)",
            alert.id,
            manager_email,
            template_kind,
        )
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning(
            "send_alert_email: SMTP falló alert=%s to=%s: %s",
            alert.id,
            manager_email,
            exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.exception(
            "send_alert_email: error inesperado alert=%s: %s", alert.id, exc
        )
        return False


def send_auto_close_email(
    *,
    to_email: str,
    plate: str,
    parking_name: str,
    entry_at: str,
    exit_at: str,
    amount: float,
    discount: float,
    total: float,
    ticket_id: int,
) -> bool:
    """Avisa al cliente de que su estancia se ha cerrado sola (T-124).

    Nunca lanza: si algo falla, devuelve ``False`` y lo deja en el log.
    """
    settings = get_settings()
    contexto = {
        "to_email": to_email,
        "plate": plate,
        "parking_name": parking_name,
        "entry_at": entry_at,
        "exit_at": exit_at,
        "amount": f"{amount:.2f}",
        "discount": f"{discount:.2f}",
        "total": f"{total:.2f}",
        "ticket_id": ticket_id,
    }
    try:
        text_body = _env.get_template("ticket/auto_closed.txt.j2").render(**contexto)
        html_body = _env.get_template("ticket/auto_closed.html.j2").render(**contexto)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "send_auto_close_email: error renderizando la plantilla del ticket "
            "%s: %s",
            ticket_id,
            exc,
        )
        return False

    subject = f"[solidAPP] Cierre automático de estancia — {plate}"
    msg = _build_message(
        from_addr=settings.smtp_from,
        to_addr=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    if _is_dry_run():
        log.info(
            "send_auto_close_email[dry-run]: to=%s ticket=%s plate=%s total=%s",
            to_email,
            ticket_id,
            plate,
            contexto["total"],
        )
        return True

    if not smtp_configurado():
        log.error(
            "send_auto_close_email: no hay SMTP configurado (SMTP_HOST=%r): el "
            "aviso al cliente NO se ha enviado (ticket=%s)",
            settings.smtp_host,
            ticket_id,
        )
        return False

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            smtp.ehlo()
            if settings.smtp_user and settings.smtp_password:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        log.info(
            "send_auto_close_email: ticket=%s enviado a %s (total=%s)",
            ticket_id,
            to_email,
            contexto["total"],
        )
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning(
            "send_auto_close_email: SMTP falló to=%s ticket=%s: %s",
            to_email,
            ticket_id,
            exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.exception(
            "send_auto_close_email: error inesperado to=%s ticket=%s: %s",
            to_email,
            ticket_id,
            exc,
        )
        return False


def encolar_correo_cierre_automatico(
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
) -> bool:
    """Encola el aviso al cliente del auto-cierre (T-124).

    Devuelve ``False`` si no se pudo encolar (el broker esta caido).
    """
    try:
        from app.workers.tasks import enviar_correo_cierre_automatico

        enviar_correo_cierre_automatico.delay(
            to_email=to_email,
            plate=plate,
            parking_name=parking_name,
            ticket_id=ticket_id,
            entry_at=entry_at,
            exit_at=exit_at,
            amount=amount,
            discount=discount,
            total=total,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "encolar_correo_cierre_automatico: no se pudo encolar el aviso del "
            "ticket %s: %s",
            ticket_id,
            exc,
        )
        return False


def encolar_correo_alerta(
    *,
    alert_id: int,
    destinatario: str | None,
    template_kind: str,
    parking_name: str = "",
    camera_code: str = "",
    count: int = 0,
    threshold: int = 0,
    frame_path: str | None = None,
) -> bool:
    """Encola el correo de una alerta para que lo mande Celery (T-103).

    POR QUE: el envio estaba **dentro** de la ronda de heartbeat, con el
    SMTP en medio. Medido el 2026-10-23 con un SMTP de mentira (que
    acepta la conexion y no contesta): **2,42 s por alerta** y, con 50
    camaras caidas, la ronda tardaba mas de dos minutos (y el beat la
    lanza cada 60 s: se solapaba sola).

    Ahora la ronda **no toca la red**: encola el correo y sigue. El
    destinatario y el contexto viajan en la tarea (la alerta se vuelve
    a leer de la base de datos, que ya esta confirmada).

    Devuelve ``False`` si no se pudo encolar (el broker esta caido): el
    llamante envia el correo en linea (mas lento, pero llega).
    """
    try:
        from app.workers.tasks import enviar_correo_alerta

        enviar_correo_alerta.delay(
            alert_id=alert_id,
            destinatario=destinatario,
            template_kind=template_kind,
            parking_name=parking_name,
            camera_code=camera_code,
            count=count,
            threshold=threshold,
            frame_path=frame_path,
        )
    except Exception:  # noqa: BLE001 -- el broker puede estar caido
        log.exception("encolar_correo_alerta: no se pudo encolar el correo")
        # T-149 (2026-10-24): el docstring de esta funcion promete que
        # «el llamante envia el correo en linea (mas lento, pero llega)»,
        # pero los TRES llamantes (alerts.py dos veces e incidents.py)
        # descartaban el valor de retorno: con el broker caido, el correo
        # de una camara caida (o de un robo) se perdia **en silencio**
        # (la alerta quedaba commiteada y visible por REST, asi que el
        # operador creia que estaba enterado).
        #
        # Se hace aqui, y no en los tres llamantes, para que haya **una
        # sola** implementacion del comportamiento.
        return _enviar_en_linea(
            alert_id=alert_id,
            destinatario=destinatario,
            template_kind=template_kind,
            parking_name=parking_name,
            camera_code=camera_code,
            count=count,
            threshold=threshold,
            frame_path=frame_path,
        )
    return True


def _enviar_en_linea(
    *,
    alert_id: int,
    destinatario: str | None,
    template_kind: str,
    parking_name: str,
    camera_code: str,
    count: int,
    threshold: int,
    frame_path: str | None,
) -> bool:
    """Manda el correo **en linea** cuando el broker esta caido (T-149).

    Relee la alerta (que ya esta commiteada) y la envia con el mismo
    ``send_alert_email`` de siempre. Devuelve ``True`` si se ha enviado.
    """
    if not destinatario:
        log.error(
            "encolar_correo_alerta: el broker esta caido y no hay "
            "destinatario para el correo de la alerta %s: no se puede "
            "enviar en linea",
            alert_id,
        )
        return False
    try:
        from app.core.db import SessionLocal
        from app.models.audit import Alert

        with SessionLocal() as db:
            alert = db.get(Alert, alert_id)
        if alert is None:
            log.error(
                "encolar_correo_alerta: la alerta %s ya no existe: no se "
                "puede enviar el correo en linea",
                alert_id,
            )
            return False
        log.warning(
            "encolar_correo_alerta: el broker esta caido; se envia el "
            "correo de la alerta %s EN LINEA",
            alert_id,
        )
        return send_alert_email(
            alert,
            destinatario,
            template_kind=template_kind,  # type: ignore[arg-type]
            parking_name=parking_name,
            camera_code=camera_code,
            count=count,
            threshold=threshold,
            # La URL del frame no viaja en la alerta (no esta en la BD):
            # sin broker no hay donde mirar la foto.
            frame_url=None,
            frame_path=frame_path,
        )
    except Exception:  # noqa: BLE001 -- el correo nunca rompe el flujo
        log.exception(
            "encolar_correo_alerta: no se pudo enviar el correo de la "
            "alerta %s en linea",
            alert_id,
        )
        return False


__all__ = ["encolar_correo_alerta", "send_alert_email", "TemplateKind"]
