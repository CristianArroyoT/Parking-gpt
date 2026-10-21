"""Verifica en vivo que un stream SSE abierto no bloquea el apagado.

Arranca un uvicorn SIN reload en un puerto libre, abre una conexión SSE
contra él, envía SIGTERM y mide cuánto tarda el proceso en terminar.

Con el bug (T-06+1) el proceso se queda en "Waiting for connections to
close" y hay que matarlo con SIGKILL. Con el arreglo debe terminar en
menos de un par de segundos.

Uso: python /tmp/verificar_apagado_sse.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import httpx

PUERTO = 8013
BASE = f"http://127.0.0.1:{PUERTO}"
API = f"{BASE}/api/v1"


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PUERTO), "--log-level", "info"],
        cwd="/app",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 1) Esperar a que arranque.
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
    print("[1] servidor arrancado")

    # 2) Login.
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{API}/auth/login",
                   json={"email": "gestor.madrid@solidapp.es",
                         "password": "gestor1234"})
        r.raise_for_status()
        token = r.json()["access_token"]
    print("[2] login ok")

    # 3) Abrir el SSE y dejarlo abierto.
    sse = httpx.Client(timeout=300)
    stream = sse.stream("GET", f"{API}/parkings/11/events",
                         headers={"Authorization": f"Bearer {token}"})
    resp = stream.__enter__()
    print(f"[3] SSE abierto: {resp.status_code} {resp.headers.get('content-type')}")
    assert resp.status_code == 200, resp.text

    # 4) SIGTERM y medir.
    t0 = time.perf_counter()
    os.kill(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=20)
        dur = time.perf_counter() - t0
        print(f"[4] PROCESO TERMINADO en {dur:.2f} s (codigo {proc.returncode})")
        ok = dur < 5.0
    except subprocess.TimeoutExpired:
        print("[4] EL PROCESO SIGUE VIVO tras 20 s -> HANG (uvicorn esperando "
              "a que terminen las conexiones abiertas)")
        proc.kill()
        proc.wait(timeout=10)
        ok = False
    finally:
        stream.__exit__(None, None, None)
        sse.close()

    if ok:
        print("RESULTADO: OK — el SSE no bloquea el apagado")
    else:
        print("RESULTADO: FALLO — el SSE bloquea el apagado")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
