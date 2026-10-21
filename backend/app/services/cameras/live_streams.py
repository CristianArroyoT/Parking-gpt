"""Registry in-memory de streams MJPEG activos por cámara.

Caller único: ``app/api/v1/cameras_live.py``. No expone API HTTP,
sólo métodos async ``try_acquire`` / ``release`` / ``heartbeat``
consumidos por el endpoint live.

Previene que dos clientes abran el mismo RTSP simultáneamente sobre
la misma cámara — cada ``cv2.VideoCapture`` abre su propia conexión
TCP al NVR y duplicaría el ancho de banda.

Si un segundo cliente intenta abrir el stream mientras hay uno
activo, el endpoint devuelve 409 Conflict.

Estado se mantiene en proceso: si el backend se reinicia, todos los
streams se liberan (los cv2.VideoCapture desaparecen con el proceso).

Sprint Fix-Stale-Sessions (2026-07-08): cuando el usuario cierra la
pestaña del navegador, el SO tarda entre 30 s y varios minutos en
limpiar el socket TCP (CLOSE_WAIT). Durante ese intervalo, el registry
sigue creyendo que hay una sesión activa y rechaza nuevos intentos
con 409 Conflict. Para evitarlo:

  - ``heartbeat(camera_id)``: el generador MJPEG lo llama cada vez que
    emite un frame. Si pasan ``STALE_AFTER_S`` sin heartbeats, la
    sesión se considera huérfana y se libera automáticamente.
  - ``try_acquire(camera_id)``: también limpia sesiones huérfanas
    antes de comprobar disponibilidad, para que un cliente nuevo
    pueda tomar la cámara aunque haya una sesión muerta pendiente
    de limpieza por el SO.

El umbral ``STALE_AFTER_S = 8`` cubre el peor caso de un stream
legítimo que emite a 1 fps con jitter: 8 s ≈ 8 frames de margen.

Disciplina de lock (T-10, 2026-10-21): TODA mutación del registro pasa
por ``self._lock`` — ``try_acquire``, ``release``, ``_cleanup_stale`` y
``heartbeat``. El lock garantiza la exclusión mutua entre ellas y hace
que el invariante "una sola sesión por cámara" se sostenga por
construcción, sin depender de que nadie introduzca un ``await`` dentro
de una sección crítica. Ver el docstring de ``heartbeat`` para el
balance coste/beneficio medido.
"""
from __future__ import annotations

import asyncio
import time


# Umbral de "sesión huérfana". Si una sesión no recibe heartbeat en
# este tiempo, se considera que el cliente se fue sin notificar y se
# libera el slot. 8 s cubre streams lentos a 1 fps con jitter y
# reap de sockets TCP en CLOSE_WAIT.
STALE_AFTER_S: float = 8.0


class _LiveSession:
    """Sesión activa. ``shutdown_event`` señala al generador que pare."""

    __slots__ = ("camera_id", "started_at", "last_heartbeat", "shutdown_event")

    def __init__(self, camera_id: int) -> None:
        self.camera_id = camera_id
        self.started_at = time.monotonic()
        # Heartbeat inicial: cuando se acquire, el generador aún no ha
        # emitido ningún frame, pero la sesión es joven — no debe ser
        # considerada stale inmediatamente.
        self.last_heartbeat = time.monotonic()
        self.shutdown_event = asyncio.Event()


