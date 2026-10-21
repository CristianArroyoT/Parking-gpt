"""Mide el coste real de ``cap.release()`` con un RTSP de verdad.

Por qué importa: ``cap.release()`` se llama en el ``finally`` del
generador MJPEG, es decir **en el hilo del event loop**. Si tarda
segundos (teardown de FFmpeg/RTSP), bloquea TODO el backend: no sólo
ese stream, sino cada request en curso.

Este script mide tres cosas:
  1. Cuánto tarda ``cv2.VideoCapture`` en abrir el RTSP.
  2. Cuánto tarda el primer ``grab()`` (latencia del primer frame).
  3. Cuánto tarda ``release()`` con la cámara sana.
  4. Cuánto tarda ``release()`` con la cámara MUERTA (RTSP que no
     responde): es el peor caso.

Uso (dentro de la red de Docker):
    python _medir_release.py
"""
from __future__ import annotations

import statistics
import time

import cv2

URL = "rtsp://parking-mediamtx:8554/cam1"
MUERTA = "rtsp://parking-mediamtx:8554/no-existe"
VUELOS = 5


def _medir(url: str) -> dict[str, float]:
    t0 = time.monotonic()
    cap = cv2.VideoCapture(url)
    t_abrir = time.monotonic() - t0
    abierto = bool(cap.isOpened())

    t0 = time.monotonic()
    ok = False
    if abierto:
        ok = bool(cap.grab())
    t_grab = time.monotonic() - t0

    t0 = time.monotonic()
    cap.release()
    t_release = time.monotonic() - t0
    return {
        "abrir": t_abrir,
        "grab": t_grab,
        "release": t_release,
        "abierto": abierto,
        "ok": ok,
    }


def main() -> None:
    print(f"== RTSP sano: {URL}")
    releases = []
    for _ in range(VUELOS):
        m = _medir(URL)
        releases.append(m["release"])
        print(
            f"  abrir={m['abrir'] * 1000:.0f} ms  grab={m['grab'] * 1000:.0f} ms  "
            f"release={m['release'] * 1000:.0f} ms  abierto={m['abierto']} grab_ok={m['ok']}"
        )
    print(
        f"  release sano: media={statistics.mean(releases) * 1000:.0f} ms  "
        f"max={max(releases) * 1000:.0f} ms"
    )

    print(f"== RTSP muerto: {MUERTA}")
    m = _medir(MUERTA)
    print(
        f"  abrir={m['abrir'] * 1000:.0f} ms  grab={m['grab'] * 1000:.0f} ms  "
        f"release={m['release'] * 1000:.0f} ms  abierto={m['abierto']}"
    )


if __name__ == "__main__":
    main()
