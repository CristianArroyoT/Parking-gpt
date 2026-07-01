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
"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import decode_token


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
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(None, 1)[1].strip()
            try:
                payload = decode_token(token)
                sub = payload.get("sub")
                if sub is not None:
                    user_id = int(sub)
            except (ValueError, TypeError, KeyError):
                pass

        # 3. ip del cliente.
        ip: str | None = request.client.host if request.client else None

        # 4. Persistir en request.state para los handlers.
        request.state.audit = {
            "user_id": user_id,
            "ip": ip,
            "correlation_id": correlation_id,
            "started_at": time.monotonic(),
        }

        response = await call_next(request)
        # 5. Propagar el ID al cliente.
        response.headers["X-Request-ID"] = correlation_id
        return response


__all__ = ["AuditMiddleware"]