"""Tests de la cámara sin URL de RTSP.

POR QUÉ (2026-10-21): una cámara con ``rtsp_url`` vacía hace que
OpenCV reviente con una **aserción de C++** ("!_filename.empty()") cada
vez que se abre: en el sondeo del heartbeat, en el preview y en la
captura de un frame. El alta ya lo impedía (``min_length=8``), pero el
PATCH no: ``CameraUpdate.rtsp_url`` no tenía ninguna restricción, así
que un ``PATCH {"rtsp_url": ""}`` dejaba la cámara sin URL.

Aquí se comprueban las dos caras:

  1. El esquema: el PATCH ya no acepta una URL vacía (ni una demasiado
     corta).
  2. Los servicios: con la URL vacía **no se llama a OpenCV** y se
     devuelve el fallo de forma limpia, sin aserción de C++.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.parking import CameraCreate, CameraUpdate
from app.services.cameras import capture as capture_mod
from app.services.cameras import heartbeat as heartbeat_mod
from app.services.cameras import stream as stream_mod


def test_el_alta_ya_rechazaba_una_url_vacia() -> None:
    with pytest.raises(ValidationError):
        CameraCreate(code="CAM-X", name="Cámara", rtsp_url="")


def test_el_patch_rechaza_una_url_vacia() -> None:
    """Éste era el agujero: el alta lo impedía, el PATCH no."""
    with pytest.raises(ValidationError):
        CameraUpdate(rtsp_url="")


def test_el_patch_rechaza_una_url_demasiado_corta() -> None:
    with pytest.raises(ValidationError):
        CameraUpdate(rtsp_url="rtsp://")


def test_el_patch_sigue_aceptando_una_url_valida() -> None:
    cambios = CameraUpdate(rtsp_url="rtsp://ejemplo.invalid/cam")
    assert cambios.rtsp_url == "rtsp://ejemplo.invalid/cam"


def test_el_patch_sigue_aceptando_no_tocar_la_url() -> None:
    cambios = CameraUpdate(name="Otro nombre")
    assert cambios.rtsp_url is None


def test_el_preview_no_abre_una_captura_sin_url() -> None:
    """Sin URL no se llama a OpenCV (que es quien lanza la aserción)."""
    cap = stream_mod._open_capture("")  # noqa: SLF001 — interno a propósito
    assert cap is not None
    assert cap.isOpened() is False


def test_el_heartbeat_devuelve_false_sin_url() -> None:
    assert heartbeat_mod._probe_sync("") is False  # noqa: SLF001


def test_la_captura_devuelve_none_sin_url() -> None:
    assert capture_mod._read_one_frame_sync("") is None  # noqa: SLF001
