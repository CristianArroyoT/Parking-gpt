"""Test del cambio Sprint O1 (2026-07-06): ``record_audit_from_request``
ahora también emite un ``log.info(...)`` con ``extra={action, result,
user_id, resource, parking_id, correlation_id, event="audit"}`` para que
Promtail/Loki reciba el evento y los dashboards Grafana puedan
graficarlo.

Verifica:
  - El log se emite con los campos correctos.
  - NO incluye el ``payload`` (puede contener emails/IPs — corre por
    canal separado en la fila de ``audit_logs``).
  - Si el logger falla, NO se propaga (logging nunca rompe audit).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from app.services.audit import record_audit_from_request


def test_record_audit_emits_log_for_loki(monkeypatch) -> None:
    """Verifica que el helper emite log.info con los campos requeridos."""
    captured: list[dict] = []

    def fake_log(level, msg, *args, **kwargs):  # noqa: ARG001
        captured.append({"level": level, "msg": msg, "extra": kwargs.get("extra", {})})

    fake_logger = MagicMock()
    fake_logger.info = fake_log
    fake_logger.warning = fake_log
    fake_logger.error = fake_log

    monkeypatch.setattr("app.services.audit.log", fake_logger)

    request = MagicMock()
    request.state.audit = {
        "user_id": 42,
        "ip": "127.0.0.1",
        "correlation_id": "abc-123",
    }

    db = MagicMock()

    record_audit_from_request(
        request, db,
        action="login_success",
        resource="users/42",
        payload={"email": "test@x.es"},  # NO debe aparecer en el log
        result="success",
        parking_id=1,
    )

    assert len(captured) == 1, "debe emitirse exactamente un log"
    rec = captured[0]
    assert rec["level"] == logging.INFO
    assert rec["msg"] == "audit event"
    extra = rec["extra"]
    assert extra["event"] == "audit"
    assert extra["action"] == "login_success"
    assert extra["result"] == "success"
    assert extra["user_id"] == 42
    assert extra["resource"] == "users/42"
    assert extra["parking_id"] == 1
    assert extra["correlation_id"] == "abc-123"
    # Privacy: el payload NO viaja al log (puede contener emails/IPs).
    assert "payload" not in extra
    assert "email" not in extra


def test_record_audit_log_failure_does_not_break(monkeypatch) -> None:
    """Si el logger lanza, el helper NO propaga (logging nunca rompe audit)."""

    def boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("logger down")

    fake_logger = MagicMock()
    fake_logger.info = boom

    monkeypatch.setattr("app.services.audit.log", fake_logger)

    request = MagicMock()
    request.state.audit = {"user_id": 1, "ip": "x", "correlation_id": "y"}
    db = MagicMock()

    # NO debe lanzar: el try/except interno captura y continúa.
    record_audit_from_request(
        request, db,
        action="login_success",
        result="success",
    )