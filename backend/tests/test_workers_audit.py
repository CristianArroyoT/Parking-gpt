"""Tests audit Fase 3B-parte-2 — workers (ping_camera, probe_heartbeats, ocr_failure).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 3 puntos de inserción de
``record_audit_worker`` en ``app/workers/tasks.py``:

  1. ``ping_camera`` con ``frame=None`` → ``action=camera_offline_frame``.
  2. ``probe_heartbeats`` con ``probe_camera`` fallando →
     ``action=camera_offline_heartbeat``.
  3. ``ping_camera`` con el **servicio OCR que no responde** y umbral
     cruzado en ``record_ocr_failure`` → ``action=ocr_failure_consecutive``.
     OJO (T-181, 2026-10-24): antes este audit salía con «hits=[]», pero
     eso (el OCR respondió y no leyó nada) es el caso **normal** de una
     entrada de parking vacía y **no** cuenta como fallo de OCR.

Los tests usan ``monkeypatch_tasks_session`` (de ``_audit_helpers``) para
que ``tasks.SessionLocal`` devuelva la sesión de prueba. Sin esto, los
audit_logs caerían en una sesión separada contra el motor de producción
y NO aparecerían en ``db_session``.

Casos cubiertos:
  1. ``ping_camera`` con grab_frame=None crea audit camera_offline_frame.
  2. ``ping_camera`` con grab_frame=None NO crea audit ocr (reset cruzado).
  3. ``probe_heartbeats`` con probe_camera=False crea audit
     camera_offline_heartbeat (cámaras con url prefix demo.invalid se
     skipean y NO crean audit).
  4. ``ping_camera`` con frame OK + el OCR que **no responde** + umbral
     cruzado crea audit ocr_failure_consecutive con resource="alerts/{id}".
  5. ``ping_camera`` con frame OK + el OCR que no responde pero por debajo
     del umbral NO crea audit ocr_failure_consecutive.
  6. ``ping_camera`` con frame OK + OCR que **respondió y no leyó nada**
     NO crea audit ocr_failure_consecutive (T-181: no había vehículos).
"""
from __future__ import annotations

import asyncio as real_asyncio
import inspect

import pytest
from sqlalchemy.orm import Session

from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.services.ocr.client import OcrResultado
from app.models.parking import Camera, Parking
from tests._audit_helpers import (
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
    monkeypatch_tasks_session,
)


def _seed_camera(db: Session, parking: Parking, *, code: str = "CAM-W",
                 url: str = "rtsp://real.invalid/stream") -> Camera:
    cam = Camera(
        parking_id=parking.id,
        code=code,
        name=f"Cámara {code}",
        rtsp_url=url,
        fps=10,
        is_active=True,
    )
    db.add(cam); db.commit(); db.refresh(cam)
    return cam


class _SafeAsyncio:
    """Reemplazo de ``asyncio`` que ejecuta coros y captura excepciones.

    El worker llama ``asyncio.run(coro)`` directamente; este wrapper
    evita que cualquier excepción del mock tumbe el task (los tests
    sustituyen el módulo entero con ``monkeypatch.setattr``).

    Desde T-13+4 el worker sondea las cámaras **en paralelo** con
    ``asyncio.gather``, así que el stub también tiene que ofrecerlo.
    """

    def run(self, coro):
        try:
            return real_asyncio.run(coro)
        except Exception:
            return None

    async def gather(self, *coros, return_exceptions=False):
        return await real_asyncio.gather(
            *coros, return_exceptions=return_exceptions
        )

    # API mínima usada por el worker.
    def get_event_loop(self):
        return real_asyncio.get_event_loop()

    def iscoroutine(self, obj):
        return inspect.iscoroutine(obj)


