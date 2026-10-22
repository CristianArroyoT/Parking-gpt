"""Rate-limit genérico para CRUDs autenticados (Sprint Fase 3D, 2026-07-01).

Cierra el hueco que dejó el sprint Fase 3C: el rate-limit con buckets
Redis INCR + EXPIRE sólo se aplicaba a ``POST /auth/login``. Los CRUDs
sensibles (``POST /users``, ``PATCH /users/{id}``, ``POST /vehicles``,
``PATCH /vehicles/{id}``) no tenían freno: un admin autenticado podía
crear/modificar 1000 usuarios/seg, sin protección contra scripts
automatizados maliciosos o buggy.

``EndpointRateLimiter`` generaliza el patrón de ``LoginRateLimiter``
(Fase 3C) a cualquier endpoint autenticado. Recibe un ``scope``
(ej. ``"users_create"``) y un dict ``identifiers`` con los pares
``kind: value`` que forman los buckets Redis. Para ``users_create``
los buckets son ``rl:users_create:actor:{user_id}`` (futuro:
``rl:users_create:parking:{parking_id}`` si la acción tiene scope).

**Fail-OPEN**: mismo patrón que ``LoginRateLimiter``. Si Redis cae,
``check()`` debería capturar ``RedisError`` y devolver
``(True, "redis_unavailable", 0)`` (no implementado aún — pendiente
declarar comportamiento concreto en B.1 si Redis se vuelve crítico
también para endpoints autenticados).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, cast

import redis
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.models.user import User
from app.services.audit import record_audit_from_request

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import Request
    from sqlalchemy.orm import Session


def enforce_endpoint_rate_limit(
    request: "Request",
    db: "Session",
    *,
    scope: str,
    actor_id: int | None,
    skip: bool = False,
) -> None:
    """Aplica el rate-limit del endpoint y lanza 429 si bloquea.

    **ÚNICO** punto de aplicación del rate-limit por endpoint (T-69).
    Antes el helper estaba copiado en cinco routers (``users``,
    ``vehicles``, ``cameras``, ``parkings``, ``tariffs``) y un sexto
    (``gestor_operadores``) lo tenía escrito en línea: seis copias del
    mismo código, de modo que arreglar una no arreglaba las otras cinco.

    OJO (T-68): una cuenta de servicio (``User.no_rate_limit``) **no** se
    bloquea: se consulta al actor y, si tiene el flag, el límite se salta.
    Antes el flag no lo leía nadie, así que un cronjob de carga inicial de
    datos se comía un 429 igual que un humano.

    Fail-OPEN si Redis no está (igual que el rate-limit de login): no
    bloquear al usuario legítimo es preferible a dejar la app sin
    servicio, y queda el aviso en el log.
    """
    if actor_id is None:
        return
    if not skip:
        actor = db.get(User, actor_id)
        skip = bool(actor is not None and actor.no_rate_limit)
    try:
        allowed, bucket, count = endpoint_rate_limiter.check(
            scope=scope, identifiers={"actor": str(actor_id)}, skip=skip,
        )
    except RedisError as exc:
        log.warning(
            "rate_limit: Redis no disponible en el scope %s (%s)", scope, exc
        )
        return
    if allowed:
        return
    record_audit_from_request(
        request, db,
        action="rate_limited_endpoint",
        payload={"scope": scope, "bucket": bucket, "count": count},
        result="failure",
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiadas operaciones. Intenta más tarde.",
    )


log = logging.getLogger(__name__)


class EndpointRateLimiter:
    """Rate-limit genérico por scope + identifiers.

    Uso en ``app/api/v1/users.py::create_user``::

        from app.services.endpoint_rate_limit import endpoint_rate_limiter
        audit = getattr(request.state, "audit", None) or {}
        actor_id = audit.get("user_id")
        allowed, bucket, count = endpoint_rate_limiter.check(
            scope="users_create",
            identifiers={"actor": str(actor_id)},
        )
        if not allowed:
            record_audit_from_request(
                request, db,
                action="rate_limited_endpoint",
                payload={"scope": "users_create", "bucket": bucket, "count": count},
                result="failure",
            )
            db.commit()
            raise HTTPException(429, "Demasiadas operaciones. Intenta más tarde.")
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

    def check(
        self,
        *,
        scope: str,
        identifiers: dict[str, str],
        max_attempts: Optional[int] = None,
        window_seconds: Optional[int] = None,
        skip: bool = False,
    ) -> tuple[bool, str, int]:
        """Incrementa N buckets y devuelve ``(allowed, bucket_exceeded, max_count)``.

        - ``allowed=False`` si cualquier bucket supera el umbral.
        - ``bucket_exceeded`` es la key del primer bucket que superó
          (vacía si todo permitido). Útil para audit y debug.
        - ``max_count`` es el count máximo entre los buckets
          (informativo para el audit log).
        - ``max_attempts`` y ``window_seconds`` son kwargs opcionales
          (útil en tests para overrides sin tocar settings). Por
          defecto usan ``settings.endpoint_rate_limit_*``.
        """
        settings = get_settings()
        attempts = max_attempts or settings.endpoint_rate_limit_max_attempts
        window = window_seconds or settings.endpoint_rate_limit_window_seconds
        if skip:
            return True, "skipped", 0
        r = self._r()
        bucket_exceeded = ""
        max_count = 0
        for kind, value in identifiers.items():
            key = f"rl:{scope}:{kind}:{value}"
            # ``incr`` devuelve ``Awaitable[Any] | Any`` en los tipos de
            # redis-py, pero el cliente es síncrono y devuelve un int.
            count = cast(int, r.incr(key))
            if count == 1:
                # Sólo la primera vez que se crea el bucket se aplica
                # el TTL. Si ya existía, conserva su TTL original
                # (ventana fija, no sliding).
                r.expire(key, window)
            if count > max_count:
                max_count = count
            if count > attempts and not bucket_exceeded:
                bucket_exceeded = key
        return (not bool(bucket_exceeded)), bucket_exceeded, max_count


endpoint_rate_limiter = EndpointRateLimiter()


__all__ = ["EndpointRateLimiter", "endpoint_rate_limiter"]
