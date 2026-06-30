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

Plantillas: ``app/services/templates/alerts/ocr_failed.{txt,html}.j2``.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings
from app.models.audit import Alert

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DASHBOARD_URL = "http://localhost:5173/gestor/alertas"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(
    alert: Alert,
    *,
    camera_code: str,
    parking_name: str,
    count: int,
    threshold: int,
    frame_url: str | None,
    frame_path: str | None,
) -> tuple[str, str]:
    """Devuelve ``(cuerpo_text, cuerpo_html)`` renderizados."""
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
    txt_tmpl = _env.get_template("alerts/ocr_failed.txt.j2")
    html_tmpl = _env.get_template("alerts/ocr_failed.html.j2")
    return txt_tmpl.render(**ctx), html_tmpl.render(**ctx)


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
    """Dry-run fuera de producción. Centralizado para tests."""
    s = get_settings()
    return s.environment != "production"


def send_alert_email(
    alert: Alert,
    manager_email: str | None,
    *,
    camera_code: str,
    parking_name: str,
    count: int,
    threshold: int,
    frame_url: str | None = None,
    frame_path: str | None = None,
) -> bool:
    """Envía el email de alerta al gestor. Devuelve ``True`` en éxito.

    Nunca lanza. Captura todas las excepciones SMTP, las loguea y
    devuelve ``False``. La alerta ya está persistida en BD aunque el
    email falle — el operador la verá por el endpoint REST.
    """
    if not manager_email:
        log.warning(
            "send_alert_email: alerta %s sin destinatario (no hay gestor)",
            alert.id,
        )
        return False

    try:
        text_body, html_body = _render(
            alert,
            camera_code=camera_code,
            parking_name=parking_name,
            count=count,
            threshold=threshold,
            frame_url=frame_url,
            frame_path=frame_path,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "send_alert_email: error renderizando plantilla alert=%s: %s",
            alert.id,
            exc,
        )
        return False

    settings = get_settings()
    subject = (
        f"[solidAPP] OCR sin lecturas en {camera_code} — "
        f"{parking_name} (#{alert.id})"
    )

    msg = _build_message(
        from_addr=settings.smtp_from,
        to_addr=manager_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    if _is_dry_run():
        log.info(
            "send_alert_email[dry-run]: alert=%s to=%s subject=%r",
            alert.id,
            manager_email,
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
            "send_alert_email: alert=%s enviado a %s", alert.id, manager_email
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


__all__ = ["send_alert_email"]
