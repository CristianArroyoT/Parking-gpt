"""El probe de cámara respeta su propio timeout (T-112).

POR QUÉ existe este fichero: el ``timeout_s`` del probe (5 s) **no se
cumplía**: el timeout que mandaba era el de FFmpeg (30 s), porque la
captura se abría sin timeout. Medido el 2026-10-23 con una cámara
colgada (una IP que no contesta):

- **antes**: el probe tardaba **30,12 s** (y la ronda, que espera a los
  hilos del executor, también);
- **después**: **5,02 s**.

Y no era un detalle: con el healthcheck del worker en 20 s, una cámara
colgada marcaba el contenedor como *unhealthy* y Docker lo reiniciaba
(con ``restart: unless-stopped``, T-101) → bucle de reinicios.

El timeout se pasa en la **apertura** (en OpenCV, ``cap.set()`` después
de abrir ya no cambia el tiempo de espera).
"""
from __future__ import annotations

import asyncio
import time

import cv2
import pytest

from app.services.cameras import heartbeat as hb


class _CamaraFalsa:
    def __init__(self, url: str) -> None:
        self.rtsp_url = url


def test_la_captura_se_abre_con_el_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La captura se abre con el timeout de apertura y de lectura."""
    recibidos: list[object] = []

    class _CapFalsa:
        def __init__(self, *args: object) -> None:
            recibidos.append(args)

        def isOpened(self) -> bool:  # noqa: N802 (mismo nombre que OpenCV)
            return False

        def release(self) -> None:
            pass

    monkeypatch.setattr(hb.cv2, "VideoCapture", _CapFalsa)

    hb._probe_sync("rtsp://ejemplo/stream", 5.0)

    assert recibidos, "no se abrio ninguna captura"
    argumentos = recibidos[0]
    assert isinstance(argumentos, tuple)
    assert len(argumentos) == 3, argumentos
    assert argumentos[1] == hb.cv2.CAP_FFMPEG
    # El tercer argumento es la lista [id, valor, id, valor, ...].
    opciones = argumentos[2]
    assert isinstance(opciones, list)
    assert cv2.CAP_PROP_OPEN_TIMEOUT_MSEC in opciones
    assert cv2.CAP_PROP_READ_TIMEOUT_MSEC in opciones
    # Los milisegundos del timeout pedido (5 s).
    assert opciones[opciones.index(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC) + 1] == 5000
    assert opciones[opciones.index(cv2.CAP_PROP_READ_TIMEOUT_MSEC) + 1] == 5000


def test_un_probe_colgado_respeta_el_timeout() -> None:
    """Una cámara que no contesta devuelve False en el tiempo previsto.

    Usa una IP de blackhole (10.255.255.1): no hay nadie al otro lado, y
    elFFmpeg se rinde con su propio timeout (30 s) o con el nuestro (5 s).
    """
    camara = _CamaraFalsa("rtsp://10.255.255.1/stream")

    inicio = time.perf_counter()
    resultado = asyncio.run(hb.probe_camera(camara, timeout_s=5.0))  # type: ignore[arg-type]
    duracion = time.perf_counter() - inicio

    assert resultado is False
    assert duracion < 15.0, (
        f"el probe tardó {duracion:.1f}s: el timeout de la captura no se "
        "está aplicando y la ronda se alarga (el healthcheck del worker "
        "falla a los 20 s y Docker reinicia el contenedor)"
    )
