"""Prueba inversa del T-138: sin el arreglo, el gestor sin sucursales
ve el mensaje FALSO («no hay movimientos que cumplan los filtros») en vez
de explicar que no tiene ninguna sucursal asignada.

OJO: hay que **reiniciar el frontend** tras quitar (o restaurar) el
arreglo: con el bind mount, el HMR de Vite no siempre aplica, y sin
reiniciar se mide el bundle viejo (falso positivo: la QA pasaba con el
defecto puesto).
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
COPIAS = Path(r"D:\tmp\_copias_t138")
COPIAS.mkdir(parents=True, exist_ok=True)
VISTAS = [
    RAIZ / "frontend" / "src" / "views" / "gestor" / "MovementsView.vue",
    RAIZ / "frontend" / "src" / "views" / "gestor" / "AlertsView.vue",
]

CON_ARRREGLO = """    loading.value = false
    error.value = 'No tienes ninguna sucursal asignada'
    return
"""
SIN_ARRREGLO = """    return
"""


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


for vista in VISTAS:
    shutil.copy2(vista, COPIAS / vista.name)

try:
    for vista in VISTAS:
        texto = vista.read_text(encoding="utf-8")
        nl = "\r\n" if "\r\n" in texto else "\n"
        bloque = CON_ARRREGLO.replace("\n", nl)
        if texto.count(bloque) != 1:
            print(f"ERROR ({vista.name}): el bloque aparece {texto.count(bloque)} veces.")
            sys.exit(1)
        vista.write_text(
            texto.replace(bloque, SIN_ARRREGLO.replace("\n", nl)),
            encoding="utf-8",
            newline="",
        )
        print(f"  quitado el arreglo de {vista.name}")

    print("  reiniciando el frontend (el HMR no siempre aplica)...")
    reiniciar_frontend()

    proc = subprocess.run(
        [sys.executable, "frontend/scripts/qa_gestor_sin_sucursal.py"],
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
        sys.exit(1)
    # Los dos fallos son validos: el "Cargando..." infinito (cuando no
    # hay sucursal, el return temprano no baja el flag) y el mensaje
    # falso ("no hay movimientos" cuando lo que no hay es la sucursal).
    motivos_validos = ("sigue en", "afirma que no hay datos")
    if not any(motivo in salida for motivo in motivos_validos):
        print("*** AVISO: fallo por otro motivo: la prueba no vale.")
        sys.exit(1)
    print("OK: sin el arreglo, la QA falla por el motivo correcto.")
finally:
    for vista in VISTAS:
        shutil.copy2(COPIAS / vista.name, vista)
    print("restauradas las dos vistas")
    print("  reiniciando el frontend...")
    reiniciar_frontend()
