"""Tests del módulo de captura RTSP (app.services.cameras.capture).

Estrategia: como `cv2.VideoCapture` no es fácil de mockear y depende
de FFmpeg/libav, los tests cubren el camino de fallo (URL inválida) y
la forma async de la función, sin necesitar un stream RTSP real. El
camino feliz requiere cámara real (o RTSP de prueba) y se valida con
un ping_camera manual contra una URL válida — fuera del alcance pytest.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.cameras.capture import grab_frame


def _run(coro):
    """Helper: ejecuta una corutina desde test sync (sin pytest-asyncio)."""
    return asyncio.run(coro)


def test_grab_frame_returns_none_for_invalid_rtsp_url() -> None:
    """URL inválida (DNS inexistente) -> None, nunca propaga excepción."""

    class FakeCamera(SimpleNamespace):
        pass

    cam = FakeCamera(rtsp_url="rtsp://demo.invalid/missing/stream")
    # No debe lanzar excepción; debe devolver None tras timeout interno.
    result = _run(grab_frame(cam, timeout_s=2.0))
    assert result is None


def test_grab_frame_returns_none_for_malformed_url() -> None:
    """URL malformada -> None, nunca propaga excepción."""

    class FakeCamera(SimpleNamespace):
        pass

    cam = FakeCamera(rtsp_url="not-even-a-url")
    result = _run(grab_frame(cam, timeout_s=2.0))
    assert result is None


def test_grab_frame_returns_none_for_empty_url() -> None:
    """URL vacía -> None (caso borde: cámaras sin RTSP configurado)."""

    class FakeCamera(SimpleNamespace):
        pass

    cam = FakeCamera(rtsp_url="")
    result = _run(grab_frame(cam, timeout_s=2.0))
    assert result is None


def test_grab_frame_is_coroutine() -> None:
    """Verifica la firma: grab_frame devuelve un awaitable."""

    class FakeCamera(SimpleNamespace):
        pass

    cam = FakeCamera(rtsp_url="rtsp://demo.invalid/x")
    coro = grab_frame(cam, timeout_s=1.0)
    # asyncio.iscoroutine distingue corutinas de returns directos.
    assert asyncio.iscoroutine(coro)
    # Cerramos la corutina sin await explícito (descarta resultado).
    coro.close()