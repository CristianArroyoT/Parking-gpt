"""Captura de un frame JPEG desde el stream RTSP de una cámara.

Aísla el driver OpenCV del resto del código: ping_camera (Celery) sólo
ve `async def grab_frame(camera) -> bytes | None` y nunca propaga
excepciones — un RTSP caído o URL inválida se traduce en `None`, igual
que el cliente OCR cuando el servicio no responde. Esto permite al
worker decidir un fallback (p. ej. placeholder 1×1) sin romperse.

Ejecutar `cv2.VideoCapture` en `asyncio.to_thread` es obligatorio: las
llamadas a OpenCV bloquean el hilo, y dentro de Celery bloquearía el
event loop del worker. `asyncio.wait_for` además impone un timeout
real (OpenCV no soporta timeout nativo en `VideoCapture.read()`).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    from app.models.parking import Camera

log = logging.getLogger(__name__)

# Tiempo máximo por captura. Bien por encima del ping_camera que es 4 s.
DEFAULT_TIMEOUT_S: float = 5.0

# Calidad JPEG al codificar el frame. 80 es buen compromiso tamaño/calidad
# para OCR; valores más altos inflan el payload sin mejorar la detección.
JPEG_QUALITY: int = 80


def _read_one_frame_sync(rtsp_url: str) -> bytes | None:
    """Abre RTSP, lee 1 frame y lo codifica como JPEG.

    Helper síncrono ejecutado en thread pool (asyncio.to_thread). Devuelve
    `None` ante cualquier fallo; nunca propaga excepción.
    """
    try:
        if not (rtsp_url or "").strip():
            # URL vacía: OpenCV lanza una aserción de C++
            # ("!_filename.empty()"). Es un dato inválido, no un fallo
            # de red.
            log.warning("capture: la cámara no tiene URL de RTSP")
            return None
        cap = cv2.VideoCapture(rtsp_url)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("capture: no se pudo instanciar VideoCapture: %s", exc)
        return None
    try:
        if not cap.isOpened():
            log.warning(
                "capture: stream no abierto (URL inválida o sin red): %s", rtsp_url
            )
            return None
        ok, frame = cap.read()
        if not ok or frame is None:
            log.warning("capture: frame vacío de %s", rtsp_url)
            return None
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        )
        if not ok:
            log.warning("capture: fallo codificando JPEG de %s", rtsp_url)
            return None
        return bytes(buf)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("capture: error inesperado con %s: %s", rtsp_url, exc)
        return None
    finally:
        cap.release()


async def grab_frame(
    camera: Camera, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> bytes | None:
    """Captura 1 frame JPEG del stream RTSP de la cámara.

    Args:
        camera: modelo SQLAlchemy con `rtsp_url` válido.
        timeout_s: segundos máximos para la captura completa
            (incluye apertura del stream, lectura y codificación).

    Returns:
        bytes JPEG del frame, o `None` si el stream no responde, la URL
        es inválida, la cámara está caída, la codificación falla o se
        agota el timeout. **Nunca propaga excepciones.**
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_read_one_frame_sync, camera.rtsp_url),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "capture: timeout tras %.1fs con %s", timeout_s, camera.rtsp_url
        )
        return None
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("capture: error inesperado: %s", exc)
        return None