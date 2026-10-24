"""Prueba inversa del T-172: sin limpiar la URL, el token de
recuperacion se queda en la barra de direcciones.

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
FICHERO = RAIZ / "frontend" / "src" / "views" / "cliente" / "ResetPasswordView.vue"
COPIA = Path(r"D:\tmp\_copias_t172")
COPIA.mkdir(parents=True, exist_ok=True)

# La llamada que limpia la URL (la funcion se queda, pero sin usar: el
# efecto es que el token sigue en la barra de direcciones).
CON_ARREGLO = "    limpiarTokenDeLaUrl()\n"
SIN_ARREGLO = "    // (defecto de prueba) el token se queda en la URL\n"


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
            f"ERROR: la llamada a limpiarTokenDeLaUrl aparece "
            f"{original.count(CON_ARREGLO)} veces."
        )
        return 1

    copia = COPIA / FICHERO.name
    shutil.copy2(FICHERO, copia)
    try:
        FICHERO.write_text(
            original.replace(CON_ARREGLO, SIN_ARREGLO), encoding="utf-8", newline=""
        )
        print("  quitado el arreglo (la URL no se limpia)")

        print("  reiniciando el frontend...")
        reiniciar_frontend()

        proc = subprocess.run(
            [sys.executable, "frontend/scripts/qa_token_url.py"],
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
        if "se queda en la URL" not in salida:
            print("*** AVISO: fallo por otro motivo: la prueba no vale.")
            return 1
        print("OK: sin el arreglo, la QA falla por el motivo correcto.")
    finally:
        shutil.copy2(copia, FICHERO)
        print("restaurado: frontend/src/views/cliente/ResetPasswordView.vue")
        print("  reiniciando el frontend...")
        reiniciar_frontend()
    return 0


if __name__ == "__main__":
    sys.exit(main())
