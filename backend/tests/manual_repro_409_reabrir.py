"""Reproduce el P2 del preview: ventana de 409 al reabrir el stream.

Escenario real (operador):
  1. Abre el modal "Ver en vivo" de la cámara 81 (RTSP de verdad).
  2. Cierra el modal → el navegador aborta la petición ``<img>``.
  3. Inmediatamente vuelve a abrirlo → ¿cuánto tarda en dejar de
     devolver 409?

Por qué devuelve 409: el registro de streams (``live_streams``) mantiene
el slot de la cámara ocupado mientras dura el stream. El slot se libera
en el ``finally`` del generador, que se ejecuta DESPUÉS de la limpieza
bloqueante de la captura (``cap.release()``: el teardown del RTSP puede
tardar segundos). Durante ese hueco, un cliente nuevo recibe 409.

La red de seguridad es el barrido de sesiones huérfanas
(``STALE_AFTER_S = 8``): si pasan 8 s sin heartbeat, el slot se libera
por la fuerza. Por eso la ventana observada es de ~8 s.

Salida esperada (con el arreglo): la ventana de 409 es de milisegundos,
no de segundos.

Uso: python backend/tests/manual_repro_409_reabrir.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("SOLIDAPP_BASE", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
PARKING_ID = 11
CAMERA_ID = 81
EMAIL = "gestor.madrid@solidapp.es"
PASSWORD = "gestor1234"
VUELOS = int(os.environ.get("VUELOS", "3"))


def _login() -> str:
    with httpx.Client(timeout=30) as c:
        r = c.post(
            f"{API}/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
        )
        r.raise_for_status()
        return r.json()["access_token"]


def _abrir_y_cerrar(token: str) -> None:
    """Abre el stream, lee un frame y lo cierra de golpe."""
    with httpx.Client(timeout=30) as s, s.stream(
        "GET",
        f"{API}/parkings/{PARKING_ID}/cameras/{CAMERA_ID}/live",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(
                f"el preview no abrio: {resp.status_code} {resp.read()[:200]!r}"
            )
        # Leemos hasta el primer frame real (no el placeholder).
        leido = 0
        for chunk in resp.iter_bytes():
            leido += len(chunk)
            if leido > 2000:
                break
    # Al salir del ``with`` el socket se cierra: es el cierre
    # abrupto que hace el navegador al cerrar el modal.


def _esperar_a_200(token: str, timeout_s: float = 30.0) -> tuple[float, int | None]:
    """Reintenta abrir el preview hasta que deje de dar 409.

    Returns:
        (segundos hasta el primer 200, código del primer 409 visto)
    """
    inicio = time.monotonic()
    primer_409: int | None = None
    while time.monotonic() - inicio < timeout_s:
        try:
            with httpx.Client(timeout=30) as s, s.stream(
                "GET",
                f"{API}/parkings/{PARKING_ID}/cameras/{CAMERA_ID}/live",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status_code == 200:
                    return time.monotonic() - inicio, primer_409
                primer_409 = resp.status_code
                resp.read()
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    return -1.0, primer_409


def main() -> int:
    token = _login()
    print(f"[1] login OK contra {BASE}")

    ventanas: list[float] = []
    for vuelta in range(1, VUELOS + 1):
        _abrir_y_cerrar(token)
        t0 = time.monotonic()
        espera, cod = _esperar_a_200(token)
        if espera < 0:
            print(f"[2.{vuelta}] NO se pudo reabrir en 30 s (último código {cod})")
            return 1
        ventanas.append(espera)
        print(
            f"[2.{vuelta}] ventana de 409 tras cerrar: {espera * 1000:.0f} ms "
            f"(código del 409: {cod})"
        )
        time.sleep(0.3)

    peor = max(ventanas)
    media = sum(ventanas) / len(ventanas)
    print(f"[3] peor ventana: {peor * 1000:.0f} ms | media: {media * 1000:.0f} ms")
    if peor > 1.0:
        print("RESULTADO: FALLO — la ventana de 409 es de segundos (P2 abierto)")
        return 1
    print("RESULTADO: OK — la ventana de 409 es despreciable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
