"""Cliente Redis async compartido por el endpoint SSE.

Sprint O2 (2026-07-06): el ``StreamingResponse`` del endpoint
``GET /parkings/{id}/events`` consume ``redis.asyncio`` pubsub —
``redis.Redis`` síncrono bloquearía el event loop de uvicorn.

El singleton lazy sigue el mismo patrón que ``get_settings``:
una conexión por proceso, reusada por todos los request handlers.
En tests, ``monkeypatch.setattr`` puede inyectar un fake con la
misma superficie (``.pubsub()``).
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import get_settings

_async_client: aioredis.Redis | None = None


def get_async_redis() -> aioredis.Redis:
    """Devuelve el cliente async; lo crea en la primera llamada."""
    global _async_client
    if _async_client is None:
        s = get_settings()
        # redis.asyncio no esta tipado.
        _async_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            s.redis_url, decode_responses=True
        )
    return _async_client


def reset_async_redis() -> None:
    """Resetea el singleton (pensado para tests)."""
    global _async_client
    _async_client = None


__all__ = ["get_async_redis", "reset_async_redis"]