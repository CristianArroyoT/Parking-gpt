"""Tests del servicio de alertas (detector de N frames sin matrícula).

Estrategia: BD SQLite en memoria + monkeypatch del cliente Redis y del
envío de email. ``alerts.record_ocr_failure`` y ``alerts.reset_ocr_failure``
se parchean a nivel de función (no de módulo) para preservar la API
original del repo.

Casos cubiertos:
  1. ``record_ocr_failure`` no crea alerta si count < threshold.
  2. ``record_ocr_failure`` crea alerta al llegar al threshold.
  3. ``record_ocr_failure`` es idempotente mientras el lock de 1 h
     esté activo (rate-limit).
  4. ``reset_ocr_failure`` borra el contador y permite una nueva
     alerta tras el threshold.
  5. Email dry-run: el método ``send_alert_email`` se invoca una vez
     con los argumentos esperados y no toca SMTP real.
"""
from __future__ import annotations

import smtplib

import pytest
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza el registro de tablas en Base.metadata
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Camera, Parking
from app.services import alerts as alerts_mod


# ── Fake Redis en memoria (suficiente para los comandos que usamos) ──
class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def incr(self, key: str) -> int:
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])

    def expire(self, key: str, ttl: int) -> bool:
        return True

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                removed += 1
        return removed


@pytest.fixture()
def alert_env(monkeypatch, motor_de_test):
    """BD del dialecto de la suite + cámara + parking + stub de email y Redis.

    Usa la fixture ``motor_de_test`` del conftest para que este fichero
    también se ejecute contra PostgreSQL cuando la suite corre contra
    PostgreSQL (antes creaba su propio SQLite y el dialecto real
    quedaba sin cubrir).
    """
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)

    # Capturar llamadas a send_alert_email sin tocar SMTP real.
    sent: list[dict] = []

    def _stub_send(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return True

    # T-103: el correo ya no se manda en linea, se ENCOLA (lo hace el
    # worker). El seam que se intercepta es el encolado.
    import app.services.email as email_mod
    monkeypatch.setattr(email_mod, "encolar_correo_alerta", _stub_send)

    # Forzar threshold=3 para no depender de Settings en estos tests.
    class _StubSettings:
        ocr_frames_before_fail = 3
        redis_url = "redis://stub"
    monkeypatch.setattr(
        "app.services.alerts.get_settings", lambda: _StubSettings()
    )

    db = SessionLocal()
    try:
        yield db, fake, sent
    finally:
        db.close()
        engine.dispose()


def _seed_camera(db) -> Camera:
    parking = Parking(code="P1", name="P1", address="x", city="y")
    db.add(parking)
    db.flush()
    cam = Camera(
        parking_id=parking.id, code="CAM-01", name="C1",
        rtsp_url="rtsp://demo.invalid/x",
    )
    db.add(cam)
    db.commit()
    return cam


def test_no_alert_below_threshold(alert_env) -> None:
    db, _fake, sent = alert_env
    cam = _seed_camera(db)
    cam = db.get(Camera, cam.id)

    for _ in range(2):
        result = alerts_mod.record_ocr_failure(cam, b"frame")
        assert result is None

    assert db.query(Alert).count() == 0
    assert sent == []


def test_alert_created_at_threshold(alert_env) -> None:
    db, fake, sent = alert_env
    cam = _seed_camera(db)
    cam = db.get(Camera, cam.id)

    assert alerts_mod.record_ocr_failure(cam, b"frame1") is None
    assert alerts_mod.record_ocr_failure(cam, b"frame2") is None
    alert = alerts_mod.record_ocr_failure(cam, b"frame3")
    assert alert is not None
    assert alert.type == AlertType.OCR_FAILED
    assert alert.severity == AlertSeverity.WARN
    assert "CAM-01" in alert.message
    assert alert.context["camera_code"] == "CAM-01"
    assert alert.context["consecutive_fails"] == 3
    assert alert.context["threshold"] == 3

    assert db.query(Alert).count() == 1
    assert len(sent) == 1
    kwargs = sent[0]["kwargs"]
    assert kwargs["camera_code"] == "CAM-01"
    assert kwargs["count"] == 3
    assert kwargs["threshold"] == 3


def test_rate_limit_prevents_duplicate(alert_env) -> None:
    db, fake, sent = alert_env
    cam = _seed_camera(db)
    cam = db.get(Camera, cam.id)

    for _ in range(2):
        assert alerts_mod.record_ocr_failure(cam, b"f") is None
    assert alerts_mod.record_ocr_failure(cam, b"f") is not None

    fake.data[f"camera:{cam.id}:consecutive_fails"] = "10"
    for _ in range(3):
        result = alerts_mod.record_ocr_failure(cam, b"f")
        assert result is None

    assert db.query(Alert).count() == 1
    assert len(sent) == 1


def test_reset_clears_counter_and_lock(alert_env) -> None:
    db, fake, sent = alert_env
    cam = _seed_camera(db)
    cam = db.get(Camera, cam.id)

    for _ in range(2):
        assert alerts_mod.record_ocr_failure(cam, b"f") is None
    assert alerts_mod.record_ocr_failure(cam, b"f") is not None
    assert db.query(Alert).count() == 1

    alerts_mod.reset_ocr_failure(cam.id)
    assert f"camera:{cam.id}:consecutive_fails" not in fake.data
    assert f"camera:{cam.id}:ocr_alert_lock" not in fake.data

    for _ in range(2):
        assert alerts_mod.record_ocr_failure(cam, b"f") is None
    assert alerts_mod.record_ocr_failure(cam, b"f") is not None
    assert db.query(Alert).count() == 2
    assert len(sent) == 2


def test_email_dry_run_in_development(alert_env, monkeypatch) -> None:
    """En development, send_alert_email loguea y no toca SMTP real."""
    called = {"n": 0}

    class _Boom:
        def __getattr__(self, name):
            called["n"] += 1
            raise AssertionError(f"SMTP no debería invocarse: {name}")

    monkeypatch.setattr(smtplib, "SMTP", _Boom)

    db, _fake, sent = alert_env
    cam = _seed_camera(db)
    cam = db.get(Camera, cam.id)

    for _ in range(2):
        assert alerts_mod.record_ocr_failure(cam, b"f") is None
    alerts_mod.record_ocr_failure(cam, b"f")
    assert called["n"] == 0
    assert len(sent) == 1