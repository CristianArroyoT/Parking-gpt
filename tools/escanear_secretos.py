"""Escanea el HISTORIAL completo del repo en busca de secretos.

El árbol versionado puede estar limpio y aun así haber habido un
secreto commiteado hace meses y borrado después: en un repositorio
PÚBLICO, esa credencial sigue expuesta en el historial.

Uso:
    python tools/escanear_secretos.py --historial
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: (nombre, expresion) de los secretos que no queremos en el historial.
PATRONES_HISTORIAL = [
    ("clave privada PEM", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("token de GitHub", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("clave de AWS", r"AKIA[0-9A-Z]{16}"),
    ("token de Slack", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("token de OpenAI", r"sk-[A-Za-z0-9]{32,}"),
    ("JWT con valor real", r"JWT_SECRET\s*=\s*[\"'][^\"'\n]{12,}[\"']"),
    ("secret de app con valor real", r"SECRET_KEY\s*=\s*[\"'][^\"'\n]{16,}[\"']"),
    ("cadena de conexion con clave", r"postgres(?:ql)?://[^\s:]+:[^\s@]+@"),
]

#: Valores de ejemplo: no son secretos.
MARCADORES = re.compile(
    r"change-me|change_me|ci-secret|ci_secret|your[-_ ]|example|EXAMPLE|"
    r"placeholder|dummy|xxxx|yourpassword|\.\.\.|<[^>]+>",
    re.IGNORECASE,
)


def main() -> int:
    if "--historial" not in sys.argv:
        print("Uso: python tools/escanear_secretos.py --historial")
        return 2

    print("Escaneando el historial completo (git log -p --all)...")
    salida = subprocess.run(
        ["git", "log", "-p", "--all", "--no-color"],
        cwd=str(RAIZ), capture_output=True, text=True, check=False,
        # El historial tiene UTF-8 (acentos, emoji) y la consola de
        # Windows usa cp1252: hay que forzar la decodificación.
        encoding="utf-8", errors="replace",
    ).stdout or ""
    lineas = salida.splitlines()
    print(f"  {len(lineas)} líneas escaneadas")

    hallazgos: list[str] = []
    for nombre, patron in PATRONES_HISTORIAL:
        regex = re.compile(patron)
        for linea in lineas:
            if not regex.search(linea):
                continue
            if MARCADORES.search(linea):
                continue
            # La línea sólo cuenta si es una ASIGNACIÓN o una credencial
            # de verdad, no si aparece en un comentario que habla de
            # ellas.
            if linea.lstrip().startswith("#") or linea.lstrip().startswith("//"):
                continue
            hallazgos.append(f"  [{nombre}] {linea.strip()[:150]}")
            if len(hallazgos) > 40:
                break

    if hallazgos:
        print(f"\n{len(hallazgos)} posible(s) secreto(s) en el HISTORIAL:")
        for h in hallazgos:
            print(h)
        print("\nSi son reales, hay que ROTAR la credencial: borrarla del "
              "historial no basta.")
        return 1
    print("\nOK: no hay secretos en el historial.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
