"""Tests del limitador de fps del preview en vivo (plan maestro T-07).

Contexto: los docstrings de ``cameras_live.py`` y ``stream.py`` anunciaban
"5 fps (cada 200 ms)" pero la constante real era ``FRAME_INTERVAL_S = 0.0``
(sprint Latencia-Mínima 2026-07-07) → el preview iba a 35 fps medidos.
Decisión D1 (2026-10-21): **5 fps por defecto**, configurable por variable
de entorno ``LIVE_PREVIEW_FPS``; con 0 (o negativo) = sin limitador, al
ritmo de la cámara.

Estos tests NO comprueban sólo el valor de una constante: comprueban que
el limitador **existe y funciona**, que el tiempo de espera se calcula
sobre el tiempo real transcurrido (no un ``sleep`` ciego que añada
latencia) y que el modo "sin limitador" sigue disponible.

Para que sean rápidos y deterministas NO se abre ningún RTSP: se sustituye
``stream._open_capture`` por un doble que devuelve frames al instante (o
con un retardo simulado, para el caso "la cámara va más lenta que el
intervalo objetivo").
"""
from __future__ import annotations

import asyncio
import contextlib
import time

import numpy as np
import pytest

from app.api.v1 import cameras_live
from app.core.config import get_settings
from app.models.parking import Camera
from app.services.cameras import stream


def _camara() -> Camera:
    """Cámara sin persistir: el generador sólo usa ``id`` y ``rtsp_url``."""
    return Camera(
        parking_id=1,
        code="CAM-FPS",
        name="Cámara limitador fps",
        rtsp_url="rtsp://fake.invalid/1",
    )


class _CapturaFalsa:
    """Doble de ``cv2.VideoCapture``: nunca toca la red.

    ``grab()`` devuelve ``True`` siempre y ``retrieve()`` un frame negro
    minúsculo (válido para ``cv2.imencode``). ``delay_s`` simula una
    cámara lenta: el ``grab`` tarda ese tiempo.
    """

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.released = False

    def isOpened(self) -> bool:
        return True

    def grab(self) -> bool:
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        return True

    def retrieve(self) -> tuple[bool, np.ndarray]:
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True


async def _nunca_desconectado() -> bool:
    """El cliente sigue conectado para siempre."""
    return False


def _desconectar_tras(max_frames: int):
    """Callable async que empieza a devolver ``True`` tras ``max_frames``.

    El generador comprueba la desconexión UNA vez por vuelta del bucle,
    justo antes de leer el frame, así que con ``max_frames=4`` se emiten
    4 frames y la 5ª comprobación corta el stream.
    """
    estado = {"vistos": 0}

    async def _is_disconnected() -> bool:
        estado["vistos"] += 1
        return estado["vistos"] > max_frames

    return _is_disconnected


async def _contar_en_ventana(
    camara: Camera, intervalo_s: float | None, segundos: float,
) -> int:
    """Consume el generador durante ``segundos`` y devuelve nº de frames."""
    generador = stream.mjpeg_generator(
        camara,
        asyncio.Event(),
        _nunca_desconectado,
        frame_interval_s=intervalo_s,
    )
    cuenta = 0
    limite = time.monotonic() + segundos
    async with contextlib.aclosing(generador):
        async for _ in generador:
            cuenta += 1
            if time.monotonic() >= limite:
                break
    return cuenta


async def _contar_hasta_desconexion(
    camara: Camera, intervalo_s: float | None, max_frames: int,
) -> tuple[int, float]:
    """Emite hasta ``max_frames`` frames. Devuelve (frames, segundos)."""
    generador = stream.mjpeg_generator(
        camara,
        asyncio.Event(),
        _desconectar_tras(max_frames),
        frame_interval_s=intervalo_s,
    )
    cuenta = 0
    inicio = time.monotonic()
    async with contextlib.aclosing(generador):
        async for _ in generador:
            cuenta += 1
    return cuenta, time.monotonic() - inicio


# ───────────────────────────── config ─────────────────────────────


def test_el_default_es_5_fps_con_un_intervalo_de_200_ms() -> None:
    """El default anunciado (5 fps / 200 ms) coincide con la config real."""
    fps_config = get_settings().live_preview_fps
    fps_default = stream.DEFAULT_PREVIEW_FPS
    intervalo = stream.FRAME_INTERVAL_S
    intervalo_config = stream.resolve_frame_interval_s()

    assert fps_config == 5.0
    assert fps_default == 5.0
    assert intervalo == pytest.approx(0.2)
    assert intervalo_config == pytest.approx(0.2)


