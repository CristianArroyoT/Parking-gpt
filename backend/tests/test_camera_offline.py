"""Tests del detector CAMERA_OFFLINE (sprint CAMERA_OFFLINE 2026-07-01).

Mismo patrón que ``test_alert_service.py`` pero para el detector de
N capturas fallidas consecutivas. Distingue "cámara caída" (CRITICAL,
email al admin) de "OCR vacío" (WARN, email al gestor).

Casos cubiertos:
  1. ``record_camera_offline`` no crea alerta si count < threshold.
  2. ``record_camera_offline`` crea alerta CRITICAL al llegar al
     threshold, con email al admin.
  3. ``record_camera_offline`` es idempotente mientras el lock de 1 h
     esté activo.
  4. ``reset_camera_offline`` borra el contador y permite una nueva
     alerta tras el threshold.
  5. Contadores aislados entre cámaras (un fallo en CAM-A no afecta
     al detector de CAM-B).
  6. Email se envía al admin con ``template_kind="camera_offline"``.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza el registro de tablas en Base.metadata
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType, UserRole
from app.models.parking import Camera, Parking
from app.models.user import User
from app.services import alerts as alerts_mod


# ── Fake Redis en memoria (idéntico al de test_alert_service.py) ──
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
def offline_env(monkeypatch, motor_de_test):
    """BD del dialecto de la suite + 2 cámaras + admin + stub de email y Redis.

    Usa ``motor_de_test`` (conftest) para que el fichero se ejecute
    también contra PostgreSQL cuando la suite corre contra PostgreSQL.
    """
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)

    sent: list[dict] = []

    def _stub_send(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return True

    # T-103: el correo ya no se manda en linea, se ENCOLA (lo hace el
    # worker). El seam que se intercepta es el encolado.
    import app.services.email as email_mod
    monkeypatch.setattr(email_mod, "encolar_correo_alerta", _stub_send)

    class _StubSettings:
        ocr_frames_before_fail = 3
        redis_url = "redis://stub"
    monkeypatch.setattr(
        "app.services.alerts.get_settings", lambda: _StubSettings()
    )

    db = SessionLocal()
    try:
        # Admin para resolver email
        admin = User(
            email="admin@solidapp.es",
            hashed_password="x",
            full_name="Admin",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        yield db, fake, sent
    finally:
        db.close()
        engine.dispose()


def _seed_cameras(db) -> tuple[Camera, Camera]:
    parking = Parking(code="P1", name="P1", address="x", city="y")
    db.add(parking)
    db.flush()
    cam_a = Camera(
        parking_id=parking.id, code="CAM-A", name="A",
        rtsp_url="rtsp://demo.invalid/a",
    )
    cam_b = Camera(
        parking_id=parking.id, code="CAM-B", name="B",
        rtsp_url="rtsp://demo.invalid/b",
    )
    db.add_all([cam_a, cam_b])
    db.commit()
    return cam_a, cam_b


def test_no_alert_below_threshold(offline_env) -> None:
    db, _fake, sent = offline_env
    cam_a, _ = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)

    for _ in range(2):
        result = alerts_mod.record_camera_offline(cam_a)
        assert result is None

    assert db.query(Alert).count() == 0
    assert sent == []


def test_alert_critical_at_threshold(offline_env) -> None:
    db, _fake, sent = offline_env
    cam_a, _ = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)

    assert alerts_mod.record_camera_offline(cam_a) is None
    assert alerts_mod.record_camera_offline(cam_a) is None
    alert = alerts_mod.record_camera_offline(cam_a)
    assert alert is not None
    assert alert.type == AlertType.CAMERA_OFFLINE
    assert alert.severity == AlertSeverity.CRITICAL
    assert "CAM-A" in alert.message
    assert alert.context["camera_code"] == "CAM-A"
    assert alert.context["consecutive_fails"] == 3
    assert alert.context["threshold"] == 3

    assert db.query(Alert).count() == 1
    assert len(sent) == 1
    kwargs = sent[0]["kwargs"]
    assert kwargs["template_kind"] == "camera_offline"
    assert kwargs["camera_code"] == "CAM-A"
    assert kwargs["count"] == 3
    assert kwargs["threshold"] == 3
    # El destinatario debe ser el admin (no el gestor).
    to_addr = sent[0]["kwargs"]["destinatario"]
    assert to_addr == "admin@solidapp.es"


def test_rate_limit_prevents_duplicate(offline_env) -> None:
    db, fake, sent = offline_env
    cam_a, _ = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)

    for _ in range(2):
        assert alerts_mod.record_camera_offline(cam_a) is None
    assert alerts_mod.record_camera_offline(cam_a) is not None

    fake.data[f"camera:{cam_a.id}:consecutive_offline"] = "10"
    for _ in range(3):
        result = alerts_mod.record_camera_offline(cam_a)
        assert result is None

    assert db.query(Alert).count() == 1
    assert len(sent) == 1


def test_reset_clears_counter_and_lock(offline_env) -> None:
    db, fake, sent = offline_env
    cam_a, _ = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)

    for _ in range(2):
        assert alerts_mod.record_camera_offline(cam_a) is None
    assert alerts_mod.record_camera_offline(cam_a) is not None
    assert db.query(Alert).count() == 1

    alerts_mod.reset_camera_offline(cam_a.id)
    assert f"camera:{cam_a.id}:consecutive_offline" not in fake.data
    assert f"camera:{cam_a.id}:offline_alert_lock" not in fake.data

    for _ in range(2):
        assert alerts_mod.record_camera_offline(cam_a) is None
    assert alerts_mod.record_camera_offline(cam_a) is not None
    assert db.query(Alert).count() == 2
    assert len(sent) == 2


def test_counters_isolated_between_cameras(offline_env) -> None:
    """Un fallo en CAM-A no debe afectar al detector de CAM-B."""
    db, fake, sent = offline_env
    cam_a, cam_b = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)
    cam_b = db.get(Camera, cam_b.id)

    # 2 fallos en A
    for _ in range(2):
        alerts_mod.record_camera_offline(cam_a)

    # 1 fallo en B (debería NO crear alerta aunque A esté cerca)
    assert alerts_mod.record_camera_offline(cam_b) is None

    # 3 fallos en A → alerta
    assert alerts_mod.record_camera_offline(cam_a) is not None
    # B sigue en 1, no crea alerta
    assert db.query(Alert).count() == 1

    # count_B=1; un fallo más (count=2, sin alerta) y luego el tercero
    # cierra el ciclo y crea la alerta propia de CAM-B.
    assert alerts_mod.record_camera_offline(cam_b) is None
    assert alerts_mod.record_camera_offline(cam_b) is not None
    assert db.query(Alert).count() == 2
    assert len(sent) == 2


def test_admin_email_not_manager(offline_env) -> None:
    """Si hay gestor Y admin, el email va al admin (no al gestor)."""
    from app.models.user import ParkingMembership
    db, _fake, sent = offline_env
    cam_a, _ = _seed_cameras(db)
    cam_a = db.get(Camera, cam_a.id)

    # Añadir un gestor con membresía
    gestor = User(
        email="gestor@solidapp.es",
        hashed_password="x",
        full_name="Gestor",
        role=UserRole.GESTOR,
        is_active=True,
    )
    db.add(gestor)
    db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=cam_a.parking_id))
    db.commit()

    for _ in range(3):
        alerts_mod.record_camera_offline(cam_a)

    assert len(sent) == 1
    to_addr = sent[0]["kwargs"]["destinatario"]
    # El admin (no el gestor) debe recibir la alerta crítica.
    assert to_addr == "admin@solidapp.es"