"""Tests de la task ``purge_audit_logs`` (Sprint Fase 3C, 2026-07-01).

Cubre:

  - Borrado de ``audit_logs`` con ``created_at < cutoff``.
  - Idempotencia (segunda llamada no encuentra nada).
  - Usa ``settings.audit_log_retention_days`` por defecto.
  - Acepta kwarg ``retention_days`` para overrides en tests.
  - Defensivo: un fallo en ``db.commit`` NO propaga y devuelve ``error``.

Usa ``monkeypatch_tasks_session`` para apuntar ``tasks.SessionLocal``
a la sesión de prueba.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AuditLog
from tests._audit_helpers import monkeypatch_tasks_session


def _make_audit_log(
    db: Session,
    *,
    age_days: int,
    action: str = "test_action",
) -> AuditLog:
    """Crea un audit_log con ``created_at`` forzado a ``now - age_days``."""
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    log = AuditLog(
        action=action,
        result="success",
        created_at=created,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ── tests ──────────────────────────────────────────────────────────────

def test_purge_old_audit_logs_deletes_only_old(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Sólo se borran los audit_logs con created_at < cutoff."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    old_logs = [_make_audit_log(db_session, age_days=age, action=f"old_{i}")
                for i, age in enumerate([400, 410, 420])]
    new_logs = [_make_audit_log(db_session, age_days=age, action=f"new_{i}")
                for i, age in enumerate([1, 5, 30])]

    from app.workers import tasks as tasks_mod
    result = tasks_mod.purge_audit_logs(retention_days=365)

    assert result["deleted"] == 3
    assert result["retention_days"] == 365

    remaining_actions = {
        row.action for row in db_session.query(AuditLog).all()
    }
    assert "old_0" not in remaining_actions
    assert "old_1" not in remaining_actions
    assert "old_2" not in remaining_actions
    assert "new_0" in remaining_actions
    assert "new_1" in remaining_actions
    assert "new_2" in remaining_actions


def test_purge_audit_logs_zero_when_nothing_old(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Si todos los audit_logs son recientes, ``deleted=0``."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    for i in range(5):
        _make_audit_log(db_session, age_days=i + 1)

    from app.workers import tasks as tasks_mod
    result = tasks_mod.purge_audit_logs(retention_days=365)

    assert result["deleted"] == 0
    assert db_session.query(AuditLog).count() == 5


def test_purge_audit_logs_uses_settings_default(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Sin kwarg ``retention_days``, usa ``settings.audit_log_retention_days``."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    settings = get_settings()
    _make_audit_log(db_session, age_days=settings.audit_log_retention_days + 1)
    _make_audit_log(db_session, age_days=1)

    from app.workers import tasks as tasks_mod
    result = tasks_mod.purge_audit_logs()  # sin override

    assert result["retention_days"] == settings.audit_log_retention_days
    assert result["deleted"] >= 1


def test_purge_audit_logs_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Dos llamadas consecutivas: la segunda no encuentra nada que borrar."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    _make_audit_log(db_session, age_days=400)
    _make_audit_log(db_session, age_days=410)

    from app.workers import tasks as tasks_mod
    first = tasks_mod.purge_audit_logs(retention_days=365)
    second = tasks_mod.purge_audit_logs(retention_days=365)

    assert first["deleted"] == 2
    assert second["deleted"] == 0


def test_purge_audit_logs_does_not_propagate_on_error(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """Si ``db.commit`` lanza, la task devuelve ``error`` y NO propaga."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    _make_audit_log(db_session, age_days=400)

    def boom_commit():
        raise RuntimeError("DB no disponible")

    monkeypatch.setattr(db_session, "commit", boom_commit)

    from app.workers import tasks as tasks_mod
    # NO debe lanzar: la task captura la excepción y devuelve dict.
    result = tasks_mod.purge_audit_logs(retention_days=365)

    assert result["deleted"] == 0
    assert "error" in result
    assert "DB no disponible" in result["error"]