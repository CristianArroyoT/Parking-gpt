"""Prueba inversa del T-171: sin ``for``/``id``, los campos de los
formularios de administracion (y el de cams) se anuncian SIN NOMBRE.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).

Se deshace el arreglo en un formulario cada vez (sucursales, tarifas y
cams) y se exige que la QA falle por el motivo correcto en cada caso.
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
COPIA = Path(r"D:\tmp\_copias_t171")
COPIA.mkdir(parents=True, exist_ok=True)

# (fichero, id del par etiqueta/campo, motivo esperado)
MUTACIONES: list[tuple[str, str, str]] = [
    ("views/admin/ParkingsView.vue", "parking-codigo", "/admin/parkings"),
    ("views/admin/TariffsView.vue", "tarifa-nombre", "/admin/tariffs"),
    ("views/gestor/CamerasView.vue", "camara-rtsp", "/cameras"),
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
    for relativo, id_campo, vista in MUTACIONES:
        ruta = SRC / relativo
        original = ruta.read_text(encoding="utf-8")
        copia = COPIA / ruta.name
        shutil.copy2(ruta, copia)
        try:
            con_for = f' for="{id_campo}"'
            con_id = f' id="{id_campo}"'
            if original.count(con_for) != 1 or original.count(con_id) != 1:
                print(
                    f"ERROR: en {relativo} el par {id_campo!r} aparece "
                    f"{original.count(con_for)} veces como for= y "
                    f"{original.count(con_id)} como id=."
                )
                return 1

            texto = original.replace(con_for, "").replace(con_id, "")
            ruta.write_text(texto, encoding="utf-8", newline="")
            print(f"  {relativo}: quitado el for/id de {id_campo!r}")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            proc = subprocess.run(
                [sys.executable, "frontend/scripts/qa_labels_admin.py"],
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
            if "SIN NOMBRE" not in salida:
                print("*** AVISO: fallo por otro motivo: la prueba no vale.")
                return 1
            if vista not in salida:
                print(
                    f"*** AVISO: la QA fallo por otra vista (se esperaba "
                    f"{vista!r}): la prueba no vale."
                )
                return 1
            print(f"OK: sin el arreglo, la QA falla por el motivo correcto ({vista}).")
        finally:
            shutil.copy2(copia, ruta)
            print(f"restaurado: frontend/src/{relativo}")
            print("  reiniciando el frontend...")
            reiniciar_frontend()
    print("\nOK: la QA detecta el defecto en los tres formularios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
