"""Las tareas periódicas no se solapan consigo mismas (T-102).

POR QUÉ existe este fichero: el beat lanza ``probe_heartbeats`` **cada
60 s**, pero una ronda puede tardar más (una cámara colgada hace que
FFmpeg tarde en abandonar el RTSP). Con dos rondas a la vez:

- el contador de fallos de cada cámara se incrementaba **dos veces por
  minuto**, así que la alerta saltaba al doble de tiempo;
- se duplicaban las filas de auditoría y los eventos publicados;
- dos rondas podían tomar a la vez el lock de alerta de una cámara.

Ahora la tarea toma un lock en Redis (``SET NX``) y, si ya hay una
ronda en curso, **se omite**.
"""
from __future__ import annotations

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.workers import tasks as tasks_mod
from tests._audit_helpers import monkeypatch_tasks_session

CLAVE_LOCK = "celery:lock:probe_heartbeats"


def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def test_la_ronda_se_omite_si_ya_hay_otra_en_curso(
    db_session: Session, monkeypatch,
) -> None:
    monkeypatch_tasks_session(monkeypatch, db_session)
    """Con el lock tomado, la tarea se omite y lo dice."""
    r = _redis()
    r.delete(CLAVE_LOCK)
    assert r.set(CLAVE_LOCK, "1", nx=True, ex=120) is True
    try:
        resultado = tasks_mod.probe_heartbeats()
        assert resultado.get("omitida") is True, resultado
        assert resultado.get("motivo") == "ronda_en_curso", resultado
    finally:
        r.delete(CLAVE_LOCK)


def test_sin_lock_la_ronda_se_ejecuta(db_session: Session, monkeypatch) -> None:
    """Sin lock (o sea, normalmente), la ronda hace su trabajo."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    r = _redis()
    r.delete(CLAVE_LOCK)
    resultado = tasks_mod.probe_heartbeats()
    assert not resultado.get("omitida"), resultado
    assert "probed" in resultado, resultado


def test_el_lock_se_toma_con_nx_y_caduca(db_session: Session) -> None:
    """El lock es ``SET NX``: dos rondas no lo toman las dos."""
    r = _redis()
    r.delete(CLAVE_LOCK)
    try:
        assert r.set(CLAVE_LOCK, "1", nx=True, ex=120) is True
        # El segundo intento NO lo toma (el primero lo tiene).
        assert r.set(CLAVE_LOCK, "1", nx=True, ex=120) is None
        # Y caduca (para que un worker muerto no bloquee las rondas).
        assert 0 < r.ttl(CLAVE_LOCK) <= 120
    finally:
        r.delete(CLAVE_LOCK)
