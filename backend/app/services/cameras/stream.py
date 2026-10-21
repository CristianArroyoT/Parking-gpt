"""Generador MJPEG para preview en vivo de una cámara.

Abre ``cv2.VideoCapture`` sobre el ``rtsp_url`` de la cámara y produce
un stream ``multipart/x-mixed-replace`` con un JPEG por frame.

Sprint Latencia-Mínima (2026-07-07): el cliente pidió "tiempo real"
porque el delay acumulado era >1 s. Tres fuentes de retardo
identificadas y corregidas:

1. **Buffer interno de OpenCV** (~4-5 frames) → ``CAP_PROP_BUFFERSIZE=1``.
   Sin esto, ``cap.read()`` siempre devuelve un frame viejo del buffer.
2. **Frames obsoletos acumulados** entre yield y read → se toma el frame
   más reciente del buffer con una única lectura ``cap.grab()`` +
   ``cap.retrieve()`` (ver ``MAX_DISCARD_FRAMES``). No se drena el buffer
   con un bucle cerrado: con un stream en vivo ese bucle nunca termina
   (``grab()`` sólo devuelve False al agotarse el stream), así que el
   generador no llegaría nunca al ``yield`` y el cliente vería el modal
   en negro indefinidamente (bug detectado en QA visual 2026-10-21).
3. **Sleep artificial** entre frames → eliminado. Emitimos al ritmo
   real de cámara + encoding. Si la cámara es 25 fps y la red lo soporta,
   el cliente ve 25 fps; si la cámara es 5 fps, ve 5 fps (sin padding).

Decisión D1 (2026-10-21, plan maestro T-07): el punto 3 anterior se
mantiene en su versión "sin sleep artificial", pero el preview deja de
ir al ritmo de la cámara y se **limita a 5 fps** (intervalo de 0,2 s).

- **Por qué**: el preview en vivo es una herramienta de calibración /
  inspección, no un vídeo. Medido en QA el modo "tan rápido como la
  cámara" daba **35 fps y 1,2 MB/s por stream**, consumiendo CPU y ancho
  de banda del backend para un detalle que el operador apenas puede ver
  (el ojo no distingue 5 fps de 25 fps en un preview de 720p).
  A 5 fps se ahorra ~85 % de CPU/ancho de banda y la latencia útil que
  ve el operador sigue siendo <400 ms (el frame sale en cuanto se
  emite).
  Reverificado el 2026-10-21 con el RTSP de prueba (cámara a 25 fps):
  **4,97 fps / 92,7 KB/s** con el límite frente a **25,01 fps /
  639,4 KB/s** sin limitador → un 85,5 % menos de ancho de banda.
- **Contexto histórico que NO se borra**: el "tiempo real" del sprint
  Latencia-Mínima (2026-07-07) fue un requisito explícito del cliente y
  sigue siendo el modo de diagnóstico. Por eso el límite es
  **configurable por variable de entorno** (``LIVE_PREVIEW_FPS``) y no
  una constante cerrada: con ``LIVE_PREVIEW_FPS=0`` (o cualquier valor
  no positivo) el preview vuelve a "flujo libre, limitado por la
  cámara", es decir, **sin limitador** por parte del backend. Sin tocar
  código.
- El código y la documentación iban contradichos (los docstrings
  anunciaban "5 fps / 200 ms" mientras la constante era 0.0). A partir
  de aquí ambas cosas dicen lo mismo y el test
  ``tests/test_live_preview_fps.py`` blinda que el limitador sea REAL.

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
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, AsyncIterator, Awaitable, Callable

import cv2

from app.core.config import get_settings
from app.models.parking import Camera

log = logging.getLogger(__name__)


# Fps objetivo del preview en vivo (decisión D1, 2026-10-21).
# 5 fps = un frame cada 200 ms. Es el valor por defecto de
# ``LIVE_PREVIEW_FPS``; el valor EFECTIVO en cada ejecución sale de la
# configuración (ver ``resolve_frame_interval_s``), para poder volver al
# "flujo libre" del sprint Latencia-Mínima tocando sólo el entorno.
DEFAULT_PREVIEW_FPS: float = 5.0

# Intervalo entre frames (segundos) DERIVADO del fps objetivo por
# defecto. Antes este nombre valía 0.0 (sin sleep) mientras los
# docstrings anunciaban 0,2 s: la contradicción que arregla T-07.
FRAME_INTERVAL_S: float = 1.0 / DEFAULT_PREVIEW_FPS  # 0.2 s

# Calidad JPEG menor que en ``capture.py`` porque aquí emitimos frames
# continuamente. 70 es buen compromiso: ~30-60 KB por frame a 1280×720
# sin artifacts visibles para reconocimiento de plaza.
JPEG_QUALITY: int = 70

# Nº máximo de frames que se leen por vuelta del bucle exterior para
# quedarnos con el más reciente. 1 = latencia mínima (una lectura).
#
# Por qué NO drenar el buffer con un bucle cerrado (`while grab()`):
# con un stream EN VIVO ese bucle no termina nunca — ``grab()`` sólo
# devuelve False cuando el stream se agota — de modo que el generador
# no llegaría jamás al ``yield`` y el cliente se quedaría mirando el
# modal en negro indefinidamente (bug detectado en QA visual
# 2026-10-21). Con ``CAP_PROP_BUFFERSIZE=1`` el buffer interno ya es
# de un frame, así que una sola lectura equivale al frame más reciente.
MAX_DISCARD_FRAMES: int = 1


def resolve_frame_interval_s(fps: float | None = None) -> float:
    """Convierte el fps objetivo en el intervalo entre frames (segundos).

    Args:
        fps: fps objetivo. ``None`` → se lee ``LIVE_PREVIEW_FPS`` de la
            configuración de la app (ver ``app.core.config.Settings``).

    Returns:
        Segundos entre frames. ``0.0`` significa **sin limitador**: el
        preview va al ritmo de la cámara (modo "flujo libre" del sprint
        Latencia-Mínima, 2026-07-07).

    Por qué un valor no positivo = sin limitador y no un error: el
    cliente puede querer el preview "lo más rápido posible" para
    diagnosticar una cámara lenta, y eso se decide por entorno
    (``LIVE_PREVIEW_FPS=0``), no tocando código.
    """
    if fps is None:
        fps = get_settings().live_preview_fps
    if fps <= 0:
        return 0.0
    return 1.0 / fps


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


async def _esperar_para_respetar_fps(
    last_emit_at: float | None, interval_s: float,
) -> float:
    """Espera lo que falte para no emitir por encima del fps objetivo.

    Args:
        last_emit_at: instante (monotónico) del último frame emitido, o
            ``None`` si todavía no se ha emitido ninguno.
        interval_s: intervalo mínimo entre frames. ``0.0`` = sin
            limitador (no se espera nada).

    Returns:
        El instante (monotónico) de la emisión de este frame.

    Por qué NO un ``sleep(interval_s)`` ciego: añadiría latencia
    artificial cuando el trabajo real (captura + encode) ya ha tardado
    más que el intervalo, y en el caso contrario iría por detrás del
    ritmo objetivo. Aquí la espera es ``interval - (tiempo real
    transcurrido desde la última emisión)``, es decir, sólo el hueco que
    falta. Si el tiempo real ya supera el intervalo, no se espera nada:
    el límite lo marca la cámara, no nosotros.
    """
    ahora = time.monotonic()
    if interval_s > 0 and last_emit_at is not None:
        restante = interval_s - (ahora - last_emit_at)
        if restante > 0:
            await asyncio.sleep(restante)
            ahora = time.monotonic()
    return ahora


def _open_capture(rtsp_url: str) -> cv2.VideoCapture:
    """Abre el VideoCapture forzando buffer interno = 1.

    CAP_PROP_BUFFERSIZE no está soportado por todos los backends (FFmpeg
    lo ignora en RTSP y usa su propio buffer de decodificación), pero
    ponerlo deja claro el intent: queremos el frame más reciente, no
    los 4-5 frames que el decoder acumula.

    Con la URL **vacía**, OpenCV revienta con una aserción de C++
    ("!_filename.empty()") que ensucia el log en cada intento. Se
    comprueba antes de abrir (2026-10-21): una cámara sin URL es un
    dato inválido, no un fallo de red.
    """
    if not (rtsp_url or "").strip():
        log.warning("mjpeg: la cámara no tiene URL de RTSP: no se abre nada")
        return cv2.VideoCapture()
    cap = cv2.VideoCapture(rtsp_url)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 — defensiva
        pass
    return cap


@dataclass(frozen=True)
class CameraRef:
    """Datos mínimos de una cámara para el preview en vivo.

    Existe para que el preview **no mantenga una sesión de BD abierta
    durante todo el stream**. Con ``Depends(get_db)`` la sesión (y su
    conexión al pool) se queda viva hasta que el stream termina: con el
    objetivo de 50 streams simultáneos eso **agota el pool** de
    conexiones (5 + 10 de salida) y las conexiones quedan *idle in
    transaction* cuando el stream se aborta (bug P1 encontrado por la
    prueba de carga, T-13).

    El endpoint extrae ``id`` y ``rtsp_url`` y cierra la sesión antes de
    empezar a emitir frames.
    """

    id: int
    rtsp_url: str


class CapturaSincronizada:
    """Envuelve un ``cv2.VideoCapture`` y serializa TODAS sus llamadas.

    Por qué hace falta (bug P0, encontrado por la prueba de carga del
    2026-10-21, T-13): las lecturas se ejecutan con ``asyncio.to_thread``,
    o sea **en un hilo del pool**. Si el cliente cierra el stream
    mientras ese hilo sigue dentro de ``cap.grab()``, el ``finally`` del
    generador llama a ``cap.release()`` **en paralelo con la lectura en
    vuelo**: OpenCV/FFmpeg libera las estructuras internas del decoder
    mientras otro hilo las está usando y el proceso **aborta con
    SIGSEGV (exit 139)**.

    Medido: 4 de 4 reproducciones. En QA el ``--reload`` lo tapa (el
    proceso revierte y aparece como "recarga"), pero **en producción el
    backend entero cae cada vez que un operador cierra el modal de
    previsualización**.

    El lock es un ``threading.Lock`` (NO asyncio) porque las partes
    implicadas viven en hilos distintos: el ``grab()`` en el hilo del
    pool y el ``release()`` en el hilo del event loop. Con este lock,
    ``release()`` **espera** a que termine la lectura en curso en vez de
    competir con ella.

    El coste es acotado: el ``release()`` bloquea el hilo del event loop
    lo que tarde la lectura en curso (milisegundos con una cámara viva).
    Es un precio menor que un SIGSEGV.
    """

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self._cap = cap
        self._lock = threading.Lock()

    def is_opened(self) -> bool:
        with self._lock:
            return bool(self._cap.isOpened())

    def grab(self) -> bool:
        with self._lock:
            return bool(self._cap.grab())

    def retrieve(self) -> tuple[bool, Any]:
        with self._lock:
            return self._cap.retrieve()

    def release(self) -> None:
        with self._lock:
            self._cap.release()


def _liberar_slot(on_session_end: Callable[[], None] | None, camera_id: int) -> None:
    """Invoca el callback de fin de sesión sin dejar que reviente.

    Es deliberadamente **síncrono** y sin ``await``: la liberación del
    slot de la cámara tiene que ocurrir aunque el generador se esté
    cerrando **por cancelación** (el caso real: el navegador aborta la
    petición ``<img>`` y Starlette cancela la tarea del stream). Con un
    ``await`` dentro, la cancelación podría cortarlo y el slot se
    quedaría ocupado hasta el barrido de huérfanas (8 s de 409 para
    quien quisiera reabrir la cámara).
    """
    if on_session_end is None:
        return
    try:
        on_session_end()
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning(
            "mjpeg: fallo liberando el slot de la cámara camera=%s: %s",
            camera_id, exc,
        )


async def _cerrar_captura(cap: CapturaSincronizada, camera_id: int) -> None:
    """Cierra el ``VideoCapture`` FUERA del hilo del event loop.

    Por qué: ``CapturaSincronizada.release()`` espera a que termine la
    lectura en vuelo (el ``threading.Lock``), y esa lectura puede
    quedarse colgada hasta el timeout de FFmpeg (5 s). Si el
    ``release()`` se hiciera en el hilo del event loop, **todo** el
    backend quedaría congelado durante ese tiempo: no sólo ese stream,
    sino cada request en curso.

    El ``await asyncio.to_thread`` delega el trabajo a un hilo del
    pool; si la tarea está siendo cancelada, el ``await`` puede
    cortarse, pero el hilo sigue y el ``release()`` se completa igual.
    """
    try:
        await asyncio.to_thread(cap.release)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning(
            "mjpeg: fallo liberando VideoCapture camera=%s: %s",
            camera_id, exc,
        )


async def mjpeg_generator(
    camera: Camera | CameraRef,
    shutdown_event: asyncio.Event,
    is_disconnected_callable: Callable[[], Awaitable[bool]],
    frame_interval_s: float | None = None,
    on_session_end: Callable[[], None] | None = None,
) -> AsyncIterator[bytes]:
    """Genera frames JPEG multipart hasta que el cliente desconecte.

    Args:
        camera: modelo SQLAlchemy ``Camera`` o un ``CameraRef`` con los
            mismos campos. Se usa **sólo** ``id`` y ``rtsp_url``: el
            preview no mantiene ninguna sesión de BD abierta (ver
            ``CameraRef``).
        shutdown_event: ``asyncio.Event`` que el ``LiveStreamRegistry``
            activa cuando queremos terminar la sesión (registry.release()
            o cierre del modal en el cliente).
        is_disconnected_callable: callable async que devuelve ``True``
            si el cliente HTTP cerró la conexión (FastAPI
            ``Request.is_disconnected()``).
        frame_interval_s: intervalo mínimo entre frames (segundos).
            ``None`` → se usa el valor de ``LIVE_PREVIEW_FPS`` (5 fps por
            defecto). ``0.0`` → sin limitador, al ritmo de la cámara.
        on_session_end: callable **síncrono** que se invoca cuando la
            sesión termina, ANTES de la limpieza del ``VideoCapture``.
            Es el sitio donde el endpoint libera el slot de la cámara en
            el registro de streams (ver el módulo de ``live_streams`` y
            el P2 documentado más abajo).

    Yields:
        Chunk ``multipart/x-mixed-replace`` con la cabecera
        ``--frame\\r\\nContent-Type: image/jpeg\\r\\n...``.

    ORDEN DE LAS FASES AL TERMINAR (P2 del preview, 2026-10-21):

    1. **Liberar el slot del registro** (``on_session_end``). Es
       instantáneo y no puede ser interrumpido por una cancelación.
    2. **Cerrar el ``VideoCapture``**. Puede tardar (el teardown de
       FFmpeg/RTSP espera a la lectura en vuelo) y por eso va **fuera**
       del hilo del event loop.

    El orden importa: si el slot se liberase después del teardown, un
    operador que cerrase el modal y volviese a abrirlo recibiría un
    409 durante todo el teardown (hasta ~8 s con el barrido de
    huérfanas). Y si el teardown se hiciese en el hilo del event loop,
    el backend entero quedaría congelado mientras espera a la lectura en
    vuelo (hasta 5 s: el timeout de FFmpeg).
    """
    # Intervalo efectivo: configuración de la app salvo que el caller
    # pase uno explícito (los tests lo hacen para no depender del env).
    interval_s = resolve_frame_interval_s() if frame_interval_s is None else frame_interval_s
    if interval_s < 0:
        interval_s = 0.0
    try:
        cap_cv = await asyncio.to_thread(_open_capture, camera.rtsp_url)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning(
            "mjpeg: no se pudo instanciar VideoCapture camera=%s: %s",
            camera.id, exc,
        )
        if on_session_end is not None:
            _liberar_slot(on_session_end, camera.id)
        return

    # Todas las llamadas a OpenCV pasan por el wrapper con lock: así
    # ``release()`` nunca compite con un ``grab()`` en vuelo (SIGSEGV,
    # ver CapturaSincronizada).
    cap = CapturaSincronizada(cap_cv)

    if not cap.is_opened():
        log.warning(
            "mjpeg: stream no abierto camera=%s url=%s",
            camera.id, camera.rtsp_url,
        )
        _liberar_slot(on_session_end, camera.id)
        await _cerrar_captura(cap, camera.id)
        placeholder = _placeholder_jpeg()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(placeholder)).encode() + b"\r\n\r\n"
            + placeholder + b"\r\n"
        )
        return

    # Momento (monotónico) del último frame emitido. Sirve para calcular
    # la espera del limitador sobre el tiempo REAL transcurrido.
    last_emit_at: float | None = None

    try:
        while True:
            if shutdown_event.is_set():
                break
            if await is_disconnected_callable():
                break

            # 1) Quedarnos con el frame MÁS RECIENTE disponible.
            #    OJO: no se puede drenar el buffer con un bucle cerrado
            #    (``while grab()``) porque con un stream EN VIVO ese bucle
            #    NUNCA termina — ``grab()`` sólo devuelve False cuando el
            #    stream se agota — así que el generador jamás llegaría al
            #    ``yield`` y el cliente vería el modal en negro para
            #    siempre (bug detectado en QA visual 2026-10-21).
            #    Con ``CAP_PROP_BUFFERSIZE=1`` + una única lectura tomamos
            #    el frame más reciente sin bloquear más de un frame.
            latest_frame = None
            for _ in range(MAX_DISCARD_FRAMES):
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
                last_emit_at = await _esperar_para_respetar_fps(
                    last_emit_at, interval_s,
                )
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
            # LIMITADOR DE FPS (decisión D1, 2026-10-21): aquí, DESPUÉS
            # de leer y codificar el frame, porque el tiempo de captura
            # y de encode cuenta como parte del intervalo. Si el grab +
            # encode ya han tardado más que el intervalo (cámara más
            # lenta que nuestro objetivo), no se espera nada: no
            # añadimos latencia artificial. Un ``sleep(intervalo)`` ciego
            # sí la añadiría y además iría por detrás del ritmo real.
            last_emit_at = await _esperar_para_respetar_fps(
                last_emit_at, interval_s,
            )
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                + payload + b"\r\n"
            )
            # El ritmo lo marca el limitador de arriba: con 5 fps
            # (decisión D1) el cliente recibe un frame cada 200 ms; con
            # ``LIVE_PREVIEW_FPS=0`` lo recibe tan rápido como la cámara
            # produce + cv2 codifica + la red entrega (modo "tiempo real"
            # del sprint Latencia-Mínima 2026-07-07).
    finally:
        # FASE 1: liberar el slot de la cámara (instantáneo, no se puede
        # interrumpir). Va PRIMERO para que quien quiera reabrir la
        # cámara no tenga que esperar al teardown del RTSP.
        _liberar_slot(on_session_end, camera.id)
        # FASE 2: cerrar la captura. Puede tardar y va fuera del hilo
        # del event loop (ver ``_cerrar_captura``).
        await _cerrar_captura(cap, camera.id)
        log.info(
            "mjpeg: stream cerrado camera=%s url=%s",
            camera.id, camera.rtsp_url,
        )