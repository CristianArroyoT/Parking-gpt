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
    200  multipart/x-mixed-replace; boundary=frame (5 fps)
    401  sin token (ni header ni query)
    403  usuario sin membresía en el parking
    404  cámara no pertenece al parking del path
    409  ya hay otro stream activo para esta cámara

Callers frontend previstos: ``CalibrateView.vue`` (botón "Ver en
vivo" → modal con ``<img src="/api/v1/parkings/{id}/cameras/{cid}/live?token=...">``).

Decisión producto: 5 fps (cada 200 ms). El placeholder gris del
SVG NO se sustituye — sólo se añade este botón.
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