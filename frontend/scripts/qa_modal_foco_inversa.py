"""Prueba inversa del T-170: sin gestion del foco, el modal de cambiar
contrasena no la tiene (el foco no entra, el Tab sale a la pagina de
detras y al cerrar se pierde).

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).

Se deshace el arreglo **por partes** (foco al abrir, trampa del Tab y
devolucion del foco) y se exige que la QA falle por el motivo correcto
en cada caso: si se quitaran las tres a la vez, la QA pararia en la
primera y no se comprobarian las demas.
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
FICHERO = RAIZ / "frontend" / "src" / "layouts" / "AppLayout.vue"
COPIA = Path(r"D:\tmp\_copias_t170")
COPIA.mkdir(parents=True, exist_ok=True)

# (nombre, texto con el arreglo, texto con el defecto, motivo esperado)
MUTACIONES: list[tuple[str, str, str, str]] = [
    (
        "foco al abrir",
        "  void nextTick(() => enfocarDialogo())",
        "  void nextTick(() => {})",
        "no took el foco",
    ),
    (
        "trampa del Tab",
        "  document.addEventListener('keydown', onTeclaModal, true)",
        "  // sin listener (defecto de prueba): el Tab se sale del overlay",
        "se salio del dialogo",
    ),
    (
        "devolucion del foco",
        "  void nextTick(() => {\n"
        "    const anterior = pwdFocoAnterior\n"
        "    pwdFocoAnterior = null\n"
        "    if (anterior && document.contains(anterior)) {\n"
        "      anterior.focus()\n"
        "      return\n"
        "    }\n"
        "    // El elemento original ya no está (el menú se cierra al abrir el\n"
        "    // modal): el foco vuelve al botón del desplegable, no al <body>.\n"
        "    pwdTriggerRef.value?.focus()\n"
        "  })",
        "  void nextTick(() => {})",
        "el foco se perdio en el <body>",
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
    original = FICHERO.read_text(encoding="utf-8")
    copia = COPIA / FICHERO.name
    shutil.copy2(FICHERO, copia)
    try:
        for nombre, con_arreglo, con_defecto, motivo in MUTACIONES:
            if original.count(con_arreglo) != 1:
                print(
                    f"ERROR ({nombre}): el bloque aparece "
                    f"{original.count(con_arreglo)} veces en AppLayout.vue."
                )
                return 1

            FICHERO.write_text(
                original.replace(con_arreglo, con_defecto), encoding="utf-8", newline=""
            )
            print(f"  {nombre}: quitado el arreglo")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            proc = subprocess.run(
                [sys.executable, "frontend/scripts/qa_modal_foco.py"],
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
            if motivo not in salida:
                print(
                    f"*** AVISO: la QA fallo por otro motivo (se esperaba "
                    f"{motivo!r}): la prueba no vale."
                )
                return 1
            print(f"OK: sin el arreglo, la QA falla por el motivo correcto ({motivo}).")
    finally:
        shutil.copy2(copia, FICHERO)
        print("restaurado: frontend/src/layouts/AppLayout.vue")
        print("  reiniciando el frontend...")
        reiniciar_frontend()
    print("\nOK: la QA detecta las tres partes del defecto de foco")
    return 0


if __name__ == "__main__":
    sys.exit(main())
