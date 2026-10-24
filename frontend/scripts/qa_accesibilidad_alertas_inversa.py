"""Prueba inversa del T-169: sin el ``role="alert"``, los errores de
formulario no se anuncian.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).

Se deshace el arreglo **de una vista cada vez** (login, reset de
contrasena, alta manual, detalle de ticket, modal de incidente y vista
en vivo de la calibracion) y se exige que la QA falle por el motivo
correcto en cada caso: si se quitaran todas a la vez, la QA pararia en
la primera y no se comprobarian las demas.
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
SRC = RAIZ / "frontend" / "src"
COPIA = Path(r"D:\tmp\_copias_t169")
COPIA.mkdir(parents=True, exist_ok=True)

# (fichero, texto con el arreglo, texto con el defecto, motivo esperado,
#  numero de apariciones esperadas)
MUTACIONES: list[tuple[str, str, str, str, int]] = [
    (
        "views/LoginView.vue",
        '<p v-if="auth.error" class="text-sm text-rose-600" role="alert" aria-live="assertive">',
        '<p v-if="auth.error" class="text-sm text-rose-600">',
        "login",
        1,
    ),
    (
        "views/cliente/ResetPasswordView.vue",
        '<p v-if="error" class="text-sm text-rose-600" role="alert" aria-live="assertive">',
        '<p v-if="error" class="text-sm text-rose-600">',
        "reset de contrasena",
        2,
    ),
    (
        "views/operador/ManualEntryView.vue",
        '<p class="text-sm text-rose-800" role="alert" aria-live="assertive">',
        '<p class="text-sm text-rose-800">',
        "alta manual",
        1,
    ),
    (
        "views/cliente/TicketsView.vue",
        '            class="text-sm text-rose-600 py-4 text-center"\n'
        '            role="alert"\n'
        '            aria-live="assertive"\n',
        '            class="text-sm text-rose-600 py-4 text-center"\n',
        "ticket",
        1,
    ),
    (
        "views/operador/IncidentModal.vue",
        '<p class="text-sm text-rose-800" role="alert" aria-live="assertive">',
        '<p class="text-sm text-rose-800">',
        "incidente",
        1,
    ),
    (
        "views/gestor/CalibrateView.vue",
        '              class="text-rose-300 text-sm px-4 text-center"\n'
        '              role="alert"\n'
        '              aria-live="assertive"\n',
        '              class="text-rose-300 text-sm px-4 text-center"\n',
        "calibracion",
        1,
    ),
]


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
    for relativo, con_arreglo, con_defecto, motivo, veces in MUTACIONES:
        ruta = SRC / relativo
        original = ruta.read_text(encoding="utf-8")
        if original.count(con_arreglo) != veces:
            print(
                f"ERROR: en {relativo} el arreglo aparece "
                f"{original.count(con_arreglo)} veces (se esperaban {veces})."
            )
            return 1

        copia = COPIA / ruta.name
        shutil.copy2(ruta, copia)
        try:
            ruta.write_text(
                original.replace(con_arreglo, con_defecto), encoding="utf-8", newline=""
            )
            print(f"  {relativo}: quitado el role=alert")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            proc = subprocess.run(
                [sys.executable, "frontend/scripts/qa_accesibilidad_alertas.py"],
                cwd=RAIZ,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            salida = (proc.stdout or "") + (proc.stderr or "")
            print("\nSalida de la QA con el defecto:")
            print(salida.strip()[:900])
            print(f"\ncodigo de salida: {proc.returncode}")
            if proc.returncode == 0:
                print("*** FALLO: la QA pasa sin el arreglo: no demuestra nada.")
                return 1
            if "no se anuncia" not in salida:
                print("*** AVISO: fallo por otro motivo: la prueba no vale.")
                return 1
            if motivo not in salida:
                print(
                    f"*** AVISO: la QA fallo por otro caso (se esperaba "
                    f"{motivo!r}): la prueba no vale."
                )
                return 1
            print(f"OK: sin el arreglo, la QA falla por el motivo correcto ({motivo}).")
        finally:
            shutil.copy2(copia, ruta)
            print(f"restaurado: frontend/src/{relativo}")
            print("  reiniciando el frontend...")
            reiniciar_frontend()
    print("\nOK: la QA detecta el defecto en las seis vistas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
