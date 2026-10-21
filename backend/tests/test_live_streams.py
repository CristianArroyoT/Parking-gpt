"""Tests del registro de streams vivos (``LiveStreamRegistry``).

Cubre el T-10 del plan maestro: blindar el registro para que dos
clientes simultáneos sobre la misma cámara se comporten de forma
determinista (uno recibe el video, el otro un 409) y las sesiones
huérfanas se liberen solas.

Casos cubiertos:
  1. ``try_acquire`` reserva la cámara; la segunda llamada la rechaza.
  2. ``try_acquire`` concurrente (5 a la vez): sólo uno gana.
  3. ``heartbeat`` actualiza el timestamp de la sesión.
  4. ``heartbeat`` de una cámara sin sesión no rompe nada.
  5. Sesión huérfana (> ``STALE_AFTER_S`` sin heartbeat) → se libera.
  6. ``release`` avisa al generador (``shutdown_event``) y libera el slot.
  7. ``shutdown_all`` señala todas las sesiones vivas SIN vaciar el
     registro (decisión de diseño: el slot sigue ocupado hasta que el
     generador termine).
"""
from __future__ import annotations

import asyncio
import time

from app.services.cameras import live_streams as live_streams_mod
from app.services.cameras.live_streams import (
    STALE_AFTER_S,
    LiveStreamRegistry,
)


def test_try_acquire_reserva_y_rechaza_la_segunda() -> None:
    """La primera llamada gana la cámara; la segunda devuelve ``None``
    (el endpoint lo traduce a 409)."""
    async def _escenario() -> tuple[bool, bool, int]:
        registry = LiveStreamRegistry()
        primera = await registry.try_acquire(1)
        segunda = await registry.try_acquire(1)
        return (
            primera is not None,
            segunda is None,
            registry.active_count(),
        )

    primera_ok, segunda_none, activos = asyncio.run(_escenario())
    assert primera_ok is True
    assert segunda_none is True
    assert activos == 1


def test_try_acquire_concurrente_solo_uno_gana() -> None:
    """Cinco ``try_acquire`` a la vez sobre la misma cámara: sólo uno
    consigue la sesión (determinismo, sin condiciones de carrera)."""
    async def _escenario() -> tuple[int, int]:
        registry = LiveStreamRegistry()
        resultados = await asyncio.gather(
            *(registry.try_acquire(1) for _ in range(5)),
        )
        ganados = sum(1 for r in resultados if r is not None)
        return ganados, registry.active_count()

    ganados, activos = asyncio.run(_escenario())
    assert ganados == 1, f"esperaba 1 ganador, hubo {ganados}"
    assert activos == 1


def test_heartbeat_actualiza_el_timestamp() -> None:
    """``heartbeat`` refresca ``last_heartbeat`` de la sesión viva."""
    async def _escenario() -> tuple[float, float]:
        registry = LiveStreamRegistry()
        session = await registry.try_acquire(1)
        assert session is not None
        antes = session.last_heartbeat
        await asyncio.sleep(0.01)
        await registry.heartbeat(1)
        return antes, session.last_heartbeat

    antes, despues = asyncio.run(_escenario())
    assert despues > antes


def test_heartbeat_de_camara_sin_sesion_no_rompe() -> None:
    """Un heartbeat tardío (la sesión ya se liberó) no debe fallar: el
    generador está cerrando y simplemente no hay a quién avisar."""
    async def _escenario() -> None:
        registry = LiveStreamRegistry()
        await registry.heartbeat(999)  # cámara sin sesión
        session = await registry.try_acquire(1)
        assert session is not None
        await registry.release(1)
        await registry.heartbeat(1)  # la sesión ya no está

    asyncio.run(_escenario())


def test_sesion_huerfana_se_libera() -> None:
    """Una sesión sin heartbeat durante más de ``STALE_AFTER_S`` se
    considera huérfana: el siguiente ``try_acquire`` la barre, avisa a
    su generador con ``shutdown_event`` y libera el slot."""
    async def _escenario() -> tuple[bool, bool, int]:
        registry = LiveStreamRegistry()
        session = await registry.try_acquire(1)
        assert session is not None
        # Envejecemos el heartbeat: equivale a > STALE_AFTER_S sin frames.
        session.last_heartbeat = time.monotonic() - STALE_AFTER_S - 1
        nueva = await registry.try_acquire(1)
        return (
            nueva is not None,
            session.shutdown_event.is_set(),
            registry.active_count(),
        )

    liberada, avisada, activos = asyncio.run(_escenario())
    assert liberada is True, "la sesión huérfana no liberó el slot"
    assert avisada is True, "no se avisó al generador de la sesión huérfana"
    assert activos == 1


def test_sesion_huerfana_por_tiempo_real(monkeypatch) -> None:
    """Lo mismo pero con el reloj real: se acorta ``STALE_AFTER_S`` y se
    espera a que el umbral se supere sin tocar el timestamp a mano."""
    monkeypatch.setattr(live_streams_mod, "STALE_AFTER_S", 0.05)

    async def _escenario() -> tuple[bool, bool]:
        registry = LiveStreamRegistry()
        session = await registry.try_acquire(1)
        assert session is not None
        await asyncio.sleep(0.12)  # > STALE_AFTER_S sin heartbeats
        nueva = await registry.try_acquire(1)
        return nueva is not None, session.shutdown_event.is_set()

    liberada, avisada = asyncio.run(_escenario())
    assert liberada is True
    assert avisada is True


def test_release_libera_el_slot_y_avisa_al_generador() -> None:
    """``release`` activa el ``shutdown_event`` (el generador termina) y
    deja la cámara libre para el siguiente cliente."""
    async def _escenario() -> tuple[bool, int, bool]:
        registry = LiveStreamRegistry()
        session = await registry.try_acquire(1)
        assert session is not None
        await registry.release(1)
        nueva = await registry.try_acquire(1)
        return (
            session.shutdown_event.is_set(),
            registry.active_count(),
            nueva is not None,
        )

    avisada, activos, reutilizable = asyncio.run(_escenario())
    assert avisada is True, "release no avisó al generador"
    assert activos == 1
    assert reutilizable is True


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
    async def _escenario() -> tuple[int, int, bool]:
        registry = LiveStreamRegistry()
        session = await registry.try_acquire(1)
        assert session is not None
        notified = await registry.shutdown_all()
        return notified, registry.active_count(), session.shutdown_event.is_set()

    notified, activos, avisada = asyncio.run(_escenario())
    assert notified == 1
    assert avisada is True
    assert activos == 1, "shutdown_all no debe vaciar el registro"
