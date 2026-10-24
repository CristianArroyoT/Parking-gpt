"""Envío del correo de recuperación de contraseña (T-22 · plan maestro).

Módulo **autocontenido**: no toca ``app/services/email.py`` (fichero
propiedad de otro sprint/agente en este repo) y por eso no reusa sus
helpers privados de SMTP; implementa aquí el mínimo necesario con el
mismo comportamiento (dry-run fuera de producción, nunca propaga
excepciones).

Plantillas (en ``app/services/templates/password_reset/``):

- ``password_reset.txt.j2`` — cuerpo en texto plano.
- ``password_reset.html.j2`` — cuerpo HTML.

Reglas de operación:

- En ``development``/``staging``/``test`` el envío se **simula**
  (log estructurado + ``return True``), igual que hace
  ``send_alert_email``. Así los tests nunca abren un socket SMTP.
- El cliente SMTP es ``smtplib.SMTP`` síncrono con timeout de 5 s.
  ``starttls()`` + ``login()`` sólo si hay credenciales.
- **Nunca lanza**: captura las excepciones SMTP, las loguea y devuelve
  ``False``. El llamante decide qué hacer con ese ``False``.
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

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

#: La página que consume el token del enlace ya existe (la ruta
#: ``/recuperar-contrasena`` del router). Lo que NO estaba bien era la
#: URL de base: hardcodeada a localhost (T-61), o sea que en produccion el
#: correo llevaba un enlace a localhost y el cliente no llegaba a nada.
#: Ahora sale de ``FRONTEND_BASE_URL`` (ver ``app/core/config.py``), que en
#: staging/produccion tiene que ser una URL real por HTTPS.
RUTA_RESET = "/recuperar-contrasena"


def _reset_url_base() -> str:
    """URL publica del frontend + la ruta de recuperacion."""
    base = get_settings().frontend_base_url.strip().rstrip("/")
    return f"{base}{RUTA_RESET}"


_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def es_entorno_real() -> bool:
    """¿Estamos en producción (donde sí se envía SMTP de verdad)?"""
    return get_settings().environment == "production"


def mail_transport_disponible() -> bool:
    """¿Hay transporte de correo utilizable?

    Se consulta **antes** de mirar si el email existe en la BD: si el
    transporte no está disponible la respuesta es 503 sea cual sea el
    email pedido (si no, el 503 revelaría qué cuentas existen).
    """
    settings = get_settings()
    if not es_entorno_real():
        # Fuera de producción el envío se simula: siempre disponible.
        return True
    return bool(settings.smtp_host.strip())


def render_password_reset_email(
    *,
    full_name: str,
    raw_token: str,
    expires_minutes: int,
) -> tuple[str, str]:
    """Renderiza las plantillas y devuelve ``(texto, html)``."""
    ctx: dict[str, Any] = {
        "full_name": full_name or "cliente",
        "reset_url": f"{_reset_url_base()}?token={raw_token}",
        "expires_minutes": expires_minutes,
        "app_name": "solidAPP",
    }
    txt = _env.get_template("password_reset/password_reset.txt.j2").render(**ctx)
    html = _env.get_template("password_reset/password_reset.html.j2").render(**ctx)
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


def send_password_reset_email(
    *,
    to_email: str,
    full_name: str,
    raw_token: str,
    expires_minutes: int,
) -> bool:
    """Envía el correo con el token de un solo uso.

    Devuelve ``True`` si el correo se ha enviado (o se ha simulado) y
    ``False`` si ha fallado. **Nunca lanza**.
    """
    if not to_email:
        log.warning("send_password_reset_email: sin destinatario")
        return False

    try:
        text_body, html_body = render_password_reset_email(
            full_name=full_name,
            raw_token=raw_token,
            expires_minutes=expires_minutes,
        )
    except Exception as exc:  # noqa: BLE001 — defensiva: el correo nunca rompe el flujo
        log.warning("send_password_reset_email: error renderizando plantilla: %s", exc)
        return False

    settings = get_settings()
    subject = "[solidAPP] Restablece tu contraseña"

    msg = _build_message(
        from_addr=settings.smtp_from,
        to_addr=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    if not es_entorno_real():
        # OJO (T-142): fuera de 'development' el dry-run es un aviso, no
        # un 'info' que nadie lee.
        if get_settings().environment == "development":
            log.info(
                "send_password_reset_email[dry-run]: to=%s subject=%r",
                to_email,
                subject,
            )
        else:
            log.warning(
                "send_password_reset_email[dry-run]: to=%s subject=%r "
                "(ENTORNO=%s: en staging el correo tiene que salir de verdad)",
                to_email,
                subject,
                get_settings().environment,
            )
        return True

    # T-142 (2026-10-24): fail-closed. En produccion, un SMTP sin
    # configurar (host vacio o 'localhost') devolvia un exito falso en
    # algunos caminos; aqui se dice en voz alta. Devolver False hace que
    # el llamante borre el token (un token que nadie recibio no vale) y
    # que el usuario pueda pedir otro.
    from app.services.email import smtp_configurado

    if not smtp_configurado():
        log.error(
            "send_password_reset_email: no hay SMTP configurado "
            "(SMTP_HOST=%r): el correo NO se ha enviado (to=%s)",
            settings.smtp_host,
            to_email,
        )
        return False

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            smtp.ehlo()
            if settings.smtp_user and settings.smtp_password:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        log.info("send_password_reset_email: enviado a %s", to_email)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("send_password_reset_email: SMTP falló to=%s: %s", to_email, exc)
        return False
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.exception("send_password_reset_email: error inesperado to=%s: %s", to_email, exc)
        return False


def encolar_envio_reset(
    *,
    to_email: str,
    full_name: str,
    raw_token: str,
    expires_minutes: int,
    token_id: int,
) -> bool:
    """Encola el envio del correo de reset FUERA del ciclo del request.

    POR QUE (T-94, 2026-10-23): el envio estaba **dentro** del request.
    Con un SMTP lento o caido, la peticion tardaba **5,03 s** (medido
    con un SMTP de mentira que acepta la conexion y no contesta nunca) y
    el worker de la API quedaba bloqueado: con varias peticiones a la
    vez, el endpoint se convertia en un vector de denegacion de
    servicio. Ademas esa latencia era un **oraculo**: con la cuenta
    existente la respuesta tardaba hasta 5 s; sin la cuenta, era
    instantanea.

    Ahora el correo lo manda una tarea de Celery
    (``solidapp.send_password_reset_email``) y el request responde
    enseguida.

    Devuelve ``False`` si no se pudo encolar (el broker esta caido): el
    llamante envia el correo en linea (mas lento, pero llega).
    """
    try:
        from app.workers.tasks import enviar_correo_reset

        enviar_correo_reset.delay(
            to_email=to_email,
            full_name=full_name,
            raw_token=raw_token,
            expires_minutes=expires_minutes,
            token_id=token_id,
        )
    except Exception:  # noqa: BLE001 -- el broker puede estar caido
        log.exception("encolar_envio_reset: no se pudo encolar el correo")
        return False
    return True


__all__ = [
    "encolar_envio_reset",
    "es_entorno_real",
    "mail_transport_disponible",
    "render_password_reset_email",
    "send_password_reset_email",
]
