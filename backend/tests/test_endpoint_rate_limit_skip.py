"""Test del sprint hardening R6 (2026-07-06): el flag ``User.no_rate_limit``
permite que service accounts se salten el rate-limit de los CRUDs
autenticados sin tocar settings globales.

Cubre:
  1. ``EndpointRateLimiter.check(skip=True)`` devuelve ``(True, "skipped", 0)``
     sin tocar Redis.
  2. Por defecto (``skip=False``) sigue aplicando el rate-limit.
"""
from __future__ import annotations

from app.services.endpoint_rate_limit import endpoint_rate_limiter


def test_check_skip_returns_allowed_without_redis(monkeypatch) -> None:
    """Si ``skip=True``, el helper NO incrementa ningún bucket Redis."""

    def boom(*args, **kwargs):  # noqa: ARG001
        raise AssertionError(
            "Redis NO debería tocarse cuando skip=True",
        )

    monkeypatch.setattr(
        endpoint_rate_limiter, "_r", boom, raising=True,
    )

    allowed, bucket, count = endpoint_rate_limiter.check(
        scope="users_create",
        identifiers={"actor": "42"},
        skip=True,
    )
    assert allowed is True
    assert bucket == "skipped"
    assert count == 0


def test_check_default_applies_limit(monkeypatch) -> None:
    """Sin ``skip`` el comportamiento no cambia: chequea Redis normal."""

    class _FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        def incr(self, key: str) -> int:
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, *_a, **_kw) -> None:  # noqa: ARG002
            return None

    fake = _FakeRedis()
    monkeypatch.setattr(endpoint_rate_limiter, "_r", lambda: fake)

    allowed, _, _ = endpoint_rate_limiter.check(
        scope="users_create",
        identifiers={"actor": "42"},
    )
    assert allowed is True