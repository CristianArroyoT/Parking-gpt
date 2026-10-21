"""Regresión del orden de canales BGR→RGB en la inferencia (T-09).

El servicio entregaba a Ultralytics la imagen **invertida** a RGB
(``cv2.cvtColor(img, cv2.COLOR_BGR2RGB)``). Ultralytics asume BGR en
los arrays numpy y la invierte internamente, así que el modelo recibía
los colores al revés y devolvía **0 detecciones** sobre fotos reales con
coches (2 'car' + 1 'bus' con conf 0.27/0.13/0.07 en BGR → 0 en RGB).

Como ``/detect`` responde 200 con ``[]`` ante cualquier problema, el
síntoma en la app era indistinguible de "la plaza está vacía".

Estos tests fijan el contrato: el array que llega a ``engine.predict``
debe tener **exactamente el mismo orden de canales** que la imagen
original.

Nota sobre OpenCV: los arrays numpy que se pasan a ``cv2.imencode`` /
``cv2.imdecode`` van en orden **BGR**. Por eso el cuadrado rojo se
escribe como ``(0, 0, 255)`` (B=0, G=0, R=255) y no como ``(255, 0, 0)``.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any

import numpy as np
import pytest
from starlette.datastructures import Headers, UploadFile

import app as vd


# ── Utilidades ──────────────────────────────────────────────────────────────
def _jpeg_con_bloque_rojo(ancho: int = 960, alto: int = 540) -> bytes:
    """JPEG con un cuadrado rojo puro en el centro (orden BGR)."""
    import cv2  # type: ignore[import-untyped]

    img = np.zeros((alto, ancho, 3), dtype=np.uint8)
    img[alto // 2 - 50: alto // 2 + 50, ancho // 2 - 50: ancho // 2 + 50] = (
        0,
        0,
        255,
    )  # rojo en BGR
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return bytes(buf)


def _es_rojo(pixel: Any) -> bool:
    """El píxel es rojo: canal R (índice 2) domina, B y G casi a cero.

    Se comprueba con tolerancia porque el JPEG es con pérdida: el 255
    puede volver como 254 o 253.
    """
    b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
    return r > 200 and b < 40 and g < 40


class _FakeEngine:
    """Motor YOLO falso: guarda la imagen que recibe el predictor."""

    def __init__(self) -> None:
        self.last_image: np.ndarray | None = None

    def predict(self, image: Any, **_: Any) -> list[Any]:
        self.last_image = image
        return []


def _upload(data: bytes) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename="captura.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )


# ── Tests ───────────────────────────────────────────────────────────────────
def test_decode_image_conserva_el_orden_de_canales() -> None:
    """``_decode_image`` devuelve BGR tal cual lo entrega OpenCV."""
    import cv2  # type: ignore[import-untyped]

    data = _jpeg_con_bloque_rojo()
    referencia = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert referencia is not None
    resultado = vd._decode_image(data)

    # El píxel del centro del cuadrado debe ser rojo en el canal R.
    centro = (referencia.shape[0] // 2, referencia.shape[1] // 2)
    assert _es_rojo(resultado[centro]), (
        f"el píxel rojo llegó como {list(resultado[centro])}: "
        "se ha intercambiado BGR↔RGB"
    )


def test_resize_no_altera_el_orden_de_canales() -> None:
    """El reescalado a 960x540 no puede reordenar los canales."""
    data = _jpeg_con_bloque_rojo()
    img = vd._decode_image(data)
    escalada = vd._resize_to_viewbox(img)

    assert escalada.shape[:2] == (vd.DETECT_H, vd.DETECT_W)
    assert _es_rojo(escalada[escalada.shape[0] // 2, escalada.shape[1] // 2])
    assert list(escalada[5, 5]) == list(img[5, 5])


def test_detect_entrega_al_motor_la_imagen_sin_invertir() -> None:
    """Punto de entrada: lo que llega a ``engine.predict`` conserva BGR."""
    motor = _FakeEngine()
    datos_originales = _jpeg_con_bloque_rojo()

    _engine_original, _error_original = vd._engine, vd._engine_error
    vd._engine, vd._engine_error = motor, None
    try:
        respuesta = asyncio.run(vd.detect(_upload(datos_originales)))
    finally:
        vd._engine, vd._engine_error = _engine_original, _error_original

    assert respuesta == []
    assert motor.last_image is not None, "el motor no llegó a ejecutarse"
    centro = (
        motor.last_image.shape[0] // 2,
        motor.last_image.shape[1] // 2,
    )
    assert _es_rojo(motor.last_image[centro]), (
        f"el motor recibió {list(motor.last_image[centro])} con los canales "
        "invertidos: el detector no detectará vehículos nunca más"
    )


def test_detect_rechaza_imagen_invalida() -> None:
    """Un fichero que no es imagen debe dar 400, no reventar."""
    from fastapi import HTTPException

    motor = _FakeEngine()
    _engine_original, _error_original = vd._engine, vd._engine_error
    vd._engine, vd._engine_error = motor, None
    try:
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(vd.detect(_upload(b"esto no es una imagen")))
    finally:
        vd._engine, vd._engine_error = _engine_original, _error_original

    assert excinfo.value.status_code == 400
