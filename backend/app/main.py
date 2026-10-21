"""Punto de entrada FastAPI: app factory + middlewares + routers.

Ciclo de vida del apagado (T-06 — no lo simplifiques sin leer esto)
-------------------------------------------------------------------
Una vista en vivo mantiene una conexión HTTP abierta para siempre. El
generador MJPEG sólo termina si el cliente desconecta o si se activa el
``shutdown_event`` de su sesión, así que al apagar el servidor hay que
avisarle explícitamente.

Y no basta con avisar en el ``lifespan``: uvicorn 0.54 ejecuta
``await self.lifespan.shutdown()`` DESPUÉS de
``_wait_tasks_to_complete()``, es decir, DESPUÉS de esperar a que
terminen las conexiones abiertas. Con el evento del lifespan solo,
uvicorn se queda en "Waiting for connections to close" para siempre, y
como el reloader hace ``process.join()`` antes de arrancar el hijo
nuevo, el backend entero deja de servir (``/health`` → 000).

Por eso aquí se engancha SIGTERM/SIGINT (la única pista de apagado que
llega ANTES de esa espera) y el evento del ``lifespan`` se queda como
red de seguridad. Ver ``_instalar_hook_cierre_streams``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import AuditMiddleware
from app.schemas import HealthResponse
from app.services.cameras.live_streams import live_streams

log = logging.getLogger(__name__)


# Timeout de E/S del socket RTSP para el backend FFmpeg de OpenCV
# (5 000 000 µs = 5 s). Se fija ANTES de abrir ningún capture.
#
# POR QUÉ: el generador MJPEG hace ``await asyncio.to_thread(cap.grab)``
# y ``to_thread`` no tiene timeout: si el NVR desaparece, FFmpeg se
# queda bloqueado en el socket y el generador NUNCA vuelve a mirar el
# ``shutdown_event`` → el stream no termina nunca y uvicorn se queda
# esperando la conexión para siempre (bug T-06). Medido en QA: sin este
# timeout, la apertura contra un host muerto tarda 21 s; con él, 5 s.
#
# 5 s es holgado para una cámara sana (un frame llega cada 25-200 ms) y
# evita que un NVR caído bloquee el stream indefinidamente. Se usa
# ``setdefault`` para que un operador pueda ajustarlo por entorno.
FFMPEG_TIMEOUT_CAPTURE_OPTIONS = "timeout;5000000"
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", FFMPEG_TIMEOUT_CAPTURE_OPTIONS)


# Marca nuestros handlers de señal (evita instalar el hook dos veces).
_HOOK_FLAG = "_solidapp_live_shutdown_hook"

# Handlers de señal que hemos sustituido, para restaurarlos al salir.
_prev_signal_handlers: dict[int, Any] = {}


def _programar_cierre_streams(
    loop: asyncio.AbstractEventLoop, app: FastAPI
) -> None:
    """Encola el cierre de los streams MJPEG y del evento de apagado.

    Un handler de señal se ejecuta entre dos bytecodes del hilo
    principal: allí no se puede hacer ``await``. Delegamos el trabajo
    real en el event loop con ``call_soon_threadsafe``.
    """
    def _tarea() -> None:
        try:
            # T-06+1: el evento de apagado lo miran los streams SSE
            # (``/parkings/{id}/events``), que si no se cierran también
            # bloquean el apagado de uvicorn.
            app.state.shutdown_event.set()
        except (AttributeError, RuntimeError):  # pragma: no cover
            log.warning("No se pudo marcar el evento de apagado")
        try:
            asyncio.ensure_future(live_streams.shutdown_all(), loop=loop)
        except RuntimeError:  # pragma: no cover — loop ya cerrado
            log.warning("No se pudieron cerrar los streams MJPEG: loop cerrado")

    try:
        loop.call_soon_threadsafe(_tarea)
    except RuntimeError:  # pragma: no cover — loop ya cerrado
        pass


def _instalar_hook_cierre_streams(
    loop: asyncio.AbstractEventLoop, app: FastAPI
) -> None:
    """Engancha SIGTERM/SIGINT para cerrar los streams MJPEG vivos.

    POR QUÉ no basta con el evento de ``lifespan`` (que sería lo
    natural): uvicorn 0.54 ejecuta ``await self.lifespan.shutdown()``
    DESPUÉS de ``_wait_tasks_to_complete()``, es decir, DESPUÉS de
    esperar a que terminen las conexiones abiertas. Y un stream MJPEG
    sólo termina si se activa su ``shutdown_event`` → con el lifespan
    solo, uvicorn se queda en "Waiting for connections to close" para
    siempre. Peor: el reloader de uvicorn hace ``process.join()`` antes
    de arrancar el proceso hijo nuevo, así que el backend entero se
    queda sin servir (``/health`` → 000) hasta un ``docker restart``.

    La señal es la ÚNICA notificación de "el servidor se está apagando"
    que llega ANTES de esa espera, por eso la enganchamos aquí.

    Encadenamos el handler anterior (el de uvicorn, ``handle_exit``, que
    es quien realmente ordena el apagado) para no romper su lógica. Si
    la señal no la gestiona nadie (SIG_DFL/SIG_IGN) no la tocamos: la
    dejaría sin su comportamiento por defecto.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError):  # pragma: no cover
            continue
        if not callable(previous):
            continue
        if getattr(previous, _HOOK_FLAG, False):
            continue

        def _handler(signum: int, frame: Any, _previous: Any = previous) -> None:
            _programar_cierre_streams(loop, app)
            _previous(signum, frame)

        setattr(_handler, _HOOK_FLAG, True)
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):  # pragma: no cover — no es el hilo principal
            continue
        _prev_signal_handlers[sig] = previous


def _restaurar_hook_cierre_streams() -> None:
    """Devuelve las señales a su handler original."""
    for sig, previous in _prev_signal_handlers.items():
        try:
            signal.signal(sig, previous)
        except (ValueError, OSError):  # pragma: no cover
            pass
    _prev_signal_handlers.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sprint Fase 3A: logger JSON / file rotado ANTES de aceptar tráfico.
    configure_logging()
    # T-06: una vista en vivo mantiene una conexión abierta para
    # siempre. Si no se cierra al apagar, uvicorn se queda esperando
    # ("Waiting for connections to close") y el backend deja de
    # responder. Enganchamos la señal de apagado (la única que llega
    # antes de esa espera) y dejamos el evento de lifespan como red de
    # seguridad.
    #
    # T-06+1: el mismo problema afectaba al stream SSE de
    # ``/parkings/{id}/events``, que tampoco miraba ningún evento de
    # apagado. El evento vive en ``app.state`` (no en un global) para que
    # cada instancia de la app tenga el suyo: en los tests se crean
    # varias apps y un global "ya apagado" rompería los streams del
    # resto de tests.
    app.state.shutdown_event = asyncio.Event()
    _instalar_hook_cierre_streams(asyncio.get_running_loop(), app)
    try:
        yield
    finally:
        app.state.shutdown_event.set()
        try:
            cerradas = await live_streams.shutdown_all()
        finally:
            _restaurar_hook_cierre_streams()
        if cerradas:
            log.info("Cerrados %s stream(s) MJPEG vivo(s) por apagado", cerradas)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="solidAPP API",
        version="0.1.0",
        description="Backend de gestión de parkings con OCR (MVP Fase 1).",
        lifespan=lifespan,
    )
    # Sprint Fase 3A: extrae user_id/ip/correlation_id en cada request
    # y los persiste en request.state.audit para los handlers.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0")

    return app


app = create_app()
