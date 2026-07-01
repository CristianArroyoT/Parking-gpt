"""Heartbeat ligero: abre RTSP y llama ``grab()`` sin decodificar el frame.

A diferencia de ``app.services.cameras.capture.grab_frame``, este módulo
NO decodifica el JPEG — sólo verifica que el servidor RTSP responde y
entrega un frame en su cola interna. Esto es ~5-10x más rápido que un
read() completo y permite sondear todas las cámaras cada 60 segundos
sin saturar la CPU ni el ancho de banda.

Igual que ``grab_frame``:
- Ejecuta OpenCV en ``asyncio.to_thread`` para no bloquear el event loop.
- Impone un timeout real con ``asyncio.wait_for`` (OpenCV no soporta
  timeout nativo en ``VideoCapture.open()`` ni en ``grab()``).
- **Nunca propaga excepciones**: cualquier fallo devuelve ``False`` y se
  loguea. Coherente con la regla "módulo cameras: nunca propaga excepción,
  devuelve None".

Uso:
    cam = db.get(Camera, cam_id)
    if not await probe_camera(cam):
        record_camera_offline(cam, kind="heartbeat")
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    from app.models.parking import Camera

log = logging.getLogger(__name__)

# Timeout por probe. Bien por encima del periodo del beat (60s) para no
# solapar probes si una cámara se cuelga.
DEFAULT_TIMEOUT_S: float = 5.0


def _probe_sync(rtsp_url: str) -> bool:
    """Abre RTSP, llama ``grab()`` y devuelve True si el frame está en cola.

    Helper síncrono ejecutado en thread pool. Devuelve ``False`` ante
    cualquier fallo (open, isOpened, grab, excepción); nunca propaga.
    """
    cap = None
    try:
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            log.warning(
                "heartbeat: stream no abierto (URL inválida o sin red): %s", rtsp_url
            )
            return False
        if not cap.grab():
            log.warning("heartbeat: grab() devolvió False: %s", rtsp_url)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("heartbeat: error inesperado con %s: %s", rtsp_url, exc)
        return False
    finally:
        if cap is not None:
            cap.release()


async def probe_camera(
    camera: Camera, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> bool:
    """Sondea la cámara con un handshake RTSP ligero.

    Args:
        camera: modelo SQLAlchemy con ``rtsp_url`` válido.
        timeout_s: segundos máximos para el probe completo
            (incluye apertura del stream + ``grab()``).

    Returns:
        ``True`` si el servidor RTSP responde y entrega un frame;
        ``False`` si la URL es inválida, la cámara está caída, el
        handshake falla o se agota el timeout.
        **Nunca propaga excepciones.**
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_probe_sync, camera.rtsp_url),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "heartbeat: timeout tras %.1fs con %s", timeout_s, camera.rtsp_url
        )
        return False
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning("heartbeat: error inesperado: %s", exc)
        return False


__all__ = ["probe_camera"]