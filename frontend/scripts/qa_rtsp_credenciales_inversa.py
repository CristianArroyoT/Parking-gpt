"""Prueba inversa del T-173: sin enmascarar, la URL RTSP (con
credenciales) se pinta en el DOM.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(r"D:\Parking")
FICHERO = RAIZ / "frontend" / "src" / "views" / "gestor" / "CamerasView.vue"
COPIA = Path(r"D:\tmp\_copias_t173")
COPIA.mkdir(parents=True, exist_ok=True)

CON_ARREGLO = "{{ enmascararRtsp(cam.rtsp_url) }}"
SIN_ARREGLO = "{{ cam.rtsp_url }}"


def reiniciar_frontend() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "frontend"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    fin = time.time() + 180
    while time.time() < fin:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5173/login", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(3)
    print("AVISO: el frontend no respondio tras el reinicio.")


def main() -> int:
    original = FICHERO.read_text(encoding="utf-8")
    if original.count(CON_ARREGLO) != 1:
        print(
            f"ERROR: el texto {CON_ARREGLO!r} aparece "
            f"{original.count(CON_ARREGLO)} veces en CamerasView.vue."
        )
        return 1

    copia = COPIA / FICHERO.name
    shutil.copy2(FICHERO, copia)
    try:
        FICHERO.write_text(
            original.replace(CON_ARREGLO, SIN_ARREGLO), encoding="utf-8", newline=""
        )
        print("  quitado el enmascarado de la URL RTSP")

        print("  reiniciando el frontend...")
        reiniciar_frontend()

        proc = subprocess.run(
            [sys.executable, "frontend/scripts/qa_rtsp_credenciales.py"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        salida = (proc.stdout or "") + (proc.stderr or "")
        print("\nSalida de la QA con el defecto:")
        print(salida.strip()[:800])
        print(f"\ncodigo de salida: {proc.returncode}")
        if proc.returncode == 0:
            print("*** FALLO: la QA pasa sin el arreglo: no demuestra nada.")
            return 1
        if "en el DOM" not in salida:
            print("*** AVISO: fallo por otro motivo: la prueba no vale.")
            return 1
        print("OK: sin el enmascarado, la QA falla por el motivo correcto.")
    finally:
        shutil.copy2(copia, FICHERO)
        print("restaurado: frontend/src/views/gestor/CamerasView.vue")
        print("  reiniciando el frontend...")
        reiniciar_frontend()
    return 0


if __name__ == "__main__":
    sys.exit(main())
