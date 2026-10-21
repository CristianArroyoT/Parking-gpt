"""Tests del registro de streams vivos (``LiveStreamRegistry``).

Cubre el T-10 del plan maestro: blindar el registro para que dos
clientes simultáneos sobre la misma cámara se comporten de forma
determinista (uno recibe el video, el otro un 409) y las sesiones
huérfanas se liberen solas.

API **síncrona** desde el 2026-10-21 (P2 del preview): la liberación del
slot tiene que ser una operación que ninguna cancelación pueda
interrumpir, y además tiene que ocurrir **antes** de la limpieza
bloqueante del ``VideoCapture``. Un ``await`` no cumplía ninguna de las
dos condiciones.

Casos cubiertos:
  1. ``try_acquire`` reserva la cámara; la segunda llamada la rechaza.
  2. ``try_acquire`` concurrente (5 hilos a la vez): sólo uno gana.
  3. ``heartbeat`` actualiza el timestamp de la sesión.
  4. ``heartbeat`` de una cámara sin sesión no rompe nada.
  5. Sesión huérfana (> ``STALE_AFTER_S`` sin heartbeat) → se libera.
  6. ``release`` avisa al generador (``shutdown_event``) y libera el slot.
  7. ``shutdown_all`` señala todas las sesiones vivas SIN vaciar el
     registro (decisión de diseño: el slot sigue ocupado hasta que el
     generador termine).
  8. ``release`` con sesión ajena NO libera el slot de otro cliente
     (la LIMITACIÓN CONOCIDA del 2026-10-21).
  9. ``heartbeat`` con sesión ajena NO refresca la sesión de otro
     cliente.
 10. ``release`` es idempotente.
"""
from __future__ import annotations

import threading
import time

from app.services.cameras import live_streams as live_streams_mod
from app.services.cameras.live_streams import (
    STALE_AFTER_S,
    LiveStreamRegistry,
)


def test_try_acquire_reserva_y_rechaza_la_segunda() -> None:
    """La primera llamada gana la cámara; la segunda devuelve ``None``
    (el endpoint lo traduce a 409)."""
    registry = LiveStreamRegistry()
    primera = registry.try_acquire(1)
    segunda = registry.try_acquire(1)
    assert primera is not None
    assert segunda is None
    assert registry.active_count() == 1


