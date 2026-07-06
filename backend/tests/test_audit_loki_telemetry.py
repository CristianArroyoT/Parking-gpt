"""Test del cambio Sprint O1 (2026-07-06): ``record_audit_from_request``
ahora también emite un ``log.info(...)`` con ``extra={action, result,
user_id, resource, parking_id, correlation_id, event="audit"}`` para que
Promtail/Loki reciba el evento y los dashboards Grafana puedan
graficarlo.

Verifica:
  - El log se emite con los campos correctos (vía pytest ``caplog``).
  - NO incluye el ``payload`` (puede contener emails/IPs — corre por
    canal separado en la fila de ``audit_logs``).
  - Si el logger falla, NO se propaga (logging nunca rompe audit).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from app.services.audit import record_audit_from_request


def _fake_request(user_id: int = 42) -> MagicMock:
    """Simula un request con state.audit poblado."""
    request = MagicMock()
    request.state.audit = {
        "user_id": user_id,
        "ip": "127.0.0.1",
        "correlation_id": "abc-123",
    }
    return request


def _fake_db() -> MagicMock:
    """DB mockeada — sólo se llama ``.add()`` (que ignoramos)."""
    return MagicMock()


def test_record_audit_emits_log_for_loki(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifica que el helper emite log.info con los campos requeridos."""
    caplog.set_level(logging.INFO, logger="app.services.audit")

    record_audit_from_request(
        _fake_request(),
        _fake_db(),
        action="login_success",
        resource="users/42",
        payload={"email": "test@x.es"},  # NO debe aparecer en el log
        result="success",
        parking_id=1,
    )

    # Filtramos por el logger específico (caplog puede traer otros).
    audit_logs = [
        r for r in caplog.records
        if r.name == "app.services.audit" and r.message == "audit event"
    ]
    assert len(audit_logs) == 1, "debe emitirse exactamente un log audit event"

    rec = audit_logs[0]
    assert rec.levelno == logging.INFO
    extra = getattr(rec, "__dict__", {})
    # Campos emitidos en ``extra={...}``.
    assert extra.get("event") == "audit"
    assert extra.get("action") == "login_success"
    assert extra.get("result") == "success"
    assert extra.get("user_id") == 42
    assert extra.get("resource") == "users/42"
    assert extra.get("parking_id") == 1
    assert extra.get("correlation_id") == "abc-123"
    # Privacy: el payload NO viaja al log (puede contener emails/IPs).
    assert "payload" not in extra
    assert "email" not in extra


def test_record_audit_log_failure_does_not_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el logger lanza, el helper NO propaga (logging nunca rompe audit)."""

    def boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("logger down")

    # Parcheamos el módulo logger del propio helper para forzar fallo.
    monkeypatch.setattr(
        "app.services.audit.log.info", boom, raising=True,
    )

    # NO debe lanzar: el try/except interno captura y continúa.
    record_audit_from_request(
        _fake_request(user_id=1),
        _fake_db(),
        action="login_success",
        result="success",
    )