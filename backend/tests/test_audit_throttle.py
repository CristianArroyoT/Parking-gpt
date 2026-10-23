"""La auditoría del heartbeat no crece sola (T-104).

POR QUÉ existe este fichero: la ronda de heartbeat escribía una fila de
auditoría **por cada cámara caída y cada ronda** (la ronda va cada 60 s).
Medido el 2026-10-23 en la base de QA: **5.928 de 8.763 filas (el 68 %)**
eran ``camera_offline_heartbeat``, y **ningún panel de Grafana las usa**.
En producción, con 50 cámaras caídas, serían 72.000 filas al día (y la
purga las borraba de una sentada, sin lotes).

Ahora:

1. la fila se escribe **la primera vez** y luego **una vez por hora**
   mientras la cámara siga caída (el rastro se conserva, la tabla deja
   de crecer sola);
2. la purga va **en lotes** (un solo DELETE sobre millones de filas deja
   un WAL enorme y bloquea la tabla).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.workers import tasks as tasks_mod
from tests._audit_helpers import monkeypatch_tasks_session
from tests.test_workers_audit import _SafeAsyncio, _seed_camera, _seed_parking


def _ronda_con_camara_caida(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, codigo: str,
) -> None:
    """Ejecuta una ronda con una camara que siempre falla."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = _seed_parking(db_session, code=f"P-{codigo}")
    cam = _seed_camera(
        db_session, parking, code=codigo,
        url="rtsp://real-probe.invalid/stream",
    )

    async def _fake_probe(_cam):
        return False

    monkeypatch.setattr(tasks_mod, "probe_camera", _fake_probe)
    monkeypatch.setattr(tasks_mod, "asyncio", _SafeAsyncio())
    monkeypatch.setattr(
        tasks_mod, "record_camera_offline", lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)
    tasks_mod.probe_heartbeats()


def test_la_fila_de_auditoria_se_escribe_una_vez_por_hora(
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tres rondas seguidas = una sola fila (no una por ronda)."""
    # Se siembra UNA vez (el codigo de parking es unico) y se lanzan las
    # tres rondas: lo que se mide es la fila de auditoria, no la siembra.
    _ronda_con_camara_caida(db_session, monkeypatch, "CAM-THR")
    for _ in range(2):
        tasks_mod.probe_heartbeats()

    filas = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "camera_offline_heartbeat")
        .all()
    )
    assert len(filas) == 1, (
        f"la fila de auditoria del heartbeat deberia escribirse una vez por "
        f"hora, se escribieron {len(filas)}"
    )


def test_la_purga_borra_todo_por_lotes(
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La purga borra todas las filas viejas, y va en lotes (T-104)."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    # Lotes de dos: con 5 filas viejas hacen tres lotes.
    monkeypatch.setattr(tasks_mod, "AUDIT_PURGE_LOTE", 2)

    viejo = datetime.now(timezone.utc) - timedelta(days=500)
    for i in range(5):
        db_session.add(
            AuditLog(
                action="prueba", resource=f"vieja-{i}",
                created_at=viejo,
            )
        )
    db_session.add(
        AuditLog(
            action="prueba", resource="nueva",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    resultado = tasks_mod.purge_audit_logs(retention_days=365)

    assert resultado["deleted"] == 5, resultado
    db_session.expire_all()
    assert db_session.query(AuditLog).filter(
        AuditLog.resource == "nueva",
    ).count() == 1, "la purga no debe tocar lo que no ha caducado"
