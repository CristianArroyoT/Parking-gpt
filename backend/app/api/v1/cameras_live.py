"""Endpoint MJPEG live para preview de cámara en CalibrateView.

Razón de vivir en router separado (no en ``cameras.py``): el router
``cameras.py`` tiene ``dependencies=[Depends(parking_context)]`` que
sólo acepta Authorization Bearer. El ``<img src="...">`` del navegador
no puede mandar headers arbitrarios, así que necesitamos permitir
``?token=...`` como query param. Aquí usamos
``get_current_user_or_query_token`` (mismo patrón del SSE del Sprint
O2).

API expuesta:
  GET /api/v1/parkings/{parking_id}/cameras/{camera_id}/live
    200  multipart/x-mixed-replace; boundary=frame (5 fps por defecto)
    401  sin token (ni header ni query)
    403  usuario sin membresía en el parking
    404  cámara no pertenece al parking del path
    409  ya hay otro stream activo para esta cámara

Callers frontend previstos: ``CalibrateView.vue`` (botón "Ver en
vivo" → modal con ``<img src="/api/v1/parkings/{id}/cameras/{cid}/live?token=...">``).

Decisión producto (D1, 2026-10-21): el preview emite a **5 fps** (un
frame cada 200 ms), NO al ritmo de la cámara. Motivo: medido en QA el
modo "tan rápido como la cámara" daba 35 fps y 1,2 MB/s por stream sin
aportar nada a un preview de inspección (el ojo no distingue 5 fps de
25 fps en 720p) y ese ancho de banda lo paga el backend. La latencia
útil para el operador sigue siendo <400 ms.

Contexto histórico (NO se borra): el sprint Latencia-Mínima
(2026-07-07) eliminó el sleep artificial porque el cliente pidió
"tiempo real". Ese modo sigue disponible: el fps viene de la variable
de entorno ``LIVE_PREVIEW_FPS`` (ver ``app/core/config.py``), y con
``LIVE_PREVIEW_FPS=0`` el stream vuelve a ir sin limitador, limitado
sólo por la cámara y la red. El default (5 fps) NO está hardcodeado en
este endpoint: lo aplica ``mjpeg_generator``.

El placeholder gris del SVG NO se sustituye — sólo se añade este botón.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app.core import db as db_mod
from app.core.db import get_db
from app.core.deps import (
    enforce_parking_membership,
    get_current_user_or_query_token,
    oauth2_scheme,
)
from app.models.parking import Camera
from app.models.user import User
from app.services.cameras.live_streams import live_streams
from app.services.cameras.stream import CameraRef, mjpeg_generator

log = logging.getLogger(__name__)

router = APIRouter(prefix="/parkings", tags=["cámaras-live"])


def _parking_context_for_live(
    parking_id: int,
    current: User = Depends(get_current_user_or_query_token),
    db: Session = Depends(get_db),
) -> User:
    """Dep local: RBAC de sucursal + auth header O ``?token=...``.

    Por qué NO usamos el ``parking_context`` global: ese dep depende de
    ``get_current_user`` (sólo ``Authorization: Bearer``), decisión
    deliberada para que el resto de routers REST (CRUD cámaras, geocercas,
    tickets…) no amplíe su superficie de auth. Aquí sí necesitamos el
    fallback de query token porque el consumidor es ``<img>`` del
    CalibrateView, que NO puede setear headers. Usamos
    ``get_current_user_or_query_token`` + ``enforce_parking_membership``
    para mantener el scope de la ampliación a este único endpoint.

    Push security review (2026-07-07): la versión anterior hacía que
    ``parking_context`` dependiera de ``get_current_user_or_query_token``,
    lo cual expandía el scope a TODOS los routers que la usan. Eso
    revertió y se opt-in por endpoint.

    NOTA: este dep **no** se usa en el endpoint del preview (ver
    ``live_preview``): una dependencia con ``Depends(get_db)`` mantiene su
    sesión viva hasta que la respuesta termina, y en un stream eso es
    toda la duración del stream.
    """
    return enforce_parking_membership(current, parking_id, db)


async def _usuario_con_membrescia(parking_id: int, request: Request) -> User:
    """Autenticación + RBAC con una sesión de BD **corta**.

    Por qué no como dependencia: ``Depends(get_db)`` mantiene la sesión
    (y su conexión del pool) viva hasta que la respuesta termina. En un
    endpoint de streaming eso significa **toda la duración del stream**:
    con el objetivo de 50 streams simultáneos eso agota el pool de
    conexiones y deja conexiones *idle in transaction* cuando el stream
    se aborta (bug P1 encontrado por la prueba de carga del 2026-10-21,
    T-13).

    Aquí se abre la sesión, se comprueba y se cierra ANTES de empezar a
    emitir. El comportamiento (401 sin token, 403 sin membresía) es el
    mismo que con dependencias.
    """
    with db_mod.SessionLocal() as db:
        bearer = await oauth2_scheme(request)
        current = get_current_user_or_query_token(
            request=request,
            token=request.query_params.get("token"),
            bearer_token=bearer,
            db=db,
        )
        return enforce_parking_membership(current, parking_id, db)


class _PreviewResponse(StreamingResponse):
    """``StreamingResponse`` que suelta el slot de la cámara al terminar.

    POR QUÉ UNA SUBCLASE Y NO EL ``finally`` DEL GENERADOR (P2 del
    preview, 2026-10-21): cuando el cliente aborta la petición —el
    navegador cerrando el modal— Starlette cancela la tarea del stream.
    El generador asíncrono **no** se cierra en ese momento: su cierre
    lo dispara el finalizador de generadores asíncronos del event loop,
    que puede tardar hasta que el recolector de basura recoge el ciclo
    de referencias. Durante ese hueco el slot de la cámara seguía
    ocupado y el siguiente cliente recibía un 409.

    Aquí la liberación es **determinista**: ``__call__`` termina (por
    el camino normal o por cancelación) y el ``finally`` suelta el
    slot. Además ocurre **antes** de la limpieza bloqueante del
    ``VideoCapture``, que es lo que hace que reabrir la cámara sea
    inmediato.
    """

    def __init__(
        self,
        *args: Any,
        on_finish: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._on_finish = on_finish

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                self._on_finish()
            except Exception as exc:  # noqa: BLE001 — defensiva
                log.warning(
                    "live_preview: no se pudo liberar el slot de la cámara: %s", exc,
                )


@router.get("/{parking_id}/cameras/{camera_id}/live")
async def live_preview(
    parking_id: int,
    camera_id: int,
    request: Request,
) -> StreamingResponse:
    # OJO: aquí NO se usan dependencias con ``Depends(get_db)``. Con esas
    # dependencias la sesión (y su conexión al pool) se mantiene viva
    # hasta que el stream termina: con 50 streams simultáneos —el
    # objetivo de producto— eso agota el pool de conexiones (5 + 10 de
    # salida) y deja conexiones "idle in transaction" cuando el stream
    # se aborta (bug P1 encontrado por la prueba de carga del
    # 2026-10-21, T-13).
    #
    # La sesión se abre, se comprueba auth + RBAC, se lee lo justo de la
    # cámara y se cierra ANTES de empezar a emitir frames; el generador
    # recibe un ``CameraRef`` (sólo id y rtsp_url), no un modelo ORM vivo.
    #
    # Se usa ``db_mod.SessionLocal()`` y no ``from app.core.db import
    # SessionLocal`` a propósito: el nombre importado queda congelado en
    # el momento del import y los tests (que parchean
    # ``app.core.db.SessionLocal``) no lo alcanzarían.
    with db_mod.SessionLocal() as db:
        bearer = await oauth2_scheme(request)
        current = get_current_user_or_query_token(
            request=request,
            token=request.query_params.get("token"),
            bearer_token=bearer,
            db=db,
        )
        enforce_parking_membership(current, parking_id, db)

        cam = (
            db.query(Camera)
            .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
            .one_or_none()
        )
        if not cam:
            raise HTTPException(status_code=404, detail="Cámara no encontrada")
        ref = CameraRef(id=cam.id, rtsp_url=cam.rtsp_url)

    session = live_streams.try_acquire(camera_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una vista en vivo abierta para esta cámara",
        )

    def _liberar_slot() -> None:
        """Libera el slot de la cámara en el registro de streams.

        Se pasa al generador para que la liberación ocurra ANTES de la
        limpieza bloqueante del ``VideoCapture`` (el teardown del RTSP).
        Sin esto, un operador que cerrase el modal y volviese a
        abrirlo recibiría un 409 durante todo el teardown (P2 del
        preview, 2026-10-21).

        El ``session`` identifica **a quién** pertenece el slot: si otro
        cliente ya lo ha tomado, esta llamada no lo toca.
        """
        live_streams.release(camera_id, session)

    async def safe_gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in mjpeg_generator(
                ref,
                session.shutdown_event,
                request.is_disconnected,
                on_session_end=_liberar_slot,
            ):
                # Sprint Fix-Stale-Sessions (2026-07-08): tras emitir
                # cada chunk (típicamente un frame MJPEG), marcamos la
                # sesión como viva. Si el cliente cierra la pestaña y
                # el socket queda en CLOSE_WAIT, ``is_disconnected()``
                # puede tardar 30-60 s en notificar. Mientras tanto,
                # este heartbeat evita que el registry considere la
                # sesión como huérfana y la libere (lo que provocaría
                # que un cliente legítimo que aún ve frames reciba un
                # cierre abrupto). El balance: si pasan >8 s sin
                # emitir NINGÚN chunk (cliente muerto), la sesión se
                # libera para evitar 409 falsos al siguiente cliente.
                live_streams.heartbeat(camera_id, session)
                yield chunk
        finally:
            # Red de seguridad: el generador ya liberó el slot en su
            # ``finally``, pero si el stream ni siquiera llegó a
            # arrancar, esta llamada es la que lo suelta. Es
            # idempotente y va con la sesión, así que no puede matar el
            # stream de otro cliente que ya haya tomado la cámara.
            live_streams.release(camera_id, session)

    return _PreviewResponse(
        safe_gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
        on_finish=_liberar_slot,
    )