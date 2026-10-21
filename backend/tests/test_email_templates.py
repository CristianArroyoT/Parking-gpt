"""Tests de las plantillas de correo de alerta (renderizado real).

POR QUÉ este fichero existe (2026-10-21): los tests de
``test_alert_service.py`` y ``test_camera_offline.py`` **simulaban**
``send_alert_email`` (monkeypatch), así que nunca entraban en el
renderizado. Por eso nadie vio que ``_render_camera_offline`` **no
existía**: el ``NameError`` lo capturaba el ``except`` de
``send_alert_email`` y la alerta de cámara caída se quedaba **sin
enviar el correo** al administrador, en silencio, desde el sprint
CAMERA_OFFLINE (2026-07-01).

Estos tests llaman al código **real** (en modo dry-run, que no toca
SMTP) y comprueban que cada plantilla se renderiza. Si alguna función
de renderizado vuelve a faltar, el test falla con un ``NameError``
en vez de dejarlo pasar.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza el registro de tablas en Base.metadata
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Parking
from app.services import email as email_mod


@pytest.fixture()
def alerta(motor_de_test):
    """Una alerta CRITICAL de cámara caída, con su parking."""
    SessionLocal = sessionmaker(
        bind=motor_de_test, autoflush=False, expire_on_commit=False
    )
    with SessionLocal() as db:
        parking = Parking(
            code="TPL-EMAIL",
            name="Parking del test de correo",
            address="Calle Falsa 1",
            city="Madrid",
            is_active=True,
        )
        db.add(parking)
        db.flush()
        alert = Alert(
            parking_id=parking.id,
            type=AlertType.CAMERA_OFFLINE,
            severity=AlertSeverity.CRITICAL,
            message="La cámara CAM-01 ha dejado de responder",
            context={"kind": "heartbeat"},
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        db.expunge(alert)
        return alert


def _sin_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falla el test si se intenta tocar SMTP de verdad."""

    class _Boom:
        def __getattr__(self, name):
            raise AssertionError(f"SMTP no debería invocarse: {name}")

    monkeypatch.setattr(smtplib, "SMTP", _Boom)


def test_render_camera_offline_devuelve_texto_y_html(alerta) -> None:
    """La plantilla de cámara caída se renderiza (la función existe)."""
    texto, html = email_mod._render_camera_offline(
        alerta,
        camera_code="CAM-01",
        parking_name="Madrid Centro A",
        count=5,
        threshold=3,
    )
    assert "CAM-01" in texto
    assert "Madrid Centro A" in texto
    assert "5" in texto and "3" in texto
    assert "<html" in html.lower()
    assert "CAM-01" in html


def test_enviar_alerta_camera_offline_no_falla(alerta, monkeypatch) -> None:
    """``send_alert_email`` con ``camera_offline`` devuelve ``True``.

    Antes de arreglarlo devolvía ``False``: el ``NameError`` de
    ``_render_camera_offline`` lo capturaba el ``except`` y el correo
    nunca salía.
    """
    _sin_smtp(monkeypatch)
    ok = email_mod.send_alert_email(
        alerta,
        "admin@example.com",
        template_kind="camera_offline",
        camera_code="CAM-01",
        parking_name="Madrid Centro A",
        count=5,
        threshold=3,
    )
    assert ok is True


def test_enviar_alerta_camera_offline_no_toca_smtp(alerta, monkeypatch) -> None:
    """Aunque renderice bien, el modo dry-run no abre conexión SMTP."""
    _sin_smtp(monkeypatch)
    ok = email_mod.send_alert_email(
        alerta,
        "admin@example.com",
        template_kind="camera_offline",
        camera_code="CAM-02",
        parking_name="Madrid Centro A",
        count=1,
        threshold=3,
    )
    assert ok is True


def test_enviar_alerta_ocr_failed_sigue_funcionando(alerta, monkeypatch) -> None:
    """La plantilla de OCR (la que sí tenía test indirecto) no se rompió."""
    _sin_smtp(monkeypatch)
    ok = email_mod.send_alert_email(
        alerta,
        "gestor@example.com",
        template_kind="ocr_failed",
        camera_code="CAM-03",
        parking_name="Madrid Centro A",
        count=4,
        threshold=3,
        frame_path=None,
    )
    assert ok is True


def test_todas_las_plantillas_de_alerta_existen_en_disco() -> None:
    """Cada ``template_kind`` tiene su fichero de plantilla.

    Si alguien añade un ``template_kind`` sin la plantilla, el render
    falla en runtime (en el peor caso, dentro del ``except``, en
    silencio). Esto lo detecta antes.
    """
    for kind in ("ocr_failed", "robery_reported", "camera_offline"):
        for ext in ("txt", "html"):
            ruta = email_mod._TEMPLATES_DIR / "alerts" / f"{kind}.{ext}.j2"
            assert ruta.is_file(), f"falta la plantilla {ruta}"


def test_render_ocr_failed_incluye_la_fecha_de_deteccion(alerta) -> None:
    """La fecha de detección se formatea en UTC, no en hora local."""
    alerta.created_at = datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc)
    texto, _html = email_mod._render_ocr_failed(
        alerta,
        camera_code="CAM-04",
        parking_name="Madrid Centro A",
        count=3,
        threshold=3,
        frame_url=None,
        frame_path=None,
    )
    assert "2026-10-21 08:30:00 UTC" in texto
