"""Tracker de sesiones activas por usuario (Sprint R2, 2026-07-06).

Mantiene en Redis un SET ``user:{user_id}:active_jtis`` con los ``jti``
de los tokens JWT (access + refresh) emitidos en login/refresh. El set
tiene TTL = max token TTL (refresh, 7 días) para auto-limpiarse si el
usuario deja la plataforma.

Casos de uso:

- ``track_session(user_id, jti, exp_epoch)``: añade jti al set. Hook
  en ``/auth/login`` y ``/auth/refresh`` para que cada par nuevo
  quede registrado.
- ``untrack_session(user_id, jti)``: elimina un jti concreto del set
  cuando el usuario hace logout normal (sólo ese dispositivo).
- ``revoke_all(user_id)``: SMEMBERS del set + blacklist cada jti en
  ``jwt:blacklist:{jti}`` + DEL del set. Hook en
  ``/auth/logout/all`` para cerrar TODAS las sesiones del usuario
  (p. ej. "me robaron el móvil, invalida todo").

**Fail-OPEN** intencional: si Redis cae, ``track_session`` y
``untrack_session`` capturan ``RedisError`` y devuelven False. La
funcionalidad core (blacklist del jti en logout normal) sigue
funcionando; sólo se pierde el "listado global de sesiones" — el
coste de un Redis-down momentáneo es NO permitir logout-all hasta
que vuelva. Logueamos warning para que el operador lo sepa.

NOTA: ``revoke_all`` NO es fail-OPEN — relanza ``RedisError`` para
que el endpoint devuelva 503. Razón: si el usuario hace logout-all
pero no podemos garantizar la invalidación, devolvemos 503 y dejamos
que el cliente reintente. Mismo patrón fail-CLOSED que
``token_blacklist.add``.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.services.token_blacklist import token_blacklist

log = logging.getLogger(__name__)

# TTL del set = TTL del refresh (7 días). Si en el futuro el TTL
# del refresh cambia, recalcular aquí manualmente (no hay settings
# explícito para esto; ver config.py::refresh_token_ttl_days).
_REFRESH_TTL_SECONDS = 7 * 24 * 3600


class SessionTracker:
    """Mantiene el set de jtis activos por user_id."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def _r(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True,
            )
        return self._client

    def _key(self, user_id: int) -> str:
        return f"user:{user_id}:active_jtis"

    def track_session(self, *, user_id: int, jti: str) -> bool:
        """Añade ``jti`` al set del usuario. Fail-OPEN (devuelve False)."""
        try:
            r = self._r()
            key = self._key(user_id)
            r.sadd(key, jti)
            r.expire(key, _REFRESH_TTL_SECONDS)
            return True
        except RedisError as exc:
            log.warning(
                "session_tracker.track_session: Redis down user=%s (%s)",
                user_id, exc,
            )
            return False

    def untrack_session(self, *, user_id: int, jti: str) -> bool:
        """Elimina ``jti`` del set del usuario. Fail-OPEN (devuelve False)."""
        try:
            r = self._r()
            r.srem(self._key(user_id), jti)
            return True
        except RedisError as exc:
            log.warning(
                "session_tracker.untrack_session: Redis down user=%s (%s)",
                user_id, exc,
            )
            return False

    def list_active(self, *, user_id: int) -> list[str]:
        """Devuelve la lista de jtis activos del usuario. Fail-OPEN → []. """
        try:
            return list(self._r().smembers(self._key(user_id)))
        except RedisError as exc:
            log.warning(
                "session_tracker.list_active: Redis down user=%s (%s)",
                user_id, exc,
            )
            return []

    def revoke_all(self, *, user_id: int) -> int:
        """SMEMBERS + blacklist cada jti + DEL set. Fail-CLOSED.

        Devuelve el número de jtis invalidados. Relanza ``RedisError``
        para que el endpoint devuelva 503 si Redis cae.
        """
        r = self._r()
        key = self._key(user_id)
        jtis = list(r.smembers(key))
        for jti in jtis:
            # TTL del blacklist = refresh TTL (los jtis más viejos del
            # set probablemente son refresh con ese TTL).
            token_blacklist.add(
                jti=jti,
                exp_epoch=int(time.time()) + _REFRESH_TTL_SECONDS,
            )
        r.delete(key)
        return len(jtis)


session_tracker = SessionTracker()


__all__ = ["SessionTracker", "session_tracker"]