class LiveStreamRegistry:
    def __init__(self) -> None:
        self._active: dict[int, _LiveSession] = {}
        self._lock = asyncio.Lock()

    async def _cleanup_stale(self) -> None:
        """Suelta sesiones sin heartbeat reciente. Asume que ``_lock``
        ya está tomado por el caller (``try_acquire``)."""
        now = time.monotonic()
        stale = [
            cid for cid, s in self._active.items()
            if now - s.last_heartbeat > STALE_AFTER_S
        ]
        for cid in stale:
            session = self._active.pop(cid, None)
            if session is not None:
                session.shutdown_event.set()

    async def try_acquire(self, camera_id: int) -> _LiveSession | None:
        """Reserva la cámara para un nuevo stream.

        Antes de comprobar disponibilidad, barre las sesiones huérfanas
        (sin heartbeat reciente) para evitar 409 falsos provocados por
        sockets TCP en CLOSE_WAIT tras un cierre de pestaña.

        Devuelve la ``_LiveSession`` o ``None`` si ya hay un stream
        activo (el caller responderá 409).
        """
        async with self._lock:
            await self._cleanup_stale()
            if camera_id in self._active:
                return None
            session = _LiveSession(camera_id)
            self._active[camera_id] = session
            return session

    async def heartbeat(self, camera_id: int) -> None:
        """Marca la sesión como viva. Llamar tras emitir cada chunk
        (típicamente cada frame). Si la sesión ya fue liberada, no
        hace nada — el generador está cerrando.

        POR QUÉ TOMA EL LOCK (aunque ``heartbeat`` sólo haga un
        ``dict.get`` + escribir un float):

        1. **Uniformidad del invariante.** Todas las mutaciones del
           registro (``try_acquire``, ``release``, ``_cleanup_stale`` y
           ``heartbeat``) pasan por el mismo lock. Así, por construcción,
           "una sola sesión por cámara" no depende de que nadie añada
           un ``await`` dentro de una sección crítica.
        2. **Lo que SÍ protege**: ``_cleanup_stale`` lee
           ``last_heartbeat`` y decide si la sesión es huérfana. Hoy esa
           lectura y el ``pop`` son operaciones síncronas (sin puntos de
           suspensión), así que en un único event loop ya son atómicas;
           con el lock, lo seguirán siendo aunque ``_cleanup_stale``
           crezca y necesite un ``await``.

        POR QUÉ EL COSTE ES ACEPTABLE (medido en este repo, 200 000
        llamadas): sin lock 0,11 µs/llamada, con lock 0,63 µs/llamada
        → 0,52 µs de diferencia. El hot-path del MJPEG emite a ~35 fps,
        así que el lock se come un 0,0001 % del presupuesto de un frame
        (28 ms). Además, un ``asyncio.Lock`` no disputado devuelve sin
        ceder el control: no añade latencia ni un tick al bucle de
        frames.
        """
        async with self._lock:
            session = self._active.get(camera_id)
            if session is not None:
                session.last_heartbeat = time.monotonic()

    async def release(self, camera_id: int) -> None:
        """Libera la cámara y activa ``shutdown_event`` para que el
        generador MJPEG termine en la próxima iteración.

        El ``pop`` y el ``set`` van DENTRO del lock a propósito: así la
        sesión desaparece del registro y se avisa a su generador en un
        solo paso atómico. Si el ``set`` quedara fuera, un cliente nuevo
        podría reservar la cámara en el hueco, y el ``finally`` del
        generador viejo (que también llama a ``release``) acabaría
        liberando la sesión del cliente nuevo.

        LIMITACIÓN CONOCIDA: ``release`` sólo recibe el ``camera_id``, así
        que no puede saber a qué sesión pertenece la llamada. Si la
        sesión A se libera por otra vía (barrido de huérfanas o apagado)
        y un cliente nuevo toma la cámara antes de que el ``finally`` del
        generador de A llame a ``release``, ese ``release`` liberaría la
        sesión del cliente nuevo. Arreglarlo de raíz exige pasar la
        sesión a ``release`` desde ``cameras_live.py``.
        """
        async with self._lock:
            session = self._active.pop(camera_id, None)
            if session is not None:
                session.shutdown_event.set()

    async def shutdown_all(self) -> int:
        """Signal ALL live sessions to close (application shutdown).

        Each session's ``shutdown_event`` is activated, so the MJPEG
        generator detects it at the top of the next iteration and
        finishes, closing the HTTP response. That's what allows uvicorn
        to complete the graceful shutdown instead of waiting forever for
        a connection that would never close.

        WHY WE DON'T EMPTY ``_active`` HERE: the generators are still
        alive until they see their ``shutdown_event``. If we removed the
        session from the dict now, a new client could reserve the
        camera, and when the old generator finished, its ``finally``
        would call ``release(camera_id)`` and release the NEW client's
        session (killing its stream). Leaving the session in the dict
        keeps the slot busy until the generator itself releases it:
        correct behaviour, and the new client gets a transient 409 that
        it retries.

        Returns the number of sessions notified.
        """
        async with self._lock:
            sessions = list(self._active.values())
            for session in sessions:
                session.shutdown_event.set()
        return len(sessions)

    def active_count(self) -> int:
        return len(self._active)


# Singleton de proceso (no thread-safety extra: FastAPI corre en un
# único event loop).
live_streams = LiveStreamRegistry()