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
        log.info(
            "send_alert_email[dry-run]: alert=%s to=%s kind=%s subject=%r",
            alert.id,
            manager_email,
            template_kind,
            subject,
        )
        return True

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


__all__ = ["send_alert_email", "TemplateKind"]