def test_try_acquire_concurrente_solo_uno_gana() -> None:
    """Cinco ``try_acquire`` a la vez (en hilos) sobre la misma cámara:
    sólo uno consigue la sesión (determinismo, sin condiciones de
    carrera).

    Con la API síncrona el lock real es un ``threading.Lock``, así que la
    prueba de concurrencia es con hilos de verdad y no con corrutinas.
    """
    registry = LiveStreamRegistry()
    barrera = threading.Barrier(5)
    resultados: list[object] = [None] * 5

    def _intentar(indice: int) -> None:
        barrera.wait()
        resultados[indice] = registry.try_acquire(1)

    hilos = [threading.Thread(target=_intentar, args=(i,)) for i in range(5)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    ganados = sum(1 for r in resultados if r is not None)
    assert ganados == 1, f"esperaba 1 ganador, hubo {ganados}"
    assert registry.active_count() == 1


def test_heartbeat_actualiza_el_timestamp() -> None:
    """``heartbeat`` refresca ``last_heartbeat`` de la sesión viva."""
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    antes = session.last_heartbeat
    time.sleep(0.01)
    registry.heartbeat(1)
    assert session.last_heartbeat > antes


def test_heartbeat_de_camara_sin_sesion_no_rompe() -> None:
    """Un heartbeat tardío (la sesión ya se liberó) no debe fallar: el
    generador está cerrando y simplemente no hay a quién avisar."""
    registry = LiveStreamRegistry()
    registry.heartbeat(999)  # cámara sin sesión
    session = registry.try_acquire(1)
    assert session is not None
    registry.release(1)
    registry.heartbeat(1)  # la sesión ya no está


def test_sesion_huerfana_se_libera() -> None:
    """Una sesión sin heartbeat durante más de ``STALE_AFTER_S`` se
    considera huérfana: el siguiente ``try_acquire`` la barre, avisa a
    su generador con ``shutdown_event`` y libera el slot."""
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    # Envejecemos el heartbeat: equivale a > STALE_AFTER_S sin frames.
    session.last_heartbeat = time.monotonic() - STALE_AFTER_S - 1
    nueva = registry.try_acquire(1)
    assert nueva is not None, "la sesión huérfana no liberó el slot"
    assert session.shutdown_event.is_set(), "no se avisó al generador"
    assert registry.active_count() == 1


def test_sesion_huerfana_por_tiempo_real(monkeypatch) -> None:
    """Lo mismo pero con el reloj real: se acorta ``STALE_AFTER_S`` y se
    espera a que el umbral se supere sin tocar el timestamp a mano."""
    monkeypatch.setattr(live_streams_mod, "STALE_AFTER_S", 0.05)

    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    time.sleep(0.12)  # > STALE_AFTER_S sin heartbeats
    nueva = registry.try_acquire(1)
    assert nueva is not None
    assert session.shutdown_event.is_set()


def test_release_libera_el_slot_y_avisa_al_generador() -> None:
    """``release`` activa el ``shutdown_event`` (el generador termina) y
    deja la cámara libre para el siguiente cliente."""
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    liberado = registry.release(1)
    nueva = registry.try_acquire(1)
    assert session.shutdown_event.is_set(), "release no avisó al generador"
    assert liberado is True
    assert registry.active_count() == 1
    assert nueva is not None


def test_shutdown_all_no_vacia_el_registro() -> None:
    """``shutdown_all`` señala las sesiones pero NO las quita del
    registro.

    POR QUÉ: los generadores siguen vivos hasta que ven su
    ``shutdown_event``. Si al apagar quitásemos la sesión del dict, un
    cliente nuevo podría tomar la cámara y, cuando el generador viejo
    terminara, su ``finally`` llamaría a ``release(camera_id)`` y
    liberaría la sesión del cliente nuevo (matando su stream). Dejando
    la sesión en el dict, el slot sigue ocupado hasta que el propio
    generador lo libere.
    """
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    notified = registry.shutdown_all()
    assert notified == 1
    assert session.shutdown_event.is_set()
    assert registry.active_count() == 1, "shutdown_all no debe vaciar el registro"


# ── P2 del preview (2026-10-21): la sesión identifica al dueño ──────


def test_release_de_una_sesion_ajena_no_mata_al_cliente_nuevo() -> None:
    """El ``finally`` de un generador viejo NO puede liberar la sesión de
    un cliente que ya tomó la cámara.

    Escenario real: la sesión A se libera por otra vía (barrido de
    huérfanas o apagado), un cliente nuevo toma la cámara (sesión B) y
    sólo después el generador de A ejecuta su ``finally``. Con el
    ``release`` por ``camera_id`` a secas, ese ``finally`` liberaba la
    sesión de B y le mataba el stream en mitad.
    """
    registry = LiveStreamRegistry()
    sesion_a = registry.try_acquire(1)
    assert sesion_a is not None

    # La sesión A se libera por otra vía (barrido de huérfanas).
    assert registry.release(1) is True

    # Un cliente nuevo toma la cámara.
    sesion_b = registry.try_acquire(1)
    assert sesion_b is not None
    assert sesion_b is not sesion_a

    # El ``finally`` tardío del generador de A llega con su sesión.
    liberado = registry.release(1, sesion_a)

    assert liberado is False, "el release de una sesión ajena Liberó el slot"
    assert registry.active_count() == 1, "la sesión del cliente nuevo desapareció"
    assert sesion_b.shutdown_event.is_set() is False, (
        "se señalizó el shutdown_event de la sesión de otro cliente"
    )


def test_release_con_la_sesion_correcta_libera_el_slot() -> None:
    """El caso bueno del ``release`` por sesión: libera el slot y avisa
    al generador."""
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    liberado = registry.release(1, session)
    assert liberado is True
    assert session.shutdown_event.is_set()
    assert registry.active_count() == 0


def test_release_es_idempotente() -> None:
    """Liberar dos veces la misma sesión no peta ni libera nada más."""
    registry = LiveStreamRegistry()
    session = registry.try_acquire(1)
    assert session is not None
    assert registry.release(1, session) is True
    assert registry.release(1, session) is False
    assert registry.active_count() == 0


def test_heartbeat_de_una_sesion_ajena_no_refresca_al_cliente_nuevo() -> None:
    """Un heartbeat tardío del generador viejo no debe mantener viva la
    sesión del cliente nuevo (ni viceversa: no se pisan entre sí)."""
    registry = LiveStreamRegistry()
    sesion_a = registry.try_acquire(1)
    assert sesion_a is not None
    registry.release(1)
    sesion_b = registry.try_acquire(1)
    assert sesion_b is not None

    antes = sesion_b.last_heartbeat
    time.sleep(0.01)
    registry.heartbeat(1, sesion_a)  # heartbeat tardío del generador viejo
    assert sesion_b.last_heartbeat == antes, (
        "el heartbeat de una sesión ajena refrescó la sesión del cliente nuevo"
    )

    registry.heartbeat(1, sesion_b)  # el heartbeat del propio cliente sí cuenta
    assert sesion_b.last_heartbeat > antes