def test_la_variable_de_entorno_cambia_el_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LIVE_PREVIEW_FPS`` es el interruptor: 12 → intervalo 1/12 s."""
    monkeypatch.setenv("LIVE_PREVIEW_FPS", "12")
    get_settings.cache_clear()
    try:
        assert get_settings().live_preview_fps == 12.0
        assert stream.resolve_frame_interval_s() == pytest.approx(1 / 12)
    finally:
        get_settings.cache_clear()


def test_fps_no_positivo_significa_sin_limitador(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LIVE_PREVIEW_FPS=0`` → intervalo 0 = flujo libre (cámara)."""
    monkeypatch.setenv("LIVE_PREVIEW_FPS", "0")
    get_settings.cache_clear()
    try:
        assert stream.resolve_frame_interval_s() == 0.0
    finally:
        get_settings.cache_clear()
    # Y también con un valor negativo (interpretado igual que 0).
    assert stream.resolve_frame_interval_s(-1.0) == 0.0


# ─────────────────────── limitador real ───────────────────────


def test_el_generador_no_emite_mas_frames_que_el_fps_marca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El limitador es REAL: a 10 fps no se pueden ver 10 frames/s.

    Ventana de 0,5 s con intervalo de 0,1 s → como mucho 5-6 frames.
    Sin limitador (fps=0) en la MISMA ventana salen muchísimos más: ése
    es justo el ahorro de CPU/ancho de banda que motiva la decisión D1.
    """
    monkeypatch.setattr(stream, "_open_capture", lambda _url: _CapturaFalsa())

    con_limite = asyncio.run(_contar_en_ventana(_camara(), 0.1, 0.5))
    sin_limite = asyncio.run(_contar_en_ventana(_camara(), 0.0, 0.5))

    assert con_limite >= 1, "el generador no emitió nada"
    assert con_limite <= 7, f"se emitieron {con_limite} frames en 0,5 s a 10 fps"
    assert sin_limite >= 20, f"sin limitador sólo salieron {sin_limite} frames"
    assert sin_limite > con_limite * 3


def test_el_generador_toma_el_fps_de_la_configuracion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin ``frame_interval_s`` explícito, manda ``LIVE_PREVIEW_FPS``."""
    monkeypatch.setattr(stream, "_open_capture", lambda _url: _CapturaFalsa())
    monkeypatch.setenv("LIVE_PREVIEW_FPS", "10")
    get_settings.cache_clear()
    try:
        frames = asyncio.run(_contar_en_ventana(_camara(), None, 0.5))
    finally:
        get_settings.cache_clear()

    assert 1 <= frames <= 7, f"se emitieron {frames} frames en 0,5 s con LIVE_PREVIEW_FPS=10"


def test_la_espera_se_calcula_sobre_el_tiempo_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La espera NO es un ``sleep(intervalo)`` ciego.

    Con una captura que ya tarda 0,12 s (más que el intervalo de 0,1 s) el
    generador no debe añadir latencia: 4 frames ≈ 0,5 s. Con un sleep
    ciego serían 4 × (0,12 + 0,1) ≈ 0,88 s.
    """
    monkeypatch.setattr(
        stream, "_open_capture", lambda _url: _CapturaFalsa(delay_s=0.12),
    )

    frames, segundos = asyncio.run(_contar_hasta_desconexion(_camara(), 0.1, 4))

    assert frames == 4
    assert segundos >= 0.4, f"los frames no tardaron lo esperado: {segundos:.2f}s"
    assert segundos < 0.75, (
        f"el limitador ha añadido latencia innecesaria: {segundos:.2f}s "
        f"(un sleep ciego habría dado ~0,88s)"
    )


def test_con_fps_cero_el_generador_no_espera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fps=0 → sin limitador: el generador no duerme entre frames."""
    monkeypatch.setattr(stream, "_open_capture", lambda _url: _CapturaFalsa())

    frames, segundos = asyncio.run(_contar_hasta_desconexion(_camara(), 0.0, 20))

    assert frames == 20
    assert segundos < 1.0, f"20 frames sin limitador tardaron {segundos:.2f}s"


# ─────────────────────── docstrings coherentes ───────────────────────


def test_el_docstring_del_endpoint_anuncia_el_fps_real() -> None:
    """El endpoint dice 5 fps y el default REAL también es 5 fps.

    Este test es el que blinda la contradicción que corregía T-07: si
    alguien cambia el default o el docstring sin tocar el otro, falla.
    """
    doc = cameras_live.__doc__ or ""
    assert "5 fps" in doc
    assert get_settings().live_preview_fps == 5.0


def test_el_docstring_del_generador_explica_el_modo_sin_limitador() -> None:
    """El modo "flujo libre" (sprint Latencia-Mínima) queda documentado."""
    doc = stream.__doc__ or ""
    assert "5 fps" in doc
    assert "sin limitador" in doc
    assert "LIVE_PREVIEW_FPS" in doc
