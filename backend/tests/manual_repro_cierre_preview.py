"""Reproduce el P0 del cierre del preview (SIGSEGV) contra un uvicorn dedicado.

Abre el preview MJPEG y lo cierra **de golpe** (como el navegador al
cerrar el modal), repetidas veces. Con la carrera entre
``cap.release()`` y el ``grab()`` en vuelo, el proceso muere con SIGSEGV
(exit 139). Con ``CapturaSincronizada`` (T-13+2) debe sobrevivir.

Uso: python /tmp/_repro_sigsegv.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import httpx

PUERTO = 8021
BASE = f"http://127.0.0.1:{PUERTO}"
API = f"{BASE}/api/v1"
VUELOS = 20


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PUERTO), "--log-level", "warning"],
        cwd=os.environ.get("APP_DIR", "/app"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        print("EL SERVIDOR NO ARRANCO")
        return 1
    print("[1] servidor dedicado arrancado")

    with httpx.Client(timeout=30) as c:
        tok = c.post(f"{API}/auth/login", json={
            "email": "gestor.madrid@solidapp.es", "password": "gestor1234",
        }).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    url = f"{API}/parkings/11/cameras/81/live"

    cierres = 0
    for vuelta in range(1, VUELOS + 1):
        s = httpx.Client(timeout=30)
        stream = s.stream("GET", url, headers=h)
        resp = stream.__enter__()
        if resp.status_code != 200:
            print(f"[2.{vuelta}] el preview no abrio: {resp.status_code}")
            stream.__exit__(None, None, None)
            s.close()
            continue
        # Leer un poco y cerrar de golpe (sin salir del todo limpio).
        try:
            for _ in range(2):
                next(resp.iter_bytes())
        except Exception:
            pass
        # Cierre ABRUPTO: se cierra el socket sin cerrar el stream con
        # gracia, que es lo que hace el navegador al cerrar el modal.
        stream.__exit__(None, None, None)
        s.close()
        cierres += 1
        if proc.poll() is not None:
            print(
                f"[2.{vuelta}] EL BACKEND HA MUERTO "
                f"(codigo {proc.returncode}) tras {cierres} cierres"
            )
            return 1
    print(f"[3] {cierres} cierres abruptos y el proceso sigue vivo")

    r = httpx.get(f"{BASE}/health", timeout=5)
    print("[4] health tras los cierres:", r.status_code)
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("RESULTADO: OK — cerrar el preview NO tumba el backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
