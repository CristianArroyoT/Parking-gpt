"""Regresión del P2 del preview (2026-10-21): el slot de la cámara.

Síntoma que se arregla aquí: un operador cerraba el modal de
previsualización y, al volver a abrirlo, recibía un **409** durante
hasta ~8 s.

Causa (tres cosas encadenadas):

1. **Orden**: el slot de la cámara se liberaba en el ``finally`` del
   generador **externo** (``safe_gen`` en ``cameras_live.py``), pero el
   ``finally`` del generador **interno** (``mjpeg_generator``) — que es
   el que cierra el ``VideoCapture`` — se ejecuta ANTES. El teardown
   del RTSP puede tardar (espera a la lectura en vuelo), así que el
   slot seguía ocupado durante todo ese tiempo.

2. **Finalización diferida**: cuando el cliente aborta la petición —el
   navegador cerrando el modal— Starlette cancela la tarea del stream.
   El generador asíncrono no se cierra en ese momento: lo cierra el
   finalizador de generadores asíncronos del event loop, que puede
   tardar hasta que el recolector de basura recoge el ciclo de
   referencias. La liberación del slot era, por tanto,
   **indeterminista**.

3. **Bloqueo del event loop**: el ``cap.release()`` se hacía en el hilo
   del event loop y ``CapturaSincronizada.release()`` espera a que
   termine la lectura en vuelo (hasta el timeout de FFmpeg: 5 s). Con
   el backend entero congelado durante ese tiempo.

Lo que se verifica aquí:

  1. El slot se libera **antes** de que termine la limpieza de la
     captura (con el teardown bloqueado a propósito).
  2. La limpieza de la captura **no bloquea** el event loop.
  3. El slot se libera también cuando el stream se cierra **por
     cancelación** (el caso real: el navegador aborta la petición).
  4. A nivel de endpoint: un cliente que reabre la cámara **no**
     recibe 409 aunque el teardown del cliente anterior siga en curso.

DISEÑO DEL FICHERO: todo pasa por la **capa HTTP** y por
``live_streams.active_count()`` (síncrono en el código viejo y en el
nuevo). Así el mismo fichero se puede ejecutar contra las dos
versiones del código y comparar el antes/después del arreglo.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import cameras_live
from app.models.parking import Camera
from app.services.cameras import stream as stream_mod
from tests._audit_helpers import (
    _login,
    _seed_admin,
    _seed_parking,
)


class _CapConReleaseLento:
    """``VideoCapture`` falso cuyo ``release()`` se queda bloqueado.

    Reproduce el peor caso real: el teardown del RTSP espera a la
    lectura en vuelo. El bloqueo se hace con un ``threading.Event``
    porque ``release()`` puede ejecutarse en un hilo del pool.

    ``eventos`` es un registro compartido con el callback de fin de
    sesión: sirve para comprobar el **orden** (el slot se suelta antes
    de que empiece el teardown).
    """

    def __init__(self, eventos: list[str], espera_s: float = 0.0) -> None:
        self.eventos = eventos
        self.espera_s = espera_s
        self.teardown_iniciado = threading.Event()
        self.desbloquear = threading.Event()
        self.liberado = False

    def isOpened(self) -> bool:  # noqa: N802 — imita la API de OpenCV
        return True

    def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def grab(self) -> bool:
        return False  # RTSP caído: el generador emite placeholder

    def retrieve(self) -> tuple[bool, Any]:
        return False, None

    def release(self) -> None:
        self.eventos.append("teardown_iniciado")
        self.teardown_iniciado.set()
        try:
            if self.espera_s:
                time.sleep(self.espera_s)
            self.desbloquear.wait(timeout=15)
        finally:
            self.liberado = True
            self.eventos.append("teardown_fin")


class _Camara:
    """Lo mínimo que el generador necesita de un Camera."""

    id = 81
    rtsp_url = "rtsp://ejemplo.invalid/cam"


class _DesconectadoTrasUnaLectura:
    """``is_disconnected`` que devuelve ``False`` la primera vez.

    Así el generador emite un frame y sólo en la iteración siguiente
    se da por desconectado (que es lo que hace el navegador: el socket
    se cierra después de haber recibido algo).
    """

    def __init__(self) -> None:
        self.llamadas = 0

    async def __call__(self) -> bool:
        self.llamadas += 1
        return self.llamadas > 1


async def _nunca_desconectado() -> bool:
    return False


@pytest.fixture(autouse=True)
def _limpiar_registro():
    """Vacía el registro de streams antes y después de cada test."""
    cameras_live.live_streams._active.clear()  # noqa: SLF001
    yield
    cameras_live.live_streams._active.clear()  # noqa: SLF001


def test_el_slot_se_libera_antes_de_la_limpieza_de_la_captura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El slot de la cámara queda libre ANTES de que el teardown del
    RTSP termine.

    Antes del arreglo, el ``release`` del registro estaba en el
    ``finally`` del generador externo, que corre después del teardown:
    el slot quedaba ocupado todo ese tiempo (409 para quien quisiera
    reabrir).
    """
    eventos: list[str] = []
    cap = _CapConReleaseLento(eventos)
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    def _on_session_end() -> None:
        eventos.append("slot_liberado")
        _soltar_slot_del_registro()

    async def _escenario() -> None:
        generador = stream_mod.mjpeg_generator(
            _Camara(),
            asyncio.Event(),
            _DesconectadoTrasUnaLectura(),
            frame_interval_s=0.0,
            on_session_end=_on_session_end,
        )
        # 1ª iteración: emite un frame. 2ª: detecta la desconexión y
        # entra en el ``finally``.
        await generador.__anext__()
        with pytest.raises(StopAsyncIteration):
            await generador.__anext__()

    async def _main() -> None:
        tarea = asyncio.create_task(_escenario())
        # El teardown empieza y se queda bloqueado.
        for _ in range(500):
            if cap.teardown_iniciado.is_set():
                break
            await asyncio.sleep(0.01)
        assert cap.teardown_iniciado.is_set(), "el teardown no llegó a empezar"
        assert cap.liberado is False, "el teardown ya había terminado"

        # Mientras el teardown sigue en curso, el slot ya está libre.
        assert cameras_live.live_streams.active_count() == 0, (
            "el slot seguía ocupado mientras la captura se cerraba: "
            "un cliente que reabriera la cámara recibiría 409"
        )
        assert eventos == ["slot_liberado", "teardown_iniciado"], (
            f"el slot se liberó después del teardown: {eventos}"
        )

        cap.desbloquear.set()
        await asyncio.wait_for(tarea, timeout=10)

    asyncio.run(_main())
    assert cap.liberado is True


