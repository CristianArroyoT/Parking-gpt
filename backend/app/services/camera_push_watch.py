"""Vigila que las camaras **sigan empujando lecturas** (T-164).

El pipeline real de lectura es el push externo a
``POST /parkings/{id}/plates-detected``. La unica vigilancia de OCR
(``OCR_FAILED``) cuelga de ``ping_camera``, que **no se despacha**: en el
camino real de datos, nadie comprobaba que la camara siguiera hablando.

Este modulo responde a eso: para cada camara activa, mira cuando fue el
**ultimo push** (``plates_detected``) y avisa si hace demasiado que no
llega.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.parking import Camera
from app.models.plates_detected import PlatesDetected

log = logging.getLogger(__name__)


def _aware(momento: datetime | None) -> datetime | None:
    """Normaliza a UTC (SQLite devuelve los datetimes *naive*)."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def ultimos_pushes(db: Session) -> dict[int, datetime]:
    """``{camera_id: ultimo push}`` de todas las camaras que han empujado."""
    filas = (
        db.query(PlatesDetected.camera_id, func.max(PlatesDetected.detected_at))
        .group_by(PlatesDetected.camera_id)
        .all()
    )
    salida: dict[int, datetime] = {}
    for camera_id, momento in filas:
        normalizado = _aware(momento)
        if normalizado is not None:
            salida[int(camera_id)] = normalizado
    return salida


def camaras_sin_push(
    db: Session,
    *,
    minutos_max: int,
    ahora: datetime | None = None,
    skip_prefixes: tuple[str, ...] = (),
) -> list[tuple[Camera, datetime | None]]:
    """Las camaras activas que llevan demasiado sin empujar lecturas.

    Devuelve ``[(cámara, último_push)]``; ``último_push`` es ``None`` si
    la camara **nunca** ha empujado nada.
    """
    momento = ahora if ahora is not None else datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    corte = momento - timedelta(minutes=minutos_max)

    ultimos = ultimos_pushes(db)
    silenciosas: list[tuple[Camera, datetime | None]] = []
    for camera in db.query(Camera).filter(Camera.is_active.is_(True)).all():
        if any(camera.rtsp_url.startswith(p) for p in skip_prefixes):
            # Camaras de demo: no empujan nada y no deben avisar.
            continue
        ultimo = ultimos.get(camera.id)
        if ultimo is None or ultimo < corte:
            silenciosas.append((camera, ultimo))
    return silenciosas
