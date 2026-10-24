"""T-149 (2026-10-24): el correo de una alerta no se pierde si el broker cae.

El defecto
----------
``encolar_correo_alerta`` devuelve ``False`` si no puede encolar (el
broker —Redis— esta caido) y su docstring promete que «el llamante envia
el correo en linea (mas lento, pero llega)». Pero **los tres llamantes
descartaban el valor de retorno**: con el broker caido, el correo de una
camara caida (o de un robo) se perdia **en silencio**. La alerta quedaba
commiteada y visible por REST, asi que el operador creia que estaba
enterado.

El arreglo
----------
Que lo haga la propia funcion (una sola implementacion): si no se puede
encolar, relee la alerta y manda el correo en linea.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Parking
from app.services import email as email_mod


def _alerta(db_session: Session) -> Alert:
    parking = Parking(
        name="Sucursal T-149",
        code="T149",
        address="Calle del Broker 1",
        city="Huelva",
        latitude=37.2614,
        longitude=-6.9447,
    )
    db_session.add(parking)
    db_session.commit()
    db_session.refresh(parking)
    alerta = Alert(
        parking_id=parking.id,
        type=AlertType.OCR_FAILED,
        severity=AlertSeverity.WARN,
        message="Sin lecturas en la camara",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(alerta)
    db_session.commit()
    db_session.refresh(alerta)
    return alerta


def _preparar(monkeypatch, enviados: list[object]) -> None:
    """El broker caido y un SMTP de mentira que registra lo que se manda."""
    import app.workers.tasks as tasks_mod

    class _BrokerCaido:
        @staticmethod
        def delay(*args: object, **kwargs: object) -> None:
            raise RuntimeError("el broker esta caido")

    monkeypatch.setattr(tasks_mod, "enviar_correo_alerta", _BrokerCaido)

    ajustes = email_mod.get_settings()
    monkeypatch.setattr(ajustes, "environment", "production", raising=False)
    monkeypatch.setattr(ajustes, "smtp_host", "smtp.test.es", raising=False)
    monkeypatch.setattr(ajustes, "smtp_port", 25, raising=False)
    monkeypatch.setattr(ajustes, "smtp_from", "no-reply@test.es", raising=False)

    class _SMTP:
        def __init__(self, host: str, port: int, timeout: int = 5) -> None:
            self.host = host

        def __enter__(self) -> "_SMTP":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def ehlo(self) -> None:
            return None

        def send_message(self, msg: object) -> None:
            enviados.append(msg)

    monkeypatch.setattr(smtplib, "SMTP", _SMTP)


def test_el_correo_sale_en_linea_si_el_broker_esta_caido(
    db_session: Session, monkeypatch
) -> None:
    """Con el broker caido, el correo tiene que salir (aun que en linea)."""
    alerta = _alerta(db_session)
    enviados: list[object] = []
    _preparar(monkeypatch, enviados)

    ok = email_mod.encolar_correo_alerta(
        alert_id=alerta.id,
        destinatario="gestor@test.es",
        template_kind="ocr_failed",
        parking_name="Sucursal T-149",
        camera_code="CAM-T149",
        count=3,
        threshold=3,
    )

    assert ok is True, "con el broker caido el correo tiene que enviarse en linea"
    assert len(enviados) == 1, (
        "con el broker caido no se ha enviado ningun correo: la alerta se "
        "queda en la BD y el gestor no se entera"
    )


def test_sin_destinatario_no_se_rompe(db_session: Session, monkeypatch) -> None:
    """Si no hay a quien mandarlo, se dice (no se rompe la alerta)."""
    alerta = _alerta(db_session)
    enviados: list[object] = []
    _preparar(monkeypatch, enviados)

    ok = email_mod.encolar_correo_alerta(
        alert_id=alerta.id,
        destinatario=None,
        template_kind="ocr_failed",
        parking_name="Sucursal T-149",
    )

    assert ok is False
    assert enviados == []
