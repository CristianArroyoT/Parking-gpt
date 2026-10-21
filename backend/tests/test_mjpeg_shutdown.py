"""Regresión T-06: el stream MJPEG debe terminar cuando la app se apaga.

Contexto (bug reproducido en QA el 2026-10-21): con una vista en vivo
abierta en el navegador, ``uvicorn --reload`` se quedaba en "Waiting for
connections to close" **para siempre**. Causa: el generador MJPEG sólo
termina si el cliente desconecta o si alguien activa el
``shutdown_event`` de su sesión, y durante el apagado nadie lo activaba.

El síntoma era total: el reloader de uvicorn hace ``process.join()``
antes de arrancar el proceso hijo nuevo, así que el backend entero se
quedaba sin servir (``/health`` → 000, contenedor ``unhealthy``) hasta
que alguien hacía ``docker restart``.

Tests cubiertos aquí:

  1. El generador MJPEG termina en < 2 s cuando se dispara el
     ``shutdown_event`` de la sesión.
  2. ``LiveStreamRegistry.shutdown_all()`` señala todas las sesiones.
  3. El evento de ``lifespan`` de la app cierra los streams vivos.
  4. El hook de señal (SIGTERM/SIGINT) cierra los streams vivos: es la
     ÚNICA pista de apagado que llega ANTES de que uvicorn espere a las
     conexiones abiertas (el ``lifespan`` de uvicorn 0.54 se ejecuta
     después de esa espera, por lo que no basta).
  5. El socket RTSP de FFmpeg tiene timeout: sin él, ``cap.grab`` puede
     quedarse bloqueado para siempre y el generador no terminaría
     nunca aunque se le avise del cierre.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Any

import pytest

from app import main as main_mod
from app.services.cameras.live_streams import live_streams

# Id de cámara ficticio: no colisiona con ninguna cámara real de los
# tests (las de QA van por el 81-135).
_CAMERA_FICTICIA = 987654


class _FakeCapture:
    """Sustituye a ``cv2.VideoCapture`` para no depender de un RTSP real.

    ``grab()`` devuelve False a propósito: el generador emite un frame
    placeholder y sigue el bucle (igual que haría con un RTSP caído),
    así que el stream permanece vivo hasta que se le avisa del cierre.
    """

    instances: list["_FakeCapture"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.opened = True
        self.released = False
        type(self).instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def grab(self) -> bool:
        return False

    def retrieve(self) -> tuple[bool, Any]:
        return False, None

    def release(self) -> None:
        self.released = True


async def _esperar(predicado, limite_s: float = 2.0) -> bool:
    """Espera activa a que ``predicado()`` devuelva True."""
    deadline = time.monotonic() + limite_s
    while time.monotonic() < deadline:
        if predicado():
            return True
        await asyncio.sleep(0.01)
    return bool(predicado())


def test_mjpeg_generator_termina_en_menos_de_2s_al_disparar_el_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresión T-06: con el ``shutdown_event`` activado, el generador
    termina casi inmediatamente (comprobado al inicio de cada iteración)
    y el ``finally`` libera el ``VideoCapture``."""
    from app.services.cameras import stream as stream_mod

    monkeypatch.setattr(stream_mod.cv2, "VideoCapture", _FakeCapture)

    class _Cam:
        id = 1
        rtsp_url = "rtsp://fake.local/stream"

    async def _nunca_desconectado() -> bool:
        return False

    async def _escenario() -> float:
        shutdown_event = asyncio.Event()
        generador = stream_mod.mjpeg_generator(
            _Cam(), shutdown_event, _nunca_desconectado,
        )
        primero = await asyncio.wait_for(generador.__anext__(), timeout=2.0)
        assert primero.startswith(b"--frame")

        shutdown_event.set()
        t0 = time.monotonic()
        try:
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(generador.__anext__(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("el generador MJPEG no terminó en 2 s tras el shutdown")
        return time.monotonic() - t0

    elapsed = asyncio.run(_escenario())
    assert elapsed < 2.0, f"el generador tardó {elapsed:.3f}s en terminar"


def test_shutdown_all_señala_todas_las_sesiones() -> None:
    """``shutdown_all()`` activa el ``shutdown_event`` de todas las sesiones
    vivas y devuelve cuántas ha señalizado."""
    from app.services.cameras.live_streams import LiveStreamRegistry

    async def _escenario() -> tuple[bool, bool, int]:
        registry = LiveStreamRegistry()
        s1 = await registry.try_acquire(1)
        s2 = await registry.try_acquire(2)
        assert s1 is not None
        assert s2 is not None
        notified = await registry.shutdown_all()
        return (
            s1.shutdown_event.is_set(),
            s2.shutdown_event.is_set(),
            notified,
        )

    s1_set, s2_set, notified = asyncio.run(_escenario())
    assert s1_set is True
    assert s2_set is True
    assert notified == 2


def test_lifespan_cierra_los_streams_vivos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Al salir del ``lifespan`` (apagado de la app) los streams vivos
    quedan señalizados para que sus generadores terminen."""
    # ``configure_logging`` reconfigura el logging de todo el proceso:
    # en un test no queremos ese efecto secundario.
    monkeypatch.setattr(main_mod, "configure_logging", lambda: None)

    async def _escenario() -> bool:
        session = await live_streams.try_acquire(_CAMERA_FICTICIA)
        assert session is not None
        try:
            async with main_mod.lifespan(main_mod.app):
                pass
            return session.shutdown_event.is_set()
        finally:
            await live_streams.release(_CAMERA_FICTICIA)

    assert asyncio.run(_escenario()) is True


def test_hook_de_señal_cierra_los_streams_vivos() -> None:
    """SIGTERM/SIGINT cierran los streams vivos.

    Es la pieza que resuelve el cuelgue de QA: uvicorn espera a las
    conexiones abiertas ANTES de lanzar el shutdown del ``lifespan``, así
    que el evento de ``lifespan`` llega demasiado tarde.
    """
    async def _escenario() -> tuple[bool, list[int]]:
        loop = asyncio.get_running_loop()
        recibidos: list[int] = []
        original = signal.getsignal(signal.SIGTERM)
        # Handler previo "de mentira": hace de uvicorn, que es quien
        # realmente ordena el apagado. Lo comprobamos al final.
        signal.signal(signal.SIGTERM, lambda s, f: recibidos.append(s))
        try:
            main_mod._instalar_hook_cierre_streams(loop)
            session = await live_streams.try_acquire(_CAMERA_FICTICIA)
            assert session is not None
            handler = signal.getsignal(signal.SIGTERM)
            assert getattr(handler, "_solidapp_live_shutdown_hook", False), (
                "el hook de señal no quedó instalado"
            )
            # Simulamos la llegada de SIGTERM. NO la enviamos de verdad:
            # mataría el proceso de pytest.
            handler(signal.SIGTERM, None)
            ok = await _esperar(lambda: session.shutdown_event.is_set())
            return ok, recibidos
        finally:
            main_mod._restaurar_hook_cierre_streams()
            signal.signal(signal.SIGTERM, original)
            await live_streams.release(_CAMERA_FICTICIA)

    ok, recibidos = asyncio.run(_escenario())
    assert ok is True, "SIGTERM no cerró los streams vivos"
    assert recibidos == [signal.SIGTERM], (
        "el handler anterior (el de uvicorn) dejó de ejecutarse"
    )


def test_timeout_de_socket_rtsp_esta_configurado() -> None:
    """El socket RTSP de FFmpeg tiene timeout (5 s).

    Sin él, ``await asyncio.to_thread(cap.grab)`` puede quedarse
    bloqueado indefinidamente si el NVR desaparece: el generador no
    volvería a mirar el ``shutdown_event`` y el stream no terminaría
    nunca (el thread del executor tampoco se puede matar).
    """
    assert main_mod.FFMPEG_TIMEOUT_CAPTURE_OPTIONS.startswith("timeout;")
    assert os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
