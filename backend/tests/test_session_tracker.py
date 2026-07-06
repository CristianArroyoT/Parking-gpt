"""Tests del session_tracker (Sprint R2, 2026-07-06).

Cubre el helper ``app/services/session_tracker.py`` aislado de Redis
(usa fakes en lugar del cliente real).

Cubre:
  1. ``track_session`` añade jti al set del user.
  2. ``untrack_session`` lo elimina.
  3. ``list_active`` devuelve los jtis del set.
  4. ``revoke_all`` SMEMBERS + blackliste + DEL set.
"""
from __future__ import annotations

import pytest

from app.services.session_tracker import session_tracker


class _FakeRedis:
    """Mock mínimo de Redis con soporte de SET (SADD/SMEMBERS/SREM/DEL/EXPIRE)."""

    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.kv: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    def sadd(self, key: str, val: str) -> int:
        self.sets.setdefault(key, set()).add(val)
        return 1

    def srem(self, key: str, val: str) -> int:
        if key in self.sets and val in self.sets[key]:
            self.sets[key].remove(val)
            return 1
        return 0

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, ()))

    def delete(self, key: str) -> int:
        self.sets.pop(key, None)
        self.kv.pop(key, None)
        return 1

    def set(self, key: str, val: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.kv[key] = val
        if ex is not None:
            self._ttls[key] = ex
        return True

    def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        self._ttls[key] = ttl
        return True

    def exists(self, key: str) -> int:
        return 1 if (key in self.kv or key in self.sets) else 0


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    # Parchea AMBOS clientes Redis: session_tracker Y token_blacklist
    # (revoke_all llama a token_blacklist.add → su _r().set()).
    monkeypatch.setattr(session_tracker, "_r", lambda: fake)
    from app.services.token_blacklist import token_blacklist
    monkeypatch.setattr(token_blacklist, "_r", lambda: fake)
    return fake


def test_track_session_adds_jti(fake_redis: _FakeRedis) -> None:
    assert session_tracker.track_session(user_id=42, jti="abc") is True
    assert session_tracker.track_session(user_id=42, jti="def") is True
    assert fake_redis.sets["user:42:active_jtis"] == {"abc", "def"}
    assert fake_redis._ttls["user:42:active_jtis"] > 0


def test_untrack_session_removes_jti(fake_redis: _FakeRedis) -> None:
    session_tracker.track_session(user_id=42, jti="abc")
    session_tracker.track_session(user_id=42, jti="def")
    assert session_tracker.untrack_session(user_id=42, jti="abc") is True
    assert "abc" not in fake_redis.sets["user:42:active_jtis"]
    assert "def" in fake_redis.sets["user:42:active_jtis"]


def test_list_active_returns_jtis(fake_redis: _FakeRedis) -> None:
    session_tracker.track_session(user_id=42, jti="abc")
    active = session_tracker.list_active(user_id=42)
    assert active == ["abc"]


def test_list_active_empty_user(fake_redis: _FakeRedis) -> None:
    assert session_tracker.list_active(user_id=99) == []


def test_revoke_all_blacklists_and_clears(fake_redis: _FakeRedis) -> None:
    session_tracker.track_session(user_id=42, jti="abc")
    session_tracker.track_session(user_id=42, jti="def")
    revoked = session_tracker.revoke_all(user_id=42)
    assert revoked == 2
    assert "user:42:active_jtis" not in fake_redis.sets
    assert "jwt:blacklist:abc" in fake_redis.kv
    assert "jwt:blacklist:def" in fake_redis.kv


def test_revoke_all_empty_set(fake_redis: _FakeRedis) -> None:
    assert session_tracker.revoke_all(user_id=99) == 0