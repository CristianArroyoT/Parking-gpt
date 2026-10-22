"""Escáner de corrupción de texto (repo en español).

El modelo de lenguaje introduce con facilidad caracteres de otros
alfabetos (CJK, cirílico, coreano) en el texto en español. Este script
los detecta para poder repararlos ANTES de commitear.

El informe se escribe en un fichero UTF-8 (no en la consola) porque la
consola de Windows se come los acentos y los caracteres no latinos.

Uso:
    python tools/escanear_texto.py <fichero o carpeta> [...] [--salida ruta]
    python tools/escanear_texto.py --tracked

``--tracked`` escanea **todo lo versionado** por git (y sólo eso: ni
``node_modules``, ni ``dist``, ni ficheros generados). Es el modo que usa
el CI: lo que se va a publicar es exactamente lo versionado.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Rangos de alfabetos que no deben aparecer en un repo en español.
RANGOS_SOSPECHOSOS = {
    "CJK": "\u4e00-\u9fff\u3400-\u4dbf",
    "Kana": "\u3040-\u30ff",
    "Cirilico": "\u0400-\u04ff",
    "Coreano": "\uac00-\ud7af",
    "Arabe": "\u0600-\u06ff",
    "Hebreo": "\u0590-\u05ff",
    "Tamil": "\u0b80-\u0bff",
    "Reemplazo": "\ufffd",
}

# Monedas que no son las del proyecto (el euro).
MONEDAS_RARAS = re.compile("[\u00a3\u00a5\u20b9\u20bd]")

# NOTA: no se busca "palabras pegadas" (tipo "deoprecipitacion"). El
# patrón se dispara con cualquier palabra española normal ("devuelve",
# "conexiones", "desbloquear") y el ruido ahoga la señal. La señal
# fiable son los rangos Unicode de arriba.

EXTENSIONES = {".py", ".md", ".ts", ".vue", ".js", ".yml", ".yaml", ".txt", ".json", ".html", ".css"}


def escanear_fichero(ruta: Path) -> list[str]:
    problemas: list[str] = []
    try:
        texto = ruta.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{ruta}: el fichero NO es UTF-8 valido"]
    for linea_no, linea in enumerate(texto.splitlines(), start=1):
        for nombre, rango in RANGOS_SOSPECHOSOS.items():
            patron = re.compile(f"[{rango}]")
            for coincidencia in patron.finditer(linea):
                problemas.append(
                    f"{ruta}:{linea_no}: [{nombre}] {coincidencia.group(0)!r} "
                    f"-> {linea.strip()[:120]!r}"
                )
        for coincidencia in MONEDAS_RARAS.finditer(linea):
            problemas.append(
                f"{ruta}:{linea_no}: [Moneda] {coincidencia.group(0)!r} "
                f"-> {linea.strip()[:120]!r}"
            )
    return problemas


def recoger(rutas: list[Path]) -> list[Path]:
    ficheros: list[Path] = []
    for base in rutas:
        if base.is_file():
            ficheros.append(base)
            continue
        for fichero in sorted(base.rglob("*")):
            if (
                fichero.is_file()
                and fichero.suffix.lower() in EXTENSIONES
                and "node_modules" not in fichero.parts
                and ".git" not in fichero.parts
            ):
                ficheros.append(fichero)
    return ficheros


def _raiz_git() -> Path:
    """Raíz del repositorio git (o el directorio actual si no lo es)."""
    try:
        salida = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd()
    return Path(salida.stdout.strip() or ".")


def ficheros_versionados() -> list[Path]:
    """Ficheros que git tiene versionados, con extensión vigilada."""
    raiz = _raiz_git()
    try:
        salida = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True, text=True, check=True, cwd=str(raiz),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"no se pudo listar los ficheros versionados: {exc}") from exc
    ficheros = []
    for nombre in salida.stdout.split("\0"):
        if not nombre:
            continue
        ruta = raiz / nombre
        if ruta.suffix.lower() in EXTENSIONES:
            ficheros.append(ruta)
    return ficheros


def _autoprueba() -> int:
    """Comprueba que el escaner DETECTA lo que tiene que detectar.

    Una puerta que no se puede ver fallar no es una puerta. Aquí se le
    pasan ficheros de mentira con cada clase de corrupción (y ficheros
    limpios) y se comprueba que acierta en las dos direcciones.

    Importa especialmente el caso limpio: el escaner no debe disparar
    con el español normal con acentos, que es el 99 % del repositorio.
    """
    import tempfile

    casos: list[tuple[str, bytes, bool]] = [
        ("caracteres CJK", "valor = 'al que\u8be2 enlazarse'\n".encode("utf-8"), True),
        ("cirilico", "clave = '\u043f\u0430\u0440\u043e\u043b\u043e\u043b\u043e'\n".encode("utf-8"), True),
        ("coreano", "nombre = '\ud14c\uc2a4\ud2b8'\n".encode("utf-8"), True),
        ("moneda rara", "importe = '\u00a35'\n".encode("utf-8"), True),
        ("no es UTF-8", b"texto = '\xff\xfe' invalido\n", True),
        ("espanol con acentos", "devuelve = 'El veh\u00edculo sali\u00f3 a las 7'\n".encode("utf-8"), False),
        ("espanol normal", b"def ejecutar() -> None:\n    return None\n", False),
    ]
    fallos = 0
    with tempfile.TemporaryDirectory(prefix="solidapp-autoprueba-") as temporal:
        for nombre, contenido, debe_detectar in casos:
            ruta = Path(temporal) / f"{nombre.replace(' ', '_')}.py"
            ruta.write_bytes(contenido)
            problemas = escanear_fichero(ruta)
            detectado = bool(problemas)
            if detectado != debe_detectar:
                fallos += 1
                print(
                    f"  FALLO: {nombre} -> detectado={detectado} "
                    f"(se esperaba {debe_detectar})"
                )
            else:
                print(f"  OK: {nombre} -> {'detectado' if detectado else 'limpio'}")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el escaner detecta cada clase de corrupcion "
          "y no dispara con el espanol normal.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    salida = Path("tools/_informe_texto.txt")
    if "--salida" in args:
        i = args.index("--salida")
        salida = Path(args[i + 1])
        del args[i:i + 2]

    if "--autoprueba" in args:
        return _autoprueba()

    if "--tracked" in args:
        # Modo "lo que se va a publicar": todo lo versionado, y nada más.
        args.remove("--tracked")
        ficheros = ficheros_versionados()
        problemas: list[str] = []
        for fichero in ficheros:
            problemas.extend(escanear_fichero(fichero))
        lineas = [
            f"{len(problemas)} problema(s) en {len(ficheros)} fichero(s) versionados:"
        ]
        lineas.extend("  " + p for p in problemas)
        if not problemas:
            lineas.append("OK: no se detecta corrupcion de texto en lo versionado")
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text("\n".join(lineas), encoding="utf-8")
        print(f"Informe escrito en {salida} ({len(problemas)} problema(s))")
        return 1 if problemas else 0

    rutas = [Path(p) for p in args]
    if not rutas:
        print("Uso: python tools/escanear_texto.py <fichero o carpeta> [...]")
        print("     python tools/escanear_texto.py --tracked")
        return 2

    problemas: list[str] = []
    for fichero in recoger(rutas):
        problemas.extend(escanear_fichero(fichero))

    lineas = [f"{len(problemas)} problema(s) en {len(recoger(rutas))} fichero(s):"]
    lineas.extend("  " + p for p in problemas)
    if not problemas:
        lineas.append("OK: no se detecta corrupcion de texto")
    salida.write_text("\n".join(lineas), encoding="utf-8")
    print(f"Informe escrito en {salida} ({len(problemas)} problema(s))")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
