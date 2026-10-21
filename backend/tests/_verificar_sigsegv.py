"""Reproduce el P0: cerrar el preview tumbaba el backend (SIGSEGV).

Arranca un uvicorn DEDICADO (sin --reload, como en produccion), abre y
cierra el preview varias veces de golpe y comprueba que el proceso sigue
vivo.

Con el bug (T-13+1) el proceso moria con SIGSEGV (exit 139) en el
primer cierre.
"""
from __future__ import annotations

import subprocess
import sys
import time

import httpx

PUERTO = 8013
BASE = f"http://127.0.0.1:{PUERTO}"
API = f"{BASE}/api/v1"
VUELOS = 5


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PUERTO), "--log-level", "warning"],
        cwd="/app", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
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
    print("[1] servidor dedicado arrancado (sin --reload)")

    with httpx.Client(timeout=30) as c:
        tok = c.post(f"{API}/auth/login", json={
            "email": "gestor.madrid@solidapp.es", "password": "gestor1234",
        }).json()["access_token"]
    print("[2] login ok")

    for vuelta in range(1, VUELOS + 1):
        # Abrir el preview y CERRARLO de golpe (como el navegador al
        # cerrar el modal).
        sse = httpx.Client(timeout=30)
        stream = sse.stream("GET", f"{API}/parkings/11/cameras/81/live",
                             headers={"Authorization": f"Bearer {tok}"})
        resp = stream.__enter__()
        if resp.status_code != 200:
            print(f"[3.{vuelta}] el preview no abrio: {resp.status_code}")
            stream.__exit__(None, None, None)
            sse.close()
            continue
        # Leer un frame y cortar de golpe.
        try:
            next(resp.iter_bytes())
        except Exception:
            pass
        stream.__exit__(None, None, None)
        sse.close()
        time.sleep(1.5)
        vivo = proc.poll() is None
        print(f"[3.{vuelta}] preview cerrado | proceso vivo: {vivo}")
        if not vivo:
            print(f"RESULTADO: FALLO — el backend murio (codigo {proc.returncode})")
            return 1

    print("[4] el proceso sigue vivo tras", VUELOS, "cierres")
    # El health sigue respondiendo.
    r = httpx.get(f"{BASE}/health", timeout=5)
    print("[5] health:", r.status_code)
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("RESULTADO: OK — cerrar el preview ya no tumba el backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
