"""T-142 (2026-10-24): el correo no puede fingir que ha salido.

CASO REAL
---------
El compose de produccion solo le daba ``ENVIRONMENT: production`` al
**backend**: el ``celery-worker`` se quedaba en ``development``, y ahi los
correos son **simulados** (``_is_dry_run()``). Medido en el compose
combinado (el que se copia a una sucursal):

    backend        ENVIRONMENT='production'
    celery-worker  ENVIRONMENT=None      <-- se queda en 'development'
    celery-beat    ENVIRONMENT=None      <-- idem

Y en el worker, en ``development``, ``send_alert_email`` devuelve
``True`` **sin enviar nada** (``log.info('[dry-run]')``). El worker es el
que envia el correo de **restablecer contrasena** y el de las alertas de
**camara caida**: en una sucursal, ambos se perdian en silencio. La API
de reset respondia 200 «te hemos enviado un correo» y el correo no salia
nunca.

QUE COMPRUEBA ESTE FICHERO
--------------------------
1. En produccion, sin SMTP configurado (``localhost``), el envio **falla**
   en voz alta (``log.error``) en vez de devolver un exito falso.
2. En produccion, con SMTP configurado, se intenta el envio de verdad.
3. El helper ``smtp_configurado()`` dice la verdad en cada caso.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone

import pytest

from app.core.config import get_settings
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Parking
from app.services.email import send_alert_email, smtp_configurado
from app.services.password_reset_email import send_password_reset_email


@pytest.fixture()
def entorno(monkeypatch):
    """Los ajustes del proceso, con ``environment`` y ``smtp_host``."""
    ajustes = get_settings()
    monkeypatch.setattr(ajustes, "environment", "production", raising=False)
    monkeypatch.setattr(ajustes, "smtp_host", "localhost", raising=False)
    monkeypatch.setattr(ajustes, "smtp_port", 1025, raising=False)
    return ajustes


def _alerta(db_session) -> Alert:
    parking = Parking(
        name="Sucursal de prueba",
        code="TEST-T142",
        address="Calle de la Prueba 1",
        city="Huelva",
        latitude=37.2614,
        longitude=-6.9447,
    )
    db_session.add(parking)
    db_session.flush()
    alerta = Alert(
        parking_id=parking.id,
        type=AlertType.OCR_FAILED,
        severity=AlertSeverity.WARN,
        message="Sin lecturas",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(alerta)
    db_session.commit()
    return alerta


def test_en_produccion_sin_smtp_el_alerta_no_dice_que_se_ha_enviado(
    entorno, db_session, monkeypatch, caplog
) -> None:
    """Sin SMTP configurado, el envio **falla**: no puede decir «enviado».

    OJO: el test tiene que fallar por una **aserción** si se quita el
    arreglo (no por un error dentro del codigo): por eso se comprueba
    que **no** se intenta conectar al SMTP y que el log dice el motivo.
    """
    alerta = _alerta(db_session)
    intentos: list[str] = []

    class _SMTP:
        def __init__(self, host: str, port: int, timeout: int = 5) -> None:
            intentos.append(host)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def ehlo(self) -> None:
            return None

        def send_message(self, msg: object) -> None:
            return None

    monkeypatch.setattr(smtplib, "SMTP", _SMTP)

    with caplog.at_level("ERROR"):
        enviado = send_alert_email(
            alerta, "gestor@ejemplo.es", template_kind="ocr_failed"
        )

    assert enviado is False, (
        "en produccion sin SMTP el correo tiene que fallar, no fingir"
    )
    assert intentos == [], (
        "sin SMTP configurado no se debe intentar conectar: "
        "asi el fallo es el del log, no un error de socket"
    )
    assert "no hay SMTP configurado" in caplog.text


def test_en_produccion_sin_smtp_el_reset_no_dice_que_se_ha_enviado(
    entorno, caplog
) -> None:
    """Lo mismo con el correo de restablecer contrasena."""
    with caplog.at_level("ERROR"):
        enviado = send_password_reset_email(
            to_email="persona@ejemplo.es",
            full_name="Persona",
            raw_token="t" * 32,
            expires_minutes=30,
        )
    assert enviado is False
    assert "no hay SMTP configurado" in caplog.text


def test_en_produccion_con_smtp_configurado_se_intenta_el_envio(
    entorno, db_session, monkeypatch
) -> None:
    """Con un SMTP de verdad, se intenta enviar (y no se aborta antes)."""
    alerta = _alerta(db_session)
    enviados: list[object] = []

    class _SMTP:
        def __init__(self, host: str, port: int, timeout: int = 5) -> None:
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def ehlo(self) -> None:
            return None

        def send_message(self, msg: object) -> None:
            enviados.append(msg)

    monkeypatch.setattr(smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(entorno, "smtp_host", "smtp.ejemplo.es", raising=False)

    assert send_alert_email(
        alerta, "gestor@ejemplo.es", template_kind="ocr_failed"
    ) is True
    assert len(enviados) == 1


def test_smtp_configurado_dice_la_verdad(entorno) -> None:
    """El helper: en produccion, 'localhost' NO es un SMTP configurado."""
    import app.services.email as email_mod

    original = email_mod.get_settings
    email_mod.get_settings = lambda: entorno  # type: ignore[assignment]
    try:
        entorno.smtp_host = "localhost"
        assert smtp_configurado() is False
        entorno.smtp_host = "smtp.ejemplo.es"
        assert smtp_configurado() is True
        entorno.smtp_host = "   "
        assert smtp_configurado() is False
        # Fuera de produccion, 'localhost' es el capturador de pruebas.
        entorno.environment = "development"
        entorno.smtp_host = "localhost"
        assert smtp_configurado() is True
    finally:
        email_mod.get_settings = original  # type: ignore[assignment]
