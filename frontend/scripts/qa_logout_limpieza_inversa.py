"""Prueba inversa del T-174: sin ``ui.reset()`` y con la ruta absoluta,
el cierre de sesion recarga la pagina (el toast no se ve), deja el
store de UI sucio y no usa el router.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).

Se deshace el arreglo por partes, porque son dos defectos distintos:

1. la recarga (``location.assign``) + el store sin limpiar: la QA tiene
   que fallar porque el toast NO se ve;
2. solo el store sin limpiar (pero con la navegacion del router): la
   QA tiene que fallar porque el estado de UI sucio sobrevive.
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
COPIA = Path(r"D:\tmp\_copias_t174")
COPIA.mkdir(parents=True, exist_ok=True)

RESET = "  ui.reset()\n"
NAVEGACION = (
    "  void router.push({ name: 'login' }).catch(() => {\n"
    "    /* ya estaba en el login: nada que hacer */\n"
    "  })"
)

MUTACIONES: list[tuple[str, str, str, str]] = [
    (
        "recarga + store sin limpiar",
        [RESET, NAVEGACION],
        ["", "  location.assign('/login')"],
        "no se ve",
    ),
    (
        "store sin limpiar (con el router)",
        [RESET],
        [""],
        "no se limpio",
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
    for nombre, viejos, nuevos, motivo in MUTACIONES:
        for viejo in viejos:
            if original.count(viejo) != 1:
                print(
                    f"ERROR ({nombre}): el bloque {viejo[:50]!r} aparece "
                    f"{original.count(viejo)} veces en AppLayout.vue."
                )
                return 1

    copia = COPIA / FICHERO.name
    shutil.copy2(FICHERO, copia)
    try:
        for nombre, viejos, nuevos, motivo in MUTACIONES:
            texto = original
            for viejo, nuevo in zip(viejos, nuevos):
                texto = texto.replace(viejo, nuevo)
            FICHERO.write_text(texto, encoding="utf-8", newline="")
            print(f"  {nombre}: quitado el arreglo")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            proc = subprocess.run(
                [sys.executable, "frontend/scripts/qa_logout_limpieza.py"],
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
    print("\nOK: la QA detecta los dos defectos del cierre de sesion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
