"""Registry in-memory de streams MJPEG activos por cámara.

Caller único: ``app/api/v1/cameras_live.py``. No expone API HTTP,
sólo métodos async ``try_acquire`` / ``release`` consumidos por el
endpoint live.

Previene que dos clientes abran el mismo RTSP simultáneamente sobre
la misma cámara — cada ``cv2.VideoCapture`` abre su propia conexión
TCP al NVR y duplicaría el ancho de banda.

Si un segundo cliente intenta abrir el stream mientras hay uno
activo, el endpoint devuelve 409 Conflict.

Estado se mantiene en proceso: si el backend se reinicia, todos los
streams se liberan (los cv2.VideoCapture desaparecen con el proceso).
"""
from __future__ import annotations

import asyncio
import time


class _LiveSession:
    """Sesión activa. ``shutdown_event`` señala al generador que pare."""

    __slots__ = ("camera_id", "started_at", "shutdown_event")

    def __init__(self, camera_id: int) -> None:
        self.camera_id = camera_id
        self.started_at = time.monotonic()
        self.shutdown_event = asyncio.Event()


class LiveStreamRegistry:
    def __init__(self) -> None:
        self._active: dict[int, _LiveSession] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, camera_id: int) -> _LiveSession | None:
        """Reserva la cámara para un nuevo stream.

        Devuelve la ``_LiveSession`` o ``None`` si ya hay un stream
        activo (el caller responderá 409).
        """
        async with self._lock:
            if camera_id in self._active:
                return None
            session = _LiveSession(camera_id)
            self._active[camera_id] = session
            return session

    async def release(self, camera_id: int) -> None:
        """Libera la cámara y activa ``shutdown_event`` para que el
        generador MJPEG termine en la próxima iteración."""
        async with self._lock:
            session = self._active.pop(camera_id, None)
        if session is not None:
            session.shutdown_event.set()

    def active_count(self) -> int:
        return len(self._active)


# Singleton de proceso (no thread-safety extra: FastAPI corre en un
# único event loop).
live_streams = LiveStreamRegistry()