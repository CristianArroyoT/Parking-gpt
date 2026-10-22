"""Tests del heartbeat ligero (sprint CAMERA_OFFLINE v2).

Estrategia:
  - ``probe_camera`` se testea con un fake de ``cv2.VideoCapture``
    (clase con ``isOpened()`` y ``grab()`` configurables). Evita
    dependencias de un RTSP real.
  - ``probe_heartbeats`` (task batch) usa los mismos fixtures que
    ``test_alert_service.py``: SQLite StaticPool + FakeRedis + stub
    de email.

Casos cubiertos:
  1. ``probe_camera`` devuelve ``True`` cuando ``open+grab`` pasan.
  2. ``probe_camera`` devuelve ``False`` cuando ``isOpened()=False``.
  3. ``probe_camera`` devuelve ``False`` cuando ``grab()=False``.
  4. ``probe_camera`` devuelve ``False`` ante timeout.
  5. ``probe_camera`` devuelve ``False`` ante excepción inesperada.
  6. ``probe_heartbeats`` skipea URLs en ``heartbeat_skip_url_prefixes``.
  7. ``probe_heartbeats`` crea CAMERA_OFFLINE con ``kind="heartbeat"``
     tras ``heartbeat_failures_before_alert`` fallos consecutivos.
  8. ``probe_heartbeats`` resetea el contador Redis en éxito.
  9. ``probe_heartbeats`` comparte lock con detector de ``frame``:
     si ya hay alerta activa (lock tomado), no crea duplicado.
 10. ``probe_heartbeats`` skipea cámaras con ``is_active=False``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza registro de tablas
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType, UserRole
from app.models.parking import Camera, Parking
from app.models.user import User
from app.services import alerts as alerts_mod
from app.services.cameras import heartbeat as heartbeat_mod


# ── Fake de cv2.VideoCapture ──────────────────────────────────────
class _FakeCapture:
    """Sustituye ``cv2.VideoCapture``. Estado a nivel de CLASE para que
    los tests puedan modificarlo antes de instanciar.

    Uso:
        _FakeCapture.opened_default = False
        cap = _FakeCapture()  # cap.opened == False
    """

    instances: list["_FakeCapture"] = []
    opened_default: bool = True
    grab_ok_default: bool = True

    def __init__(self, *args, **kwargs):
        self.opened = type(self).opened_default
        self.grab_ok = type(self).grab_ok_default
        self.release_calls = 0
        type(self).instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def grab(self) -> bool:
        return self.grab_ok

    def release(self) -> None:
        self.release_calls += 1


@pytest.fixture(autouse=True)
def _reset_fake_capture():
    """Cada test parte de un _FakeCapture en estado 'todo OK'."""
    _FakeCapture.instances.clear()
    _FakeCapture.opened_default = True
    _FakeCapture.grab_ok_default = True
    yield
    _FakeCapture.instances.clear()
    _FakeCapture.opened_default = True
    _FakeCapture.grab_ok_default = True


# ── Fake Redis (idéntico al de test_alert_service / test_camera_offline) ──
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


# ── Tests de probe_camera (sin BD) ───────────────────────────────
@pytest.fixture()
def fake_capture(monkeypatch):
    """Reemplaza ``cv2.VideoCapture`` por el fake."""
    monkeypatch.setattr(heartbeat_mod.cv2, "VideoCapture", _FakeCapture)
    return _FakeCapture


def test_probe_camera_returns_true_on_grab_ok(fake_capture: _FakeCapture) -> None:
    class _Cam:
        rtsp_url = "rtsp://demo/x"
    cap = fake_capture
    cap.instances.clear()
    cap.opened_default = True
    cap.grab_ok_default = True

    ok = asyncio.run(heartbeat_mod.probe_camera(_Cam()))  # type: ignore[arg-type]
    assert ok is True
    assert len(cap.instances) == 1
    assert cap.instances[0].release_calls == 1


def test_probe_camera_returns_false_when_not_opened(
    fake_capture: _FakeCapture,
) -> None:
    class _Cam:
        rtsp_url = "rtsp://demo/x"
    # Estado de clase (leído en __init__ de cada nueva instancia).
    fake_capture.opened_default = False
    fake_capture.grab_ok_default = True

    ok = asyncio.run(heartbeat_mod.probe_camera(_Cam()))  # type: ignore[arg-type]
    assert ok is False


def test_probe_camera_returns_false_when_grab_fails(
    fake_capture: _FakeCapture,
) -> None:
    class _Cam:
        rtsp_url = "rtsp://demo/x"
    fake_capture.opened_default = True
    fake_capture.grab_ok_default = False

    ok = asyncio.run(heartbeat_mod.probe_camera(_Cam()))  # type: ignore[arg-type]
    assert ok is False


def test_probe_camera_returns_false_on_timeout(
    monkeypatch, fake_capture: _FakeCapture
) -> None:
    """Forzar TimeoutError en ``wait_for`` → False."""

    class _Cam:
        rtsp_url = "rtsp://demo/x"

    def _never_returns(*args, **kwargs):
        # Sync para que Python NO evalúe los argumentos (incluido to_thread).
        raise asyncio.TimeoutError()

    monkeypatch.setattr(
        heartbeat_mod.asyncio, "wait_for", _never_returns,
    )
    ok = asyncio.run(heartbeat_mod.probe_camera(_Cam()))  # type: ignore[arg-type]
    assert ok is False


def test_probe_camera_returns_false_on_exception(
    monkeypatch, fake_capture: _FakeCapture
) -> None:
    class _Cam:
        rtsp_url = "rtsp://demo/x"

    def _raises(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        heartbeat_mod.asyncio, "wait_for", _raises,
    )
    ok = asyncio.run(heartbeat_mod.probe_camera(_Cam()))  # type: ignore[arg-type]
    assert ok is False


# ── Tests de probe_heartbeats (con BD + Redis) ───────────────────
@pytest.fixture()
def heartbeat_env(monkeypatch, motor_de_test):
    """BD del dialecto de la suite + Redis fake + stub email + umbral forzado."""
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake_redis)

    sent: list[dict] = []

    def _stub_send(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return True

    import app.services.email as email_mod
    monkeypatch.setattr(email_mod, "send_alert_email", _stub_send)

    class _StubSettings:
        ocr_frames_before_fail = 3
        heartbeat_failures_before_alert = 3
        # T-75: ``tasks.py`` usa la property del ajuste real.
        heartbeat_skip_url_prefixes_list = ("rtsp://demo.invalid",)
        redis_url = "redis://stub"

    monkeypatch.setattr(
        "app.services.alerts.get_settings", lambda: _StubSettings(),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_settings", lambda: _StubSettings(),
    )
    # CRÍTICO: tasks.py tiene su propio import `from app.core.db import SessionLocal`.
    # El monkeypatch sobre alerts_mod.SessionLocal no le afecta.
    monkeypatch.setattr(
        "app.workers.tasks.SessionLocal", SessionLocal,
    )

    # Reemplazar cv2.VideoCapture en el módulo que importa tasks.
    monkeypatch.setattr(heartbeat_mod.cv2, "VideoCapture", _FakeCapture)

    db = SessionLocal()
    try:
        admin = User(
            email="admin@solidapp.es", full_name="Admin",
            role=UserRole.ADMIN, is_active=True, hashed_password="x",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        yield db, fake_redis, sent, _FakeCapture
    finally:
        db.close()
        engine.dispose()


def _seed_camera(db, *, code: str, url: str, is_active: bool = True) -> Camera:
    """Crea cámara con su parking. El parking se reutiliza si ya existe
    en la misma sesión (UNIQUE constraint en ``Parking.code``).
    """
    parking = db.query(Parking).filter(Parking.code == "P-H").first()
    if parking is None:
        parking = Parking(code="P-H", name="H", address="x", city="y")
        db.add(parking); db.flush()
    cam = Camera(
        parking_id=parking.id, code=code, name=code,
        rtsp_url=url, is_active=is_active,
    )
    db.add(cam); db.commit(); db.refresh(cam)
    return cam


def test_probe_heartbeats_skips_demo_invalid(heartbeat_env) -> None:
    """Cámaras con URL en heartbeat_skip_url_prefixes no se procesan."""
    from app.workers import tasks as tasks_mod
    db, fake_redis, sent, _ = heartbeat_env
    cam = _seed_camera(db, code="CAM-SKIP", url="rtsp://demo.invalid/seed")

    result = tasks_mod.probe_heartbeats()

    assert result == {"probed": 0, "skipped": 1, "ok": 0, "failed": 0}
    assert db.query(Alert).count() == 0
    assert sent == []
    assert f"camera:{cam.id}:consecutive_offline" not in fake_redis.data


def test_probe_heartbeats_creates_alert_after_threshold(heartbeat_env) -> None:
    """Tras ``heartbeat_failures_before_alert`` fallos, crea CAMERA_OFFLINE."""
    from app.workers import tasks as tasks_mod
    db, fake_redis, sent, fake_cap = heartbeat_env
    cam = _seed_camera(db, code="CAM-DOWN", url="rtsp://real/down")

    # Forzar que el probe falle
    fake_cap.opened_default = False
    fake_cap.grab_ok_default = False

    # Primera ronda: count=1, sin alerta
    r1 = tasks_mod.probe_heartbeats()
    assert r1["failed"] == 1
    assert r1["probed"] == 1
    assert db.query(Alert).count() == 0

    # Segunda: count=2
    tasks_mod.probe_heartbeats()
    assert db.query(Alert).count() == 0

    # Tercera: count=3 → alerta CRITICAL con kind="heartbeat"
    r3 = tasks_mod.probe_heartbeats()
    assert r3["failed"] == 1
    alert = db.query(Alert).one()
    assert alert.type == AlertType.CAMERA_OFFLINE
    assert alert.severity == AlertSeverity.CRITICAL
    assert "CAM-DOWN" in alert.message
    assert alert.context["camera_code"] == "CAM-DOWN"
    assert alert.context["consecutive_fails"] == 3
    assert alert.context["threshold"] == 3
    assert alert.context["kind"] == "heartbeat"

    # Email al admin
    assert len(sent) == 1
    assert sent[0]["kwargs"]["template_kind"] == "camera_offline"
    assert sent[0]["args"][1] == "admin@solidapp.es"


def test_probe_heartbeats_resets_counter_on_success(heartbeat_env) -> None:
    """Si la cámara vuelve, el contador Redis se borra."""
    from app.workers import tasks as tasks_mod
    db, fake_redis, _sent, fake_cap = heartbeat_env
    cam = _seed_camera(db, code="CAM-RECOVER", url="rtsp://real/recover")

    # 2 fallos
    fake_cap.opened_default = False
    fake_cap.grab_ok_default = False
    tasks_mod.probe_heartbeats()
    tasks_mod.probe_heartbeats()
    assert fake_redis.data.get(f"camera:{cam.id}:consecutive_offline") == "2"

    # Cámara vuelve
    fake_cap.opened_default = True
    fake_cap.grab_ok_default = True
    result = tasks_mod.probe_heartbeats()
    assert result["ok"] == 1
    assert f"camera:{cam.id}:consecutive_offline" not in fake_redis.data


def test_probe_heartbeats_lock_shared_with_frame_detector(heartbeat_env) -> None:
    """Si ping_camera(kind='frame') ya creó alerta, probe_heartbeats no duplica."""
    from app.workers import tasks as tasks_mod
    db, fake_redis, sent, fake_cap = heartbeat_env
    cam = _seed_camera(db, code="CAM-DUP", url="rtsp://real/dup")

    # Simular que ping_camera ya disparó la alerta (3 fallos + lock tomado)
    for _ in range(3):
        alerts_mod.record_camera_offline(cam, kind="frame")
    assert db.query(Alert).count() == 1

    # Ahora el heartbeat ve la cámara caída. Lock activo → no crea duplicado.
    fake_cap.opened_default = False
    fake_cap.grab_ok_default = False
    for _ in range(3):
        tasks_mod.probe_heartbeats()

    # Sigue habiendo una sola alerta (la del frame), no dos.
    assert db.query(Alert).count() == 1
    assert len(sent) == 1  # sólo el email del frame original


def test_probe_heartbeats_handles_mixed_active_inactive(heartbeat_env) -> None:
    """Sólo procesa cámaras con is_active=True."""
    from app.workers import tasks as tasks_mod
    db, _fake_redis, _sent, fake_cap = heartbeat_env
    _seed_camera(db, code="ACTIVE", url="rtsp://real/active")
    _seed_camera(db, code="INACTIVE", url="rtsp://real/inactive", is_active=False)

    fake_cap.opened_default = True
    fake_cap.grab_ok_default = True
    result = tasks_mod.probe_heartbeats()
    assert result["probed"] == 1
    assert result["skipped"] == 0
    assert result["ok"] == 1


def test_probe_heartbeats_empty_camera_list(heartbeat_env) -> None:
    """Sin cámaras activas → devuelve zeros sin fallar."""
    from app.workers import tasks as tasks_mod
    result = tasks_mod.probe_heartbeats()
    assert result == {"probed": 0, "skipped": 0, "ok": 0, "failed": 0}


# ── Persistencia de health fields (sprint Camera Health 2026-07-01) ──
def test_probe_heartbeats_persists_last_heartbeat_ok(heartbeat_env) -> None:
    """Tras un probe exitoso, la cámara tiene last_heartbeat_at y last_ok=True."""
    from app.workers import tasks as tasks_mod
    db, _fake_redis, _sent, fake_cap = heartbeat_env
    cam = _seed_camera(db, code="CAM-ALIVE", url="rtsp://real/alive")

    # Forzar probe OK.
    fake_cap.opened_default = True
    fake_cap.grab_ok_default = True

    tasks_mod.probe_heartbeats()

    # Re-leer la cámara con la sesión de la fixture (mismo motor StaticPool).
    db.expire_all()
    refreshed = db.get(Camera, cam.id)
    assert refreshed is not None
    assert refreshed.last_heartbeat_at is not None
    assert refreshed.last_heartbeat_ok is True
    # last_heartbeat_at debe ser reciente (hace < 5 s). SQLite devuelve
    # datetimes naive; Postgres los devuelve tz-aware. Normalizamos a naive
    # en ambos casos con ``.replace(tzinfo=None)`` (no-op si ya es naive).
    #
    # OJO (2026-10-21): el instante de la comparación tiene que ser
    # también UTC. El heartbeat guarda ``datetime.now(timezone.utc)``;
    # comparar ese valor (naive) con ``datetime.now()`` (hora LOCAL)
    # dejaba un desfase de una o dos horas según la zona del servidor, y
    # el test fallaba con "last_heartbeat_at demasiado antiguo" en
    # cualquier máquina que no estuviera en UTC. En CI y en el
    # contenedor pasaba (los dos en UTC), así que el fallo sólo se veía
    # al ejecutar la suite en el portátil del equipo.
    last_at_naive = refreshed.last_heartbeat_at.replace(tzinfo=None)
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    age = (ahora_utc - last_at_naive).total_seconds()
    assert 0 <= age < 5, f"last_heartbeat_at demasiado antiguo: {age}s"


def test_probe_heartbeats_persists_last_heartbeat_ok_false(heartbeat_env) -> None:
    """Tras un probe fallido, la cámara tiene last_heartbeat_at y last_ok=False."""
    from app.workers import tasks as tasks_mod
    db, _fake_redis, _sent, fake_cap = heartbeat_env
    cam = _seed_camera(db, code="CAM-DEAD", url="rtsp://real/dead")

    # Forzar probe FALLIDO.
    fake_cap.opened_default = False
    fake_cap.grab_ok_default = False

    tasks_mod.probe_heartbeats()

    db.expire_all()
    refreshed = db.get(Camera, cam.id)
    assert refreshed is not None
    assert refreshed.last_heartbeat_at is not None
    assert refreshed.last_heartbeat_ok is False