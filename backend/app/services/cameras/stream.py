"""Generador MJPEG para preview en vivo de una cámara.

Abre ``cv2.VideoCapture`` sobre el ``rtsp_url`` de la cámara y produce
un stream ``multipart/x-mixed-replace`` con un JPEG por frame. El
intervalo entre frames (``FRAME_INTERVAL_S = 0.2`` ≈ 5 fps) es la
decisión del producto (calibración humana, no sustituye al sistema de
detección automática).

Por qué NO usamos ``grab_frame()`` ya existente: ``grab_frame`` lee
un solo frame y cierra. Para "live" necesitamos mantener el
``VideoCapture`` abierto durante toda la sesión del usuario.

El generador es cooperativo: si el registry externo activa el
``shutdown_event``, la siguiente iteración termina y ``cap.release()``
se ejecuta vía ``finally``. Esto cubre el caso de "el usuario cierra
el modal antes de que llegue la siguiente request".
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import AsyncIterator

import cv2

from app.models.parking import Camera

log = logging.getLogger(__name__)


# Intervalo entre frames: 200 ms = 5 fps (decidido por el producto,
# calibración humana). Ver ``app/services/cameras/capture.py`` para el
# equivalente en captura puntual (mayor calidad, single-frame).
FRAME_INTERVAL_S: float = 0.2

# Calidad JPEG menor que en ``capture.py`` porque aquí emitimos frames
# continuamente. 70 es buen compromiso: ~30-60 KB por frame a 1280×720
# sin artifacts visibles para reconocimiento de plaza.
JPEG_QUALITY: int = 70


@lru_cache(maxsize=1)
def _placeholder_jpeg() -> bytes:
    """JPEG 1×1 negro codificado en runtime.

    Lo generamos en lugar de hardcodear el hex para evitar el riesgo
    de pegarlo mal (los bytes JPEG no son trivialmente serializables
    en un literal). Se cachea porque el mismo buffer se emite cada
    vez que el stream no responde.
    """
    import numpy as np
    black = np.zeros((1, 1, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(
        ".jpg", black, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
    )
    if not ok:
        return b""
    return bytes(buf)


async def mjpeg_generator(
    camera: Camera,
    shutdown_event: asyncio.Event,
    is_disconnected_callable,
) -> AsyncIterator[bytes]:
    """Genera frames JPEG multipart hasta que el cliente desconecte.

    Args:
        camera: modelo SQLAlchemy con ``rtsp_url``.
        shutdown_event: ``asyncio.Event`` que el ``LiveStreamRegistry``
            activa cuando queremos terminar la sesión (registry.release()
            o cierre del modal en el cliente).
        is_disconnected_callable: callable async que devuelve ``True``
            si el cliente HTTP cerró la conexión (FastAPI
            ``Request.is_disconnected()``).

    Yields:
        Chunk ``multipart/x-mixed-replace`` con la cabecera
        ``--frame\\r\\nContent-Type: image/jpeg\\r\\n...``.
    """
    try:
        cap = await asyncio.to_thread(cv2.VideoCapture, camera.rtsp_url)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning(
            "mjpeg: no se pudo instanciar VideoCapture camera=%s: %s",
            camera.id, exc,
        )
        return

    if not cap.isOpened():
        log.warning(
            "mjpeg: stream no abierto camera=%s url=%s",
            camera.id, camera.rtsp_url,
        )
        cap.release()
        placeholder = _placeholder_jpeg()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(placeholder)).encode() + b"\r\n\r\n"
            + placeholder + b"\r\n"
        )
        return

    try:
        while True:
            if shutdown_event.is_set():
                break
            if await is_disconnected_callable():
                break

            ok, frame = await asyncio.to_thread(cap.read)
            if not ok or frame is None:
                # Stream caído momentáneamente: emitimos placeholder y
                # reintentamos. NO salimos del bucle — un NVR puede
                # reconectar el RTSP solo.
                await asyncio.sleep(FRAME_INTERVAL_S)
                placeholder = _placeholder_jpeg()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(placeholder)).encode() + b"\r\n\r\n"
                    + placeholder + b"\r\n"
                )
                continue

            ok, buf = await asyncio.to_thread(
                cv2.imencode, ".jpg", frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
            )
            if not ok:
                await asyncio.sleep(FRAME_INTERVAL_S)
                continue

            payload = bytes(buf)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                + payload + b"\r\n"
            )

            await asyncio.sleep(FRAME_INTERVAL_S)
    finally:
        try:
            cap.release()
        except Exception as exc:  # noqa: BLE001 — defensiva
            log.warning(
                "mjpeg: fallo liberando VideoCapture camera=%s: %s",
                camera.id, exc,
            )
        log.info(
            "mjpeg: stream cerrado camera=%s url=%s",
            camera.id, camera.rtsp_url,
        )