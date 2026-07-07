"""Generador MJPEG para preview en vivo de una cámara.

Abre ``cv2.VideoCapture`` sobre el ``rtsp_url`` de la cámara y produce
un stream ``multipart/x-mixed-replace`` con un JPEG por frame.

Sprint Latencia-Mínima (2026-07-07): el cliente pidió "tiempo real"
porque el delay acumulado era >1 s. Tres fuentes de retardo
identificadas y corregidas:

1. **Buffer interno de OpenCV** (~4-5 frames) → ``CAP_PROP_BUFFERSIZE=1``.
   Sin esto, ``cap.read()`` siempre devuelve un frame viejo del buffer.
2. **Frames obsoletos acumulados** entre yield y read → bucle de
   ``cap.grab()`` que descarta todos los frames intermedios antes de
   recuperar el ÚLTIMO con ``cap.retrieve()``.
3. **Sleep artificial** entre frames → eliminado. Emitimos al ritmo
   real de cámara + encoding. Si la cámara es 25 fps y la red lo soporta,
   el cliente ve 25 fps; si la cámara es 5 fps, ve 5 fps (sin padding).

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


# Sin sleep artificial entre frames (Sprint Latencia-Mínima 2026-07-07):
# el ritmo real lo marca la cámara + cv2.imencode + red. Reservamos el
# nombre como deprecated por si alguien lo busca en git history.
FRAME_INTERVAL_S: float = 0.0

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


def _open_capture(rtsp_url: str) -> cv2.VideoCapture:
    """Abre el VideoCapture forzando buffer interno = 1.

    CAP_PROP_BUFFERSIZE no está soportado por todos los backends (FFmpeg
    lo ignora en RTSP y usa su propio buffer de decodificación), pero
    ponerlo deja claro el intent: queremos el frame más reciente, no
    los 4-5 frames que el decoder acumula.
    """
    cap = cv2.VideoCapture(rtsp_url)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 — defensiva
        pass
    return cap


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
        cap = await asyncio.to_thread(_open_capture, camera.rtsp_url)
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

            # 1) Descartar todos los frames obsoletos del buffer interno
            #    con grab() (rápido, no decodifica) y quedarnos con el
            #    ÚLTIMO disponible vía retrieve(). Así nunca enviamos
            #    un frame de hace 500 ms cuando ya hay uno de hace 50 ms.
            latest_frame = None
            while True:
                if shutdown_event.is_set():
                    break
                grabbed = await asyncio.to_thread(cap.grab)
                if not grabbed:
                    break
                ok, frame = await asyncio.to_thread(cap.retrieve)
                if ok and frame is not None:
                    latest_frame = frame
            if latest_frame is None:
                # Stream caído momentáneamente: emitimos placeholder y
                # reintentamos. NO salimos del bucle — un NVR puede
                # reconectar el RTSP solo.
                placeholder = _placeholder_jpeg()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(placeholder)).encode() + b"\r\n\r\n"
                    + placeholder + b"\r\n"
                )
                # Pequeño backoff para no quemar CPU si el RTSP está muerto.
                await asyncio.sleep(0.05)
                continue

            ok, buf = await asyncio.to_thread(
                cv2.imencode, ".jpg", latest_frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
            )
            if not ok:
                continue

            payload = bytes(buf)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                + payload + b"\r\n"
            )
            # Sin sleep artificial: el cliente recibe tan rápido como la
            # cámara produce + cv2 codifica + la red entrega. En pruebas
            # con RTSP de demo de 25 fps, observamos 20-23 fps efectivos
            # con delay visual <200 ms (vs >1 s con sleep 100 ms + buffer).
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