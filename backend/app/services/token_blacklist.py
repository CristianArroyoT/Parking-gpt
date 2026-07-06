"""Token blacklist Redis (Sprint Fase 3D, 2026-07-01).

Cierra el hueco real de seguridad que el logout del sprint Fase 3A
dejó abierto: antes, ``POST /auth/logout`` sólo registraba un audit
``logout_success`` pero NO invalidaba el JWT. Un atacante con un token
robado podía seguir usándolo hasta su ``exp`` natural (15 min access,
7 días refresh).

Ahora el logout añade el ``jti`` del token actual al blacklist de Redis
con TTL ``(exp - now) + grace_seconds``. El ``AuditMiddleware`` consulta
este blacklist en cada request después de decodificar el JWT: si está,
aborta con 401 ``WWW-Authenticate: Bearer error="invalid_token"``.

**Fail-CLOSED**: NO capturamos ``RedisError`` en ``is_blocked``. Si
Redis cae durante la validación, ``RedisError`` propaga al middleware,
que devuelve 401 con "Servicio de autenticación no disponible". Esto
garantiza que un Redis caído NO deja pasar tokens no validados contra
blacklist. Es la única excepción al patrón fail-OPEN de Fase 3C (rate-
limit) — justificado por la semántica de seguridad: preferible un DoS
temporal si Redis cae antes que tokens comprometidos circulando.
"""
from __future__ import annotations

import time
from typing import Optional

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings


class TokenBlacklist:
    """Helper de blacklist sobre ``jwt:blacklist:{jti}`` en Redis.

    Uso típico (sprint Fase 3D):

      # En ``AuditMiddleware.dispatch``, después de decodificar el JWT:
      jti = payload.get("jti")
      if jti is not None and token_blacklist.is_blocked(jti):
          return 401  # abort antes del handler

      # En ``/auth/logout``:
      token_blacklist.add(jti=jti, exp_epoch=exp)
    """

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def _r(self) -> redis.Redis:
        """Lazy-init del cliente Redis (parámetrizado por settings)."""
        if self._client is None:
            self._client = redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True,
            )
        return self._client

    def add(self, *, jti: str, exp_epoch: int) -> int:
        """Marca ``jti`` como inválido hasta ``exp + grace_seconds``.

        Devuelve el TTL aplicado (segundos). Si ``exp_epoch`` ya pasó,
        el TTL se acorta a 1s (casi inmediato) — el token ya estaba
        expirado por su ``exp`` natural, así que no hay nada que
        blacklistear.

        Relanza ``RedisError`` (fail-CLOSED) para que ``logout`` lo
        capture y devuelva 503. Decisión documentada en el módulo.
        """
        settings = get_settings()
        ttl = max(int(exp_epoch - time.time()) + settings.jwt_blacklist_ttl_grace_seconds, 1)
        key = f"{settings.jwt_blacklist_key_prefix}{jti}"
        self._r().set(key, "1", ex=ttl)
        return ttl

    def is_blocked(self, jti: str) -> bool:
        """Devuelve ``True`` si ``jti`` está en blacklist.

        Relanza ``RedisError`` (fail-CLOSED) — el ``AuditMiddleware``
        captura el error y aborta con 401. NO usar try/except en el
        caller: dejar propagar es parte del contrato.
        """
        key = f"{get_settings().jwt_blacklist_key_prefix}{jti}"
        return self._r().exists(key) > 0


token_blacklist = TokenBlacklist()


__all__ = ["TokenBlacklist", "token_blacklist", "RedisError"]