def _soltar_slot_del_registro() -> None:
    """Suelta el slot de la cámara 81 en el registro de streams.

    Es compatible con las dos versiones del registro: en el código
    viejo ``release`` era ``async`` (aquí se agenda la corrutina) y en
    el nuevo es síncrona (se llama directamente).
    """
    resultado = cameras_live.live_streams.release(81)
    if asyncio.iscoroutine(resultado):
        try:
            asyncio.get_running_loop().create_task(resultado)
        except RuntimeError:  # pragma: no cover — sin loop activo
            resultado.close()


def test_la_limpieza_de_la_captura_no_bloquea_el_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El ``cap.release()`` va fuera del hilo del event loop.

    Con el teardown en el hilo del loop, **todo** el backend quedaba
    congelado mientras esperaba a la lectura en vuelo (hasta 5 s con el
    timeout de FFmpeg): no sólo ese stream, sino cada request.
    """
    eventos: list[str] = []
    cap = _CapConReleaseLento(eventos, espera_s=1.0)
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    ticks = 0

    async def _contar() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    async def _escenario() -> int:
        generador = stream_mod.mjpeg_generator(
            _Camara(),
            asyncio.Event(),
            _DesconectadoTrasUnaLectura(),
            frame_interval_s=0.0,
        )
        await generador.__anext__()
        contador = asyncio.create_task(_contar())
        try:
            with pytest.raises(StopAsyncIteration):
                await generador.__anext__()
        finally:
            contador.cancel()
        return ticks

    ticks = asyncio.run(_escenario())
    # Con el release en el hilo del loop, el contador se quedaba en
    # ~1 tick (1 s congelado). Con el release en un hilo, el loop sigue
    # vivo: en 1 s caben ~100 ticks de 10 ms.
    assert ticks >= 20, (
        f"el event loop se quedó congelado durante el teardown "
        f"(sólo {ticks} ticks en 1 s)"
    )


def test_el_slot_se_libera_aunque_el_stream_se_cancele(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso real: el navegador aborta la petición y Starlette cancela
    la tarea del stream.

    La liberación del slot tiene que ocurrir **aun así**: si dependiera
    de un ``await``, la cancelación podría cortarla y el slot se
    quedaría ocupado hasta el barrido de huérfanas (8 s de 409).
    """
    eventos: list[str] = []
    cap = _CapConReleaseLento(eventos)
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    def _on_session_end() -> None:
        eventos.append("slot_liberado")
        _soltar_slot_del_registro()

    async def _escenario() -> None:
        generador = stream_mod.mjpeg_generator(
            _Camara(),
            asyncio.Event(),
            _nunca_desconectado,
            frame_interval_s=0.0,
            on_session_end=_on_session_end,
        )
        await generador.__anext__()
        # Se cancela la tarea que está esperando el siguiente frame.
        tarea = asyncio.create_task(generador.__anext__())
        await asyncio.sleep(0.05)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(_escenario())
    assert cameras_live.live_streams.active_count() == 0, (
        "la cancelación dejó el slot ocupado: el siguiente cliente "
        "recibiría 409 hasta el barrido de huérfanas"
    )
    assert eventos[0] == "slot_liberado", (
        f"el slot no se liberó al principio: {eventos}"
    )
    cap.desbloquear.set()


