"""Prueba inversa del T-140: sin la redireccion al login, la sesion caducada
NO expulsa al operador (la URL se queda en /mapa y el mapa sigue mostrando
los datos con el rotulo «Sin sesion»).

MEDIDO (2026-10-24, con un navegador de verdad):

    - el evento ``solidapp:sesion-caducada`` SI se dispara;
    - los tokens SI se limpian;
    - pero la URL se queda en /mapa y la pantalla sigue viva.

Es decir: el guard del router **solo corre al navegar**, y sin una
redireccion explicita el operador se queda en una pagina muerta.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el arreglo
(con el bind mount, el HMR de Vite no siempre aplica y se mide el bundle
viejo).
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
FICHERO = RAIZ / "frontend" / "src" / "router" / "index.ts"
COPIA = Path(r"D:\tmp\_copias_t140")
COPIA.mkdir(parents=True, exist_ok=True)

MARCA = "window.addEventListener('solidapp:sesion-caducada'"
APERTURA = "if (typeof window !== 'undefined') {"


def _quitar_el_listener(texto: str) -> str | None:
    """Quita el bloque que registra el listener del router.

    Se busca por la llave de cierre (balanceada), no por un texto fijo: el
    bloque cambia con el tiempo y una copia literal se quedaria obsoleta
    (y la prueba dejaria de poner el defecto, sin avisar).
    """
    pos_evento = texto.find(MARCA)
    if pos_evento < 0:
        return None
    pos_if = texto.rfind(APERTURA, 0, pos_evento)
    if pos_if < 0:
        return None
    nivel = 0
    fin = None
    i = pos_if
    while i < len(texto):
        if texto[i] == "{":
            nivel += 1
        elif texto[i] == "}":
            nivel -= 1
            if nivel == 0:
                fin = i + 1
                break
        i += 1
    if fin is None:
        return None
    return texto[:pos_if] + texto[fin:]


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


texto_original = FICHERO.read_text(encoding="utf-8")
texto_sin = _quitar_el_listener(texto_original)
if texto_sin is None:
    print("ERROR: no se encuentra el listener del router: no se puede probar nada.")
    sys.exit(1)
if texto_sin == texto_original:
    print("ERROR: el listener no se ha quitado: la prueba no valdria.")
    sys.exit(1)

shutil.copy2(FICHERO, COPIA / FICHERO.name)
try:
    FICHERO.write_text(texto_sin, encoding="utf-8", newline="")
    print("  quitada la redireccion al login del router")

    print("  reiniciando el frontend...")
    reiniciar_frontend()

    proc = subprocess.run(
        [sys.executable, "frontend/scripts/qa_sesion_caducada.py"],
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
        sys.exit(1)
    if "NO expulso" not in salida:
        print("*** AVISO: fallo por otro motivo: la prueba no vale.")
        sys.exit(1)
    print("OK: sin la redireccion, la QA falla por el motivo correcto.")
finally:
    shutil.copy2(COPIA / FICHERO.name, FICHERO)
    print("restaurado: frontend/src/router/index.ts")
    print("  reiniciando el frontend...")
    reiniciar_frontend()
