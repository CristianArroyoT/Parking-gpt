"""Middleware HTTP que extrae contexto de auditoría (sprint Fase 3A, 2026-07-01).

``AuditMiddleware`` corre en cada request HTTP y deja en
``request.state.audit`` un dict con:

  - ``user_id``: extraído del JWT en ``Authorization: Bearer ...`` (sin
    lanzar excepción si el token es inválido — sólo se loguea).
  - ``ip``: ``request.client.host`` (puede ser ``None`` si el request
    viene sin socket — caso raro en producción).
  - ``correlation_id``: UUID hex de 36 chars. Si el cliente envía
    ``X-Request-ID`` se reusa; si no, se genera uno nuevo.
  - ``started_at``: ``time.monotonic()`` para calcular ``duration_ms``.

El header ``X-Request-ID`` se devuelve en la response para que el
operador pueda correlacionar logs de cliente ↔ servidor ↔ Loki.

Los handlers FastAPI leen de ``request.state.audit`` vía el helper
``record_audit_from_request`` (en ``app/services/audit.py``).

Sprint Fase 3D (2026-07-01): añadido check de blacklist de tokens.
Tras decodificar el JWT, si tiene ``jti`` y NO está expirado, consulta
``token_blacklist.is_blocked(jti)`` en Redis. Si está bloqueado, aborta
con 401 ``WWW-Authenticate: Bearer error="invalid_token"``. Si Redis
cae durante el check, FAIL-CLOSED: 401 con "Servicio de autenticación
no disponible". Persiste ``jti`` y ``exp`` en ``request.state.audit``
para que ``logout`` pueda blacklistear.

Push security review (2026-07-01) — 2 hallazgos aplicados:

  1. ``type`` (claim ``access``/``refresh``) se persiste en
     ``request.state.audit`` para que ``logout`` distinga qué tipo
     de token llevó el cliente. Si llega un ``refresh`` a ``/logout``
     ya no se asume silenciosamente que es un ``access``.
  2. ``decode_error`` se persiste en ``request.state.audit`` cuando
     la decodificación JWT lanza ``ValueError/TypeError/KeyError``.
     Antes se descartaba con ``except: pass`` silencioso, dando un
     canal lateral a atacantes (oracle). Ahora los handlers pueden
     detectar el fallo y rechazar con 401 explícito.
"""
from __future__ import annotations

import logging
import time
import uuid

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.ip import get_real_ip
from app.core.security import decode_token
from app.services.token_blacklist import token_blacklist

log = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Inyecta ``request.state.audit`` y propaga ``X-Request-ID``."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. correlation_id (reutiliza entrante o genera nuevo).
        correlation_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # Asegurar que cabe en String(36) de la BD.
        if len(correlation_id) > 36:
            correlation_id = correlation_id[:36]

        # 2. user_id (decodifica JWT sin validar — si falla, queda None).
        user_id: int | None = None
        jti: str | None = None
        exp_epoch: int | None = None
        token_type: str | None = None
        decode_error: bool = False
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(None, 1)[1].strip()
            try:
                payload = decode_token(token)
                sub = payload.get("sub")
                if sub is not None:
                    user_id = int(sub)
                jti = payload.get("jti")
                token_type = payload.get("type")
                exp_val = payload.get("exp")
                if isinstance(exp_val, (int, float)):
                    exp_epoch = int(exp_val)
            except (ValueError, TypeError, KeyError) as exc:
                # Sprint Fase 3D (push security review 2026-07-01):
                # registramos el fallo en audit para que handlers como
                # ``logout`` puedan detectar tokens malformados y
                # rechazar con 401 explícito (cierra el canal lateral
                # "oracle" que devolvía 200 con tokens sin jti).
                decode_error = True
                log.debug(
                    "AuditMiddleware: decode JWT falló (%s)", exc,
                    extra={"correlation_id": correlation_id},
                )

        # 2b. Sprint Fase 3D: check blacklist si el token tiene jti y
        # no ha expirado. Fail-CLOSED: si Redis cae, abort con 401.
        if jti is not None and exp_epoch is not None and exp_epoch > time.time():
            try:
                if token_blacklist.is_blocked(jti):
                    log.warning(
                        "AuditMiddleware: token blacklisteado jti=%s user=%s",
                        jti, user_id,
                        extra={
                            "correlation_id": correlation_id,
                            "jti": jti,
                            "user_id": user_id,
                        },
                    )
                    return Response(
                        status_code=401,
                        content='{"detail":"Token inválido"}',
                        media_type="application/json",
                        headers={
                            "WWW-Authenticate": 'Bearer error="invalid_token"',
                            "X-Request-ID": correlation_id,
                        },
                    )
            except RedisError as exc:
                # FAIL-CLOSED: si Redis cae, NO dejamos pasar.
                log.warning(
                    "AuditMiddleware: Redis caído, fail-closed (%s)", exc,
                    extra={"correlation_id": correlation_id},
                )
                return Response(
                    status_code=401,
                    content='{"detail":"Servicio de autenticación no disponible"}',
                    media_type="application/json",
                    headers={"X-Request-ID": correlation_id},
                )

        # 3. ip del cliente real (parsea X-Forwarded-For si el proxy
        # está en settings.trusted_proxies; ver ``app.core.ip``).
        ip: str | None = get_real_ip(request)

        # 4. Persistir en request.state para los handlers.
        request.state.audit = {
            "user_id": user_id,
            "ip": ip,
            "correlation_id": correlation_id,
            "started_at": time.monotonic(),
            "jti": jti,
            "exp": exp_epoch,
            "type": token_type,
            "decode_error": decode_error,
        }

        response = await call_next(request)
        # 5. Propagar el ID al cliente.
        response.headers["X-Request-ID"] = correlation_id
        return response


__all__ = ["AuditMiddleware"]