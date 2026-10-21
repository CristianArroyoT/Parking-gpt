"""Escanea el repositorio en busca de secretos.

El repositorio es **público**: un secreto commiteado no es un
inconveniente, es una credencial filtrada. Y un secreto puede haber
estado commiteado hace meses y borrado después: en el historial sigue
expuesto.

Dos modos:

  * sin argumentos: escanea el **árbol versionado** (lo que se ve hoy).
  * ``--historial``: escanea además el **historial completo** de
    commits (``git log -p --all``).

En los dos casos se distinguen los valores de ejemplo (las plantillas
``.env.example``, los ficheros de prueba, las contraseñas demo del
seed) de los que serían reales.

Uso:
    python tools/escanear_secretos.py
    python tools/escanear_secretos.py --historial
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: (nombre, expresion) de los secretos que no queremos en el repositorio.
PATRONES = [
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
    r"placeholder|dummy|xxxx|yourpassword|\.\.\.|<[^>]+>|test|seed|local|demo|"
    r"password|admin12345|gestor1234|oper12345|cliente1234|localhost|127\.0\.0\.1|"
    # El usuario y la clave por defecto de la imagen oficial de
    # Postgres: nunca existieron en un entorno real, pero salen en el
    # historial de los ficheros de compose de antes.
    r"postgres:postgres",
    re.IGNORECASE,
)

#: Ficheros donde un "secreto" es legitimo (plantillas, pruebas, seed).
EXENTOS = re.compile(
    r"(\.env\.example|/tests?/|/seed|conftest\.py|\.example|\.sample|"
    r"docs/|/locust/|\.md$|__init__\.py)",
    re.IGNORECASE,
)


def _git_grep(patron: str) -> list[str]:
    """Lineas del arbol versionado que casan con el patron."""
    try:
        salida = subprocess.run(
            ["git", "grep", "-n", "-I", "-E", patron, "--", "."],
            cwd=str(RAIZ), capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:  # pragma: no cover
        return []
    return [linea for linea in salida.stdout.splitlines() if linea.strip()]


def _escanear_arbol() -> int:
    hallazgos: list[str] = []
    for nombre, patron in PATRONES:
        for linea in _git_grep(patron):
            ruta = linea.split(":", 1)[0] if ":" in linea else ""
            if EXENTOS.search(ruta):
                continue
            if MARCADORES.search(linea):
                continue
            # Una linea que sólo habla de como NO hacer las cosas no es
            # un secreto.
            if linea.lstrip().startswith(("#", "//")):
                continue
            hallazgos.append(f"  [{nombre}] {linea.strip()[:160]}")

    if hallazgos:
        print(f"{len(hallazgos)} posible(s) secreto(s) en el arbol versionado:")
        for h in hallazgos:
            print(h)
        return 1
    print("OK: no hay secretos en el arbol versionado.")
    return 0


def _escanear_historial() -> int:
    print("Escaneando el historial completo (git log -p --all)...")
    salida = subprocess.run(
        ["git", "log", "-p", "--all", "--no-color"],
        cwd=str(RAIZ), capture_output=True, text=True, check=False,
        # El historial tiene UTF-8 (acentos, emoji) y la consola de
        # Windows usa cp1252: hay que forzar la decodificacion.
        encoding="utf-8", errors="replace",
    ).stdout or ""
    lineas = salida.splitlines()
    print(f"  {len(lineas)} lineas escaneadas")

    hallazgos: list[str] = []
    for nombre, patron in PATRONES:
        regex = re.compile(patron)
        for linea in lineas:
            if not regex.search(linea):
                continue
            if MARCADORES.search(linea):
                continue
            if linea.lstrip().startswith(("#", "//")):
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


def main() -> int:
    if "--historial" in sys.argv:
        return _escanear_historial()
    return _escanear_arbol()


if __name__ == "__main__":
    raise SystemExit(main())
