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
#: OJO: los directorios se buscan con ``(^|/)`` para que ALSO estén
#: exentos en la raíz del repo ("tests/test_app.py"), no sólo anidados
#: ("backend/tests/test_app.py").
EXENTOS = re.compile(
    r"(\.env\.example|(^|/)tests?/|(^|/)seed|conftest\.py|\.example|\.sample|"
    r"(^|/)docs/|/locust/|\.md$|__init__\.py)",
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


def _secreto_en_linea(linea: str, ruta: str = "") -> str | None:
    """El nombre del patrón que casa en esta línea, o ``None`` si no es un secreto.

    Extraído como función pura para poder **probarlo** (ver
    ``--autoprueba``): una puerta que no se puede ver fallar no es una
    puerta.
    """
    if ruta and EXENTOS.search(ruta):
        return None
    if MARCADORES.search(linea):
        return None
    # Una linea que sólo habla de como NO hacer las cosas no es un secreto.
    if linea.lstrip().startswith(("#", "//")):
        return None
    for nombre, patron in PATRONES:
        if re.search(patron, linea):
            return nombre
    return None


def _escanear_arbol() -> int:
    hallazgos: list[str] = []
    for nombre, patron in PATRONES:
        for linea in _git_grep(patron):
            ruta = linea.split(":", 1)[0] if ":" in linea else ""
            if _secreto_en_linea(linea, ruta) != nombre:
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
            if _secreto_en_linea(linea) != nombre:
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


def _autoprueba() -> int:
    """Comprueba que el escaner DETECTA los secretos y NO dispara con los de mentira.

    Una puerta que no se puede ver fallar no es una puerta. Aquí se le
    pasan líneas de mentira y se comprueba que acierta en las dos
    direcciones. Importan especialmente los casos "no es un secreto": un
    escaner que marcara todo dejaría de servir para nada.
    """
    # OJO: los secretos de mentira se **construyen** en tiempo de
    # ejecución, no se escriben literales. Si estaban literales en este
    # fichero, el propio escaner los encontraría (y con razón: el
    # repositorio es público y un token real en un literal es una
    # credencial filtrada).
    token_github = "ghp_" + "a1b2c3d4e5" * 3 + "fghij"
    # AKIA + 16 caracteres (los que exige el patrón).
    clave_aws = "AKIA" + "ABCDEFGHIJKLMNOP"
    pem = "-----BEGIN RSA PRIVATE KEY" + "-----"
    jwt = "JWT" + "_SECRET = " + '"' + "s3cr3t" + "-de-verdad-1234567890" + '"'
    dsn = "postgresql://" + "usuario:claveReal123" + "@db:5432/app"

    casos: list[tuple[str, str, str, bool]] = [
        ("token de GitHub", "app/api.py", f'TOKEN = "{token_github}"', True),
        ("clave de AWS", "app/api.py", f'AWS = "{clave_aws}"', True),
        ("clave privada PEM", "app/keys.py", pem, True),
        ("JWT con valor real", "app/config.py", jwt, True),
        ("cadena de conexion", "app/db.py", f'DSN = "{dsn}"', True),
        ("valor de ejemplo", "app/config.py", 'JWT_SECRET = "change-me-in-production"', False),
        ("fichero de ejemplo", ".env.example", 'SECRET_KEY = "clave-de-ejemplo-larguísima"', False),
        ("fichero de pruebas", "backend/tests/test_app.py", f'TOKEN = "{token_github}"', False),
        ("documentacion", "docs/secreto.md", f'TOKEN = "{token_github}"', False),
        ("comentario", "app/api.py", f'# TOKEN = "{token_github}"', False),
        ("linea limpia", "app/api.py", "def ejecutar() -> None:\n    return None", False),
    ]
    fallos = 0
    for nombre, ruta, linea, debe_detectar in casos:
        detectado = _secreto_en_linea(linea, ruta) is not None
        if detectado != debe_detectar:
            fallos += 1
            print(
                f"  FALLO: {nombre} (en {ruta}) -> detectado={detectado} "
                f"(se esperaba {debe_detectar})"
            )
        else:
            print(f"  OK: {nombre} (en {ruta}) -> {'detectado' if detectado else 'limpio'}")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el escaner detecta los secretos y no dispara "
          "con los valores de ejemplo ni con los ficheros exentos.")
    return 0


def main() -> int:
    if "--autoprueba" in sys.argv:
        return _autoprueba()
    if "--historial" in sys.argv:
        return _escanear_historial()
    return _escanear_arbol()


if __name__ == "__main__":
    raise SystemExit(main())
