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
from typing import TYPE_CHECKING, Any

import cv2

if TYPE_CHECKING:
    from app.models.parking import Camera

log = logging.getLogger(__name__)

# Timeout por probe. Bien por encima del periodo del beat (60s) para no
# solapar probes si una cámara se cuelga.
DEFAULT_TIMEOUT_S: float = 5.0


def _abrir_captura(rtsp_url: str, timeout_s: float) -> Any:
    """Abre la captura RTSP **con timeout de apertura y de lectura**.

    T-112 (2026-10-23): sin esto, el timeout de FFmpeg era el suyo por
    defecto (30 s), asi que el ``timeout_s`` del probe (5 s) **no se
    cumplia**: medido, una camara colgada hacia que el probe tardase
    30,12 s en vez de 5. Y como la ronda espera a los hilos del executor
    (Python 3.11 espera hasta 300 s), la ronda entera se alargaba:
    con el healthcheck del worker en 20 s, el contenedor se marcaba
    unhealthy y Docker lo reiniciaba (con ``restart: unless-stopped``,
    T-101) -> bucle de reinicios mientras una camara colgase.

    Los parametros se pasan en la **apertura** (en OpenCV, ``cap.set()``
    despues de abrir ya no cambia el tiempo de espera).
    """
    params = []
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        params.append(int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC))
        params.append(int(timeout_s * 1000))
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params.append(int(cv2.CAP_PROP_READ_TIMEOUT_MSEC))
        params.append(int(timeout_s * 1000))
    if params:
        return cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, params)
    return cv2.VideoCapture(rtsp_url)


def _probe_sync(rtsp_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> bool:
    """Abre RTSP, llama ``grab()`` y devuelve True si el frame está en cola.

    Helper síncrono ejecutado en thread pool. Devuelve ``False`` ante
    cualquier fallo (open, isOpened, grab, excepción); nunca propaga.
    """
    cap = None
    try:
        if not (rtsp_url or "").strip():
            # URL vacía: OpenCV lanza una aserción de C++
            # ("!_filename.empty()") en cada sondeo. Es un dato
            # inválido, no un fallo de red.
            log.warning("heartbeat: la cámara no tiene URL de RTSP")
            return False
        cap = _abrir_captura(rtsp_url, timeout_s)
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
            asyncio.to_thread(_probe_sync, camera.rtsp_url, timeout_s),
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