def test_reabrir_la_camara_no_devuelve_409_aunque_el_teardown_siga(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nivel de endpoint: cerrar y reabrir el preview no da 409.

    Es la prueba del síntoma que ve el operador. El teardown del
    cliente anterior se deja bloqueado a propósito: si el slot no se
    liberase antes, el segundo cliente recibiría 409.
    """
    eventos: list[str] = []
    cap = _CapConReleaseLento(eventos)
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-LIVE-P2")
    cam = Camera(
        parking_id=parking.id, code="CAM-LIVE-P2",
        name="Cámara P2", rtsp_url="rtsp://demo.invalid/x", fps=10,
    )
    db_session.add(cam)
    db_session.commit()
    db_session.refresh(cam)

    token = _login(client, admin.email, "admin12345")

    async def _escenario() -> tuple[bool, bool]:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            url = f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/live"
            headers = {"Authorization": f"Bearer {token}"}

            # 1) Primer cliente: abre el stream y se queda con la cámara.
            primero = asyncio.create_task(ac.get(url, headers=headers))
            for _ in range(300):
                if cameras_live.live_streams.active_count() == 1:
                    break
                await asyncio.sleep(0.01)
            assert cameras_live.live_streams.active_count() == 1, (
                "el primer cliente no tomó la cámara"
            )

            # 2) Cierra el modal: se cancela la petición en vuelo. El
            #    teardown se queda bloqueado a propósito.
            primero.cancel()
            with pytest.raises(asyncio.CancelledError):
                await primero
            for _ in range(300):
                if cameras_live.live_streams.active_count() == 0:
                    break
                await asyncio.sleep(0.01)
            assert cameras_live.live_streams.active_count() == 0, (
                "el slot siguió ocupado tras cancelar la petición: "
                "la liberación del slot no es determinista"
            )

            # 3) Segundo cliente: debe poder tomar la cámara aunque el
            #    teardown del primero siga en curso. Tras la liberación
            #    del primero el contador está a 0, así que que suba a 1
            #    significa que el segundo cliente ha tomado el slot (si
            #    hubiera recibido un 409, seguiría a 0).
            segundo = asyncio.create_task(ac.get(url, headers=headers))
            for _ in range(300):
                if cameras_live.live_streams.active_count() >= 1:
                    break
                await asyncio.sleep(0.01)
            tomo_el_slot = cameras_live.live_streams.active_count() >= 1
            # Si el segundo cliente hubiera recibido un 409, su task
            # habría terminado; con 200 sigue abierto esperando frames.
            sigue_vivo = not segundo.done()
            segundo.cancel()
            with pytest.raises(asyncio.CancelledError):
                await segundo
            cap.desbloquear.set()
            return tomo_el_slot, sigue_vivo

    tomo_el_slot, sigue_vivo = asyncio.run(_escenario())
    assert tomo_el_slot is True, (
        "el segundo cliente no pudo tomar la cámara: el slot seguía "
        "ocupado por el teardown del primero (409)"
    )
    assert sigue_vivo is True, (
        "el segundo cliente recibió un 409 en vez de un stream"
    )
