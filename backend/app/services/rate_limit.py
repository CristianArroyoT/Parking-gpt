"""Rate-limit por IP + email para ``POST /auth/login`` (sprint Fase 3C).

Estrategia:

- 2 buckets Redis independientes:
  - ``rl:login:ip:{ip}`` — protege contra DDoS distribuido.
  - ``rl:login:email:{email_lower}`` — protege contra fuerza bruta
    dirigida a un usuario concreto.
- Si **CUALQUIER** bucket supera ``settings.login_rate_limit_max_attempts``
  en ``settings.login_rate_limit_window_seconds`` → ``allowed=False``.
- Implementación: ``INCR`` por intento + ``EXPIRE`` sólo cuando count==1
  (TTL sólo en la primera escritura, no se renueva en cada INCR — esto
  da una ventana fija desde el primer intento, no una ventana deslizante).
- ``bucket_exceeded`` es la primera clave que pasó el umbral; el
  ``audit_log`` con ``action=rate_limited_login`` registra cuál fue
  para correlación forense.

Garantías:

- ``check()`` NUNCA lanza — captura ``RedisError`` y degrada a
  ``allowed=True`` con ``bucket='redis_unavailable'`` (fail-open:
  preferimos no bloquear usuarios legítimos si Redis está caído; el
  admin verá el warning en logs).
- El módulo expone ``rate_limiter`` (singleton) reusado por el handler.
"""
from __future__ import annotations

import logging

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings

log = logging.getLogger(__name__)


class LoginRateLimiter:
    """Rate-limit por IP + email, vía Redis INCR + EXPIRE."""

    def __init__(self) -> None:
        self._client: redis.Redis | None = None

    def _r(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True,
            )
        return self._client

    def check(self, *, ip: str, email: str) -> tuple[bool, str, int]:
        """Devuelve ``(allowed, bucket_exceeded, max_count)``.

        - ``allowed=False`` si cualquier bucket supera el umbral.
        - ``bucket_exceeded`` es la primera key que superó
          (vacía si todo permitido).
        - ``max_count`` es el count máximo entre los 2 buckets
          (informativo para el audit log).
        """
        settings = get_settings()
        window = settings.login_rate_limit_window_seconds
        max_attempts = settings.login_rate_limit_max_attempts
        try:
            r = self._r()
            bucket_exceeded = ""
            max_count = 0
            for raw_key in (
                f"rl:login:ip:{ip}",
                f"rl:login:email:{email.lower()}",
            ):
                count = r.incr(raw_key)
                if count == 1:
                    r.expire(raw_key, window)
                if count > max_count:
                    max_count = count
                if count > max_attempts and not bucket_exceeded:
                    bucket_exceeded = raw_key
            return (not bool(bucket_exceeded)), bucket_exceeded, max_count
        except RedisError as exc:
            # Fail-open: preferimos no bloquear usuarios legítimos si
            # Redis está caído. El admin verá este warning en Loki.
            log.warning("LoginRateLimiter: Redis no disponible: %s", exc)
            return True, "redis_unavailable", 0


rate_limiter = LoginRateLimiter()