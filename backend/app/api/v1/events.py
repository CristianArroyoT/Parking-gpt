"""Stream SSE por sucursal: empuja eventos del bus al frontend (MapView).

Sprint O2 (2026-07-06): MapView sustituye ``setInterval(5 s)`` por este
stream. El cliente se suscribe al canal ``parking:{id}:events`` de
Redis pub/sub y recibe los eventos publicados por ``event_bus.publish``
(hooks en ``ingest_service``, ``manual_tickets``, ``incidents``,
``workers/tasks``).

Diseño:

- **Un canal por sucursal**: el cliente sólo escucha su parking.
  ``parking_context`` valida membresía o admin global.
- **Heartbeat cada 30 s**: ``:keepalive\\n\\n`` para que proxies
  intermedios no cierren la conexión por idle.
- **Header ``X-Accel-Buffering: no``**: evita buffering en nginx en
  despliegues futuros (Cloudflare, AWS ALB, etc.).
- **Cleanup en desconexión**: ``unsubscribe`` + ``aclose`` para no
  dejar subscripciones colgadas si el cliente cierra la pestaña.

El evento inicial ``ping`` permite al frontend saber que la conexión
está establecida (se traduce a ``connected.value=true`` en el composable).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core import db as db_mod
from app.core.db import get_db
from app.core.deps import (
    enforce_parking_membership,
    get_current_user_or_query_token,
    oauth2_scheme,
)
from app.core.redis_async import get_async_redis
from app.models.user import User
from app.services.event_bus import channel_for_parking

log = logging.getLogger(__name__)

router = APIRouter(prefix="/parkings/{parking_id}", tags=["events"])


def _parking_context_for_events(
    parking_id: int,
    current: User = Depends(get_current_user_or_query_token),
    db: Session = Depends(get_db),
) -> User:
    """Dep local: RBAC de sucursal + auth por header O ``?token=...``.

    Por qué NO el ``parking_context`` global: ese dep depende de
    ``get_current_user`` (sólo ``Authorization: Bearer``), así que
    combinándolo con ``get_current_user_or_query_token`` el resultado
    era un **401 siempre**: el ``?token=`` se aceptaba en la primera
    dependencia pero la segunda exigía la cabecera. O sea, el endpoint
    anunciaba en su docstring que aceptaba ``?token=`` y en la práctica
    no lo aceptaba.

    Es el mismo patrón (y el mismo criterio de seguridad) que usa el
    endpoint MJPEG ``/cameras/{id}/live``: la ampliación a query token
    es **opt-in por endpoint**, no global. Aquí la ampliación tiene
    sentido porque el consumidor natural del SSE es ``EventSource``, que
    no puede mandar cabeceras.

    ``enforce_parking_membership`` mantiene el RBAC: 403 si el usuario no
    es miembro de la sucursal (o es admin, que pasa siempre).
    """
    return enforce_parking_membership(current, parking_id, db)


@router.get("/events")
async def stream_parking_events(
    request: Request,
    parking_id: int,
) -> StreamingResponse:
    # OJO: este endpoint **no** usa dependencias con ``Depends(get_db)``.
    # Con ellas, la sesión (y su conexión del pool) se mantendría viva
    # hasta que el stream terminaría: con 50 streams simultáneos —el
    # objetivo de producto— eso agota el pool de conexiones y deja
    # conexiones "idle in transaction" cuando el stream se aborta (bug P1
    # encontrado por la prueba de carga del 2026-10-21, T-13). El stream
    # SSE no usa la BD para nada más: todo pasa por Redis (pub/sub).
    #
    # Auth + RBAC se resuelven con una sesión CORTA, abierta y cerrada
    # aquí, antes de empezar a emitir.
    with db_mod.SessionLocal() as db:
        bearer = await oauth2_scheme(request)
        current = get_current_user_or_query_token(
            request=request,
            token=request.query_params.get("token"),
            bearer_token=bearer,
            db=db,
        )
        enforce_parking_membership(current, parking_id, db)
    """Stream SSE con eventos de la sucursal.

    Autenticación: ``Authorization: Bearer <jwt>`` o ``?token=<jwt>``
    (querystring es para ``EventSource`` que no soporta headers).

    RBAC: admin global o miembro del parking. ``parking_context`` ya
    lo valida y devuelve 403 si el gestor no pertenece a la sucursal.

    El stream permanece abierto mientras el cliente esté conectado.
    En cada mensaje publicado al canal Redis, lo emite como
    ``data: <json>\\n\\n``. Cada 30 s sin mensajes emite ``:keepalive``.

    T-06+1 (2026-10-21): el stream también se cierra al apagar el
    servidor. Antes no miraba ningún evento de apagado, así que una
    conexión SSE abierta bloqueaba el apagado de uvicorn igual que lo
    hacia el preview MJPEG: el backend se quedaba en "Waiting for
    connections to close" y, con el reloader, ``process.join()`` impedía
    arrancar el proceso hijo (``/health`` → 000) hasta un
    ``docker restart``. El evento vive en ``app.state.shutdown_event``
    y lo activa el hook de señales de ``app.main``.
    """
    r = get_async_redis()
    pubsub = r.pubsub()
    channel = channel_for_parking(parking_id)
    await pubsub.subscribe(channel)
    log.info("SSE: subscrito a canal %s", channel)

    shutdown_event = getattr(request.app.state, "shutdown_event", None)

    async def gen():
        try:
            # Mensaje inicial para que el cliente sepa que conectó OK.
            yield "event: ping\ndata: {}\n\n"
            while True:
                # El servidor se está apagando: cerrar el stream para que
                # uvicorn pueda terminar. Se comprueba en cada vuelta
                # (el bucle interno espera como mucho 1 s al mensaje de
                # Redis), así que el cierre es prácticamente inmediato.
                if shutdown_event is not None and shutdown_event.is_set():
                    log.info(
                        "SSE: cierre por apagado del servidor (canal %s)", channel
                    )
                    break
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        ),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    # Idle > 30 s: emitimos heartbeat para mantener la
                    # conexión viva en proxies intermedios.
                    yield ":keepalive\n\n"
                    continue
                if msg is not None and msg.get("type") == "message":
                    # msg["data"] ya viene como JSON string (decode_responses=True).
                    yield f"data: {msg['data']}\n\n"
        except asyncio.CancelledError:
            # El cliente cerró el stream (navegador tab cerrada).
            log.info("SSE: cliente desconectó del canal %s", channel)
            raise
        except Exception as exc:  # noqa: BLE001 — defensiva
            log.warning("SSE: error en stream canal=%s: %s", channel, exc)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:  # noqa: BLE001
                log.debug("SSE: cleanup pubsub falló (no crítico): %s", exc)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Evita buffering en nginx/ALB/Cloudflare.
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]