def test_ping_camera_offline_creates_audit_log(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """``ping_camera`` con ``grab_frame=None`` → audit camera_offline_frame."""
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W1")
    cam = _seed_camera(db_session, parking)

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return None

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    result = tasks_mod.ping_camera(cam.id)

    assert result["status"] == "camera_offline"
    assert_audit_log(
        db_session,
        action="camera_offline_frame",
        resource=f"cameras/{cam.id}",
        result="failure",
    )


def test_ping_camera_offline_no_ocr_audit(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """``ping_camera`` con cámara caída → NO crea audit de OCR (reset cruzado)."""
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W2")
    cam = _seed_camera(db_session, parking, code="CAM-W2")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return None

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    tasks_mod.ping_camera(cam.id)

    assert_no_audit_log(db_session, action="ocr_failure_consecutive")


def test_probe_heartbeats_offline_creates_audit_log(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """``probe_heartbeats`` con ``probe_camera=False`` → audit heartbeat."""
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W3")
    # url que NO esté en heartbeat_skip_url_prefixes → se procesa.
    cam = _seed_camera(
        db_session, parking,
        code="CAM-W3",
        url="rtsp://real-probe.invalid/stream",
    )

    from app.workers import tasks as tasks_mod

    async def _fake_probe(_cam):
        return False  # cámara caída.

    monkeypatch.setattr(tasks_mod, "probe_camera", _fake_probe)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    # Stub de record_camera_offline: incrementa contador pero no crea Alert.
    monkeypatch.setattr(
        tasks_mod, "record_camera_offline",
        lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    result = tasks_mod.probe_heartbeats()

    assert result["failed"] >= 1
    assert_audit_log(
        db_session,
        action="camera_offline_heartbeat",
        resource=f"cameras/{cam.id}",
        result="failure",
    )


def test_ping_camera_ocr_failure_creates_audit_log(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """``ping_camera`` con el OCR que **no responde** + umbral cruzado en
    ``record_ocr_failure`` → audit ``ocr_failure_consecutive`` con
    ``resource='alerts/{id}'``.

    T-181 (2026-10-24): el audit se crea en la ruta del **servicio** que no
    contesta (eso **sí** es un fallo de la lectura). Antes salía con
    «hits=[]», que es el caso normal de una entrada de parking vacía.
    """
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W4")
    cam = _seed_camera(db_session, parking, code="CAM-W4")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return b"\xff\xd8\xff\xe0"  # JPEG mínimo.

    class _FakeOcr:
        async def reconocer(self, frame):
            # El servicio NO da una respuesta utilizable (T-181).
            return OcrResultado(hits=[], respondio=False, motivo="no_disponible")

    # record_ocr_failure fake: simula creación de Alert.
    fake_alert = Alert(
        parking_id=cam.parking_id,
        type=AlertType.OCR_FAILED,
        severity=AlertSeverity.WARN,
        message="OCR sin lecturas",
        context={
            "camera_id": cam.id,
            "camera_code": cam.code,
            "consecutive_fails": 5,
            "threshold": 5,
        },
    )
    db_session.add(fake_alert); db_session.commit(); db_session.refresh(fake_alert)

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "get_ocr_client", lambda: _FakeOcr())
    monkeypatch.setattr(
        tasks_mod, "record_ocr_failure",
        lambda *_a, **_kw: fake_alert,
    )
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    result = tasks_mod.ping_camera(cam.id)

    assert result["status"] == "ocr_no_disponible", result
    assert result["plates_found"] == 0
    assert_audit_log(
        db_session,
        action="ocr_failure_consecutive",
        resource=f"alerts/{fake_alert.id}",
        result="failure",
    )


def test_ping_camera_no_ocr_audit_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """``ping_camera`` con el OCR que no responde pero por debajo del
    umbral → NO crea audit ``ocr_failure_consecutive``."""
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W5")
    cam = _seed_camera(db_session, parking, code="CAM-W5")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return b"\xff\xd8\xff\xe0"

    class _FakeOcr:
        async def reconocer(self, frame):
            return OcrResultado(hits=[], respondio=False, motivo="no_disponible")

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "get_ocr_client", lambda: _FakeOcr())
    # record_ocr_failure devuelve None (umbral no cruzado).
    monkeypatch.setattr(
        tasks_mod, "record_ocr_failure",
        lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    result = tasks_mod.ping_camera(cam.id)

    assert result["plates_found"] == 0
    assert_no_audit_log(db_session, action="ocr_failure_consecutive")


def test_ping_camera_sin_lecturas_no_crea_audit_ocr(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """T-181: el OCR respondió y no leyó nada ⇒ **no** hay audit de OCR.

    El frame no tenía vehículos (una entrada de parking vacía, que es el
    caso normal). Contarlo como fallo de OCR producía una falsa alarma
    por cámara cada hora (medido: la alarma id=401).
    """
    monkeypatch_tasks_session(monkeypatch, db_session)

    parking = _seed_parking(db_session, code="P-W6")
    cam = _seed_camera(db_session, parking, code="CAM-W6")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return b"\xff\xd8\xff\xe0"

    class _FakeOcr:
        async def reconocer(self, frame):
            # El servicio respondió, pero no leyó nada.
            return OcrResultado(hits=[], respondio=True, motivo="sin_lecturas")

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "get_ocr_client", lambda: _FakeOcr())
    monkeypatch.setattr(
        tasks_mod, "record_ocr_failure",
        lambda *_a, **_kw: pytest.fail(
            "el OCR que respondió y no leyó nada se ha contado como fallo"
        ),
    )
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    result = tasks_mod.ping_camera(cam.id)

    assert result["status"] == "ok", result
    assert result["plates_found"] == 0
    assert_no_audit_log(db_session, action="ocr_failure_consecutive")

# ── Sprint Fase 3C — correlación end-to-end ────────────────────────────
#
# Cada invocación de ``ping_camera`` / ``probe_heartbeats`` genera UN
# ``correlation_id`` (uuid hex de 36 chars) que se propaga a:
#
#   - todos los ``record_audit_worker`` que emita esa invocación, y
#   - todos los ``log.warning`` / ``log.info`` vía ``extra=``.
#
# Estos 3 tests verifican el contrato: 1) formato del cid, 2) presencia
# en el audit persistido, 3) presencia en el log estructurado (Loki).

import re as _re
from app.models.audit import AuditLog as _AuditLog
_HEX_36 = _re.compile(r"^[0-9a-f]{36}$")


def test_ping_camera_audit_has_correlation_id_36hex(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """El audit creado por ping_camera lleva correlation_id formato hex 36."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = _seed_parking(db_session, code="P-W6")
    cam = _seed_camera(db_session, parking, code="CAM-W6")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return None

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    tasks_mod.ping_camera(cam.id)

    row = db_session.query(_AuditLog).filter(
        _AuditLog.action == "camera_offline_frame",
    ).one()
    assert row.correlation_id is not None
    assert _HEX_36.match(row.correlation_id), (
        f"correlation_id no tiene formato hex 36: {row.correlation_id!r}"
    )


def test_probe_heartbeats_audit_has_correlation_id_36hex(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """El audit de probe_heartbeats lleva correlation_id formato hex 36."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = _seed_parking(db_session, code="P-W7")
    cam = _seed_camera(
        db_session, parking,
        code="CAM-W7",
        url="rtsp://real-probe.invalid/stream",
    )

    from app.workers import tasks as tasks_mod

    async def _fake_probe(_cam):
        return False

    monkeypatch.setattr(tasks_mod, "probe_camera", _fake_probe)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(
        tasks_mod, "record_camera_offline",
        lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    tasks_mod.probe_heartbeats()

    row = db_session.query(_AuditLog).filter(
        _AuditLog.action == "camera_offline_heartbeat",
    ).one()
    assert row.correlation_id is not None
    assert _HEX_36.match(row.correlation_id), (
        f"correlation_id no tiene formato hex 36: {row.correlation_id!r}"
    )


def test_ping_camera_correlation_id_in_log_extra(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Los ``log.warning`` de ping_camera llevan correlation_id en ``extra``."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = _seed_parking(db_session, code="P-W8")
    cam = _seed_camera(db_session, parking, code="CAM-W8")

    from app.workers import tasks as tasks_mod

    async def _fake_grab(_cam):
        return None

    monkeypatch.setattr(tasks_mod, "grab_frame", _fake_grab)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    with caplog.at_level("WARNING", logger="app.workers.tasks"):
        tasks_mod.ping_camera(cam.id)

    # El log.warning final de CAMERA_OFFLINE debe llevar correlation_id.
    cam_offline_records = [
        r for r in caplog.records
        if "CAMERA_OFFLINE" in r.getMessage()
    ]
    assert cam_offline_records, "no se encontró log de CAMERA_OFFLINE en caplog"
    rec = cam_offline_records[0]
    # ``extra={"correlation_id": cid}`` se expone como atributo del record.
    assert hasattr(rec, "correlation_id"), (
        f"el record no tiene atributo correlation_id: {rec.__dict__}"
    )
    assert _HEX_36.match(rec.correlation_id), (
        f"correlation_id del log no tiene formato hex 36: {rec.correlation_id!r}"
    )

    # Y debe COINCIDIR con el correlation_id del audit persistido.
    audit = db_session.query(_AuditLog).filter(
        _AuditLog.action == "camera_offline_frame",
    ).one()
    assert rec.correlation_id == audit.correlation_id, (
        f"correlation_id inconsistente entre log ({rec.correlation_id}) "
        f"y audit ({audit.correlation_id})"
    )