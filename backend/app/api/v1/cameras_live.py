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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import (
    enforce_parking_membership,
    get_current_user_or_query_token,
)
from app.models.parking import Camera
from app.models.user import User
from app.services.cameras.live_streams import live_streams
from app.services.cameras.stream import mjpeg_generator

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
    """
    return enforce_parking_membership(current, parking_id, db)


@router.get("/{parking_id}/cameras/{camera_id}/live")
async def live_preview(
    parking_id: int,
    camera_id: int,
    request: Request,
    _user: User = Depends(get_current_user_or_query_token),
    _ctx: User = Depends(_parking_context_for_live),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    cam = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not cam:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")

    session = await live_streams.try_acquire(camera_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una vista en vivo abierta para esta cámara",
        )

    async def safe_gen():
        try:
            async for chunk in mjpeg_generator(
                cam,
                session.shutdown_event,
                request.is_disconnected,
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
                await live_streams.heartbeat(camera_id)
                yield chunk
        finally:
            await live_streams.release(camera_id)

    return StreamingResponse(
        safe_gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )