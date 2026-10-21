"""Registry in-memory de streams MJPEG activos por cámara.

Caller único: ``app/api/v1/cameras_live.py``. No expone API HTTP,
sólo métodos de registro (``try_acquire`` / ``release`` / ``heartbeat``)
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

API SÍNCRONA (cambio del 2026-10-21, P2 del preview): los métodos ya
no son ``async``. El motivo es concreto, no de estilo:

  - El slot de la cámara tiene que liberarse **antes** de la limpieza
    bloqueante del ``VideoCapture`` (el teardown de FFmpeg/RTSP puede
    tardar segundos). Ese ``finally`` vive en un generador asíncrono
    que puede ser cerrado **por cancelación**: si la liberación
    necesrase un ``await``, una cancelación podría cortarla y el slot
    se quedaría ocupado hasta el barrido de huérfanas (8 s).
  - Con métodos síncronos la liberación es una operación atómica que
    **ninguna** cancelación puede interrumpir.

  Por eso el lock es un ``threading.Lock`` y no un ``asyncio.Lock``:
  con métodos síncronos el lock tiene que poder usarse desde
  cualquier hilo, y además un ``asyncio.Lock`` ata el registro a un
  event loop concreto (el registry es un singleton de proceso, pero los
  tests creaban registries en loops distintos: ver el test de
  concurrencia de ``test_cameras_live.py``).

  El coste medido sigue siendo irrelevante: ``heartbeat`` es la
  operación caliente (una por frame emitido) y con el lock cuesta
  0,63 µs frente a 0,11 µs sin lock. El hot-path del MJPEG emite a
  ~5 fps (decisión D1), así que el lock se come una fracción
  irrelevante del presupuesto de un frame (200 ms).
"""
from __future__ import annotations

import asyncio
import threading
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
        # asyncio.Event sin loop asociado: ``set()`` no toca el loop
        # (sólo ``wait()`` lo haría), así que el registro puede ser
        # manipulado desde cualquier hilo.
        self.shutdown_event = asyncio.Event()

    def __repr__(self) -> str:  # pragma: no cover — sólo para depurar
        return f"<_LiveSession camera_id={self.camera_id}>"


class LiveStreamRegistry:
    """Registro de streams vivos. Métodos síncronos (ver el docstring
    del módulo para el porqué)."""

    def __init__(self) -> None:
        self._active: dict[int, _LiveSession] = {}
        self._lock = threading.Lock()

    def _cleanup_stale_locked(self) -> int:
        """Suelta sesiones sin heartbeat reciente.

        Asume que ``self._lock`` ya está tomado por el caller
        (``try_acquire``). Devuelve cuántas sesiones se liberaron.
        """
        now = time.monotonic()
        stale = [
            cid for cid, s in self._active.items()
            if now - s.last_heartbeat > STALE_AFTER_S
        ]
        for cid in stale:
            session = self._active.pop(cid, None)
            if session is not None:
                session.shutdown_event.set()
        return len(stale)

    def try_acquire(self, camera_id: int) -> _LiveSession | None:
        """Reserva la cámara para un nuevo stream.

        Antes de comprobar disponibilidad, barre las sesiones huérfanas
        (sin heartbeat reciente) para evitar 409 falsos provocados por
        sockets TCP en CLOSE_WAIT tras un cierre de pestaña.

        Devuelve la ``_LiveSession`` o ``None`` si ya hay un stream
        activo (el caller responderá 409).
        """
        with self._lock:
            self._cleanup_stale_locked()
            if camera_id in self._active:
                return None
            session = _LiveSession(camera_id)
            self._active[camera_id] = session
            return session

    def heartbeat(self, camera_id: int, session: "_LiveSession | None" = None) -> None:
        """Marca la sesión como viva. Llamar tras emitir cada chunk
        (típicamente cada frame). Si la sesión ya fue liberada, no
        hace nada — el generador está cerrando.

        Con ``session`` el heartbeat es **idempotente y seguro**: sólo
        refresca la sesión que ocupa el slot. Sin él (uso legacy) se
        refresca la que haya, sea cual sea. Ver ``release`` para el
        porqué de esto.

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
           crezca y necesite más trabajo.

        POR QUÉ EL COSTE ES ACEPTABLE (medido en este repo, 200 000
        llamadas): sin lock 0,11 µs/llamada, con lock 0,63 µs/llamada
        → 0,52 µs de diferencia. El hot-path del MJPEG emite a ~5 fps
        (decisión D1, 2026-10-21), así que el lock se come el 0,0003 %
        del presupuesto de un frame (200 ms). Además, un lock no
        disputado devuelve sin ceder el control: no añade latencia ni
        un tick al bucle de frames.
        """
        with self._lock:
            session_actual = self._active.get(camera_id)
            if session_actual is None:
                return
            if session is not None and session_actual is not session:
                # El slot ya es de otro cliente: no lo refrescamos
                # (su propio generador ya lo está haciendo).
                return
            session_actual.last_heartbeat = time.monotonic()

    def release(
        self, camera_id: int, session: "_LiveSession | None" = None,
    ) -> bool:
        """Libera la cámara y activa ``shutdown_event`` para que el
        generador MJPEG termine en la próxima iteración.

        El ``pop`` y el ``set`` van DENTRO del lock a propósito: así la
        sesión desaparece del registro y se avisa a su generador en un
        solo paso atómico. Si el ``set`` quedara fuera, un cliente nuevo
        podría reservar la cámara en el hueco, y el ``finally`` del
        generador viejo (que también llama a ``release``) acabaría
        liberando la sesión del cliente nuevo.

        Args:
            camera_id: cámara de la que se quiere liberar el slot.
            session: la sesión que se considera propiedad de esta
                llamada. Si se pasa, el slot **sólo** se libera si la
                sesión que lo ocupa es esa misma. Sin ella se libera
                la que haya (uso legacy y tests).

        Returns:
            ``True`` si esta llamada liberó el slot, ``False`` si no
            había slot o si el slot era de otra sesión.

        POR QUÉ IMPORTA EL ``session`` (arreglo de la LIMITACIÓN
        CONOCIDA del 2026-10-21): antes, ``release`` sólo recibía el
        ``camera_id``, así que no podía saber a qué sesión pertenecía
        la llamada. Si la sesión A se liberaba por otra vía (barrido de
        huérfanas o apagado) y un cliente nuevo tomaba la cámara antes
        de que el ``finally`` del generador de A llamara a ``release``,
        ese ``release`` liberaba la sesión del cliente nuevo y le
        mataba el stream. Con el ``session`` la comprobación es por
        identidad: la sesión de otro cliente no se toca.
        """
        with self._lock:
            actual = self._active.get(camera_id)
            if actual is None:
                return False
            if session is not None and actual is not session:
                # El slot ya pertenece a otro cliente: no se toca.
                return False
            del self._active[camera_id]
            actual.shutdown_event.set()
            return True

    def shutdown_all(self) -> int:
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

        (Con el ``release`` por sesión que hay ahora, ese escenario ya
        no puede matar el stream de nadie, pero mantener el slot hasta
        que el generador winds down sigue siendo lo correcto: durante
        el apagado no tiene sentido abrir un stream nuevo.)

        Returns the number of sessions notified.
        """
        with self._lock:
            sessions = list(self._active.values())
            for session in sessions:
                session.shutdown_event.set()
        return len(sessions)

    def active_count(self) -> int:
        return len(self._active)


# Singleton de proceso (thread-safe: todas las mutaciones pasan por
# ``self._lock``).
live_streams = LiveStreamRegistry()
