"""Regresión del SIGSEGV al cerrar el preview (T-13+1).

Bug P0 encontrado por la prueba de carga del 2026-10-21: **cerrar el
modal de previsualización tumba el backend**. Reproducción: 4 de 4.

Causa: las lecturas se ejecutan con ``asyncio.to_thread`` (hilo del pool).
Si el cliente cierra el stream mientras ese hilo sigue dentro de
``cap.grab()``, el ``finally`` del generador llama a ``cap.release()`` en
paralelo con la lectura en vuelo. OpenCV/FFmpeg libera las estructuras
internas del decoder mientras otro hilo las está usando y el proceso
aborta con **SIGSEGV (exit 139)**.

En QA el ``--reload`` lo disimula (el proceso revierte y parece una
"recarga"), pero en producción el backend entero cae cada vez que un
operador cierra el modal.

Estos tests comprueban el invariante: ``release()`` **nunca** se llama
con una lectura en curso. Con el código anterior (sin lock) fallan.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
import pytest

from app.services.cameras import stream as stream_mod


class _CapFalso:
    """VideoCapture falso que registra la condición de carrera."""

    def __init__(self) -> None:
        self.en_vuelo = False
        self.violaciones: list[str] = []

    # -- API de cv2.VideoCapture que usa el generador ------------------
    def isOpened(self) -> bool:  # noqa: N802 — imita la API de OpenCV
        return True

    def grab(self) -> bool:
        self.en_vuelo = True
        # Lectura lenta a propósito: abre la ventana en la que el
        # generador puede cerrarse con la lectura en vuelo.
        time.sleep(0.25)
        self.en_vuelo = False
        return True

    def retrieve(self):
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        if self.en_vuelo:
            self.violaciones.append("release() con grab() en vuelo")

    # -- API de cv2.VideoCapture que usa _open_capture -------------------
    def set(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


class _Camara:
    """Lo mínimo que el generador necesita de un Camera."""

    id = 81
    rtsp_url = "rtsp://ejemplo.invalid/cam"


async def _nunca_desconectado() -> bool:
    return False


def test_release_no_ocurre_con_una_lectura_en_vuelo(monkeypatch) -> None:
    """Cerrar el generador con un ``grab()`` en vuelo no debe liberar el capture."""
    cap = _CapFalso()
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    async def _escenario() -> list[str]:
        gen = stream_mod.mjpeg_generator(
            _Camara(), asyncio.Event(), _nunca_desconectado, frame_interval_s=0.0,
        )
        # Primera vuelta: el generador emite su primer frame.
        await gen.__anext__()
        # Segunda vuelta: entra en otro grab() (0,25 s) y se cancela
        # mientras la lectura está en vuelo (el cliente cerró el modal).
        tarea = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        return cap.violaciones

    violaciones = asyncio.run(_escenario())
    assert not violaciones, (
        "el capture se liberó con una lectura en vuelo: OpenCV abortaría "
        f"el proceso con SIGSEGV (violaciones: {violaciones})"
    )


def test_el_preview_sigue_emitiendo_frames(monkeypatch) -> None:
    """El wrap con lock no rompe la emisión normal de frames."""
    cap = _CapFalso()
    monkeypatch.setattr(stream_mod, "_open_capture", lambda url: cap)

    async def _escenario() -> list[bytes]:
        gen = stream_mod.mjpeg_generator(
            _Camara(), asyncio.Event(), _nunca_desconectado, frame_interval_s=0.0,
        )
        frames = []
        for _ in range(3):
            frames.append(await gen.__anext__())
        await gen.aclose()
        return frames

    frames = asyncio.run(_escenario())
    assert len(frames) == 3
    for frame in frames:
        assert frame.startswith(b"--frame\r\n")
        assert b"Content-Type: image/jpeg" in frame
    assert not cap.violaciones
