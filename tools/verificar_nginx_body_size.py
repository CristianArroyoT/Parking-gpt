"""Puerta: el servidor de producción admite los cuerpos que el backend acepta.

POR QUÉ (T-60, 2026-10-22): el servidor de producción (nginx) tiene un
límite de tamaño de petición y, **si no se dice nada, ese límite es de
1 MB**. El backend, en cambio, acepta hasta ``incident_attachment_max_files``
ficheros de ``incident_attachment_max_bytes`` cada uno (10 MB x 3 = 30 MB
por defecto) y el frontend acepta fotos de 10 MB.

Medido contra la imagen de producción: una petición de 2 MB devolvía
**413 Request Entity Too Large** con un HTML de nginx, y el backend **nunca
llegaba a verla**. En desarrollo (Vite) sí pasaba. O sea: en producción,
subir una foto de móvil a un incidente fallaba siempre, y con un mensaje
que no explicaba el motivo.

POR QUÉ una puerta y no un comentario: el valor de nginx y el del backend
están en ficheros distintos, y cada uno puede cambiar por su cuenta. Sin
una puerta que los compare, volverían a desincronizarse en silencio (el
tope del backend subiría a 20 MB y nadie se enteraría de que nginx
sigue en 1 MB).

Lo que exige:
    ``client_max_body_size`` de nginx >= ``max_bytes * max_files`` del
    backend.

Uso:
    python tools/verificar_nginx_body_size.py
    python tools/verificar_nginx_body_size.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

CONFIG_BACKEND = RAIZ / "backend" / "app" / "core" / "config.py"
PLANTILLA_NGINX = RAIZ / "frontend" / "nginx" / "templates" / "default.conf.template"

#: ``client_max_body_size 32m;`` (nginx: k = 1024, m = 1024^2, g = 1024^3).
RE_DIRECTIVA = re.compile(
    r"client_max_body_size\s+(\d+)\s*([kmg]?)\s*;", re.IGNORECASE
)

_MULTIPLICADORES = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _evaluar(nodo: ast.AST) -> int:
    """Evalúa una expresión entera constante (sin ``eval``).

    Los defaults del backend son cosas como ``10 * 1024 * 1024``.
    """
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, int):
        return int(nodo.value)
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Mult):
        return _evaluar(nodo.left) * _evaluar(nodo.right)
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        return _evaluar(nodo.left) + _evaluar(nodo.right)
    raise ValueError(f"no se puede evaluar esta expresion: {ast.dump(nodo)}")


def _default_de_campo(arbol: ast.Module, campo: str) -> int:
    """Saca el ``default=`` de un ``campo: int = Field(default=...)``."""
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.AnnAssign):
            continue
        objetivo = nodo.target
        if not isinstance(objetivo, ast.Name) or objetivo.id != campo:
            continue
        valor = nodo.value
        if not isinstance(valor, ast.Call):
            raise ValueError(f"el campo {campo} no se declara con Field(...)")
        for keyword in valor.keywords:
            if keyword.arg == "default":
                return _evaluar(keyword.value)
        raise ValueError(f"el campo {campo} no tiene default")
    raise ValueError(f"no se encuentra el campo {campo}")


def leer_tope_backend(ruta: Path = CONFIG_BACKEND) -> tuple[int, int]:
    """Devuelve ``(max_bytes_por_fichero, max_ficheros)`` del backend."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return (
        _default_de_campo(arbol, "incident_attachment_max_bytes"),
        _default_de_campo(arbol, "incident_attachment_max_files"),
    )


def leer_limite_nginx(ruta: Path = PLANTILLA_NGINX) -> int | None:
    """Devuelve el límite de nginx en bytes, o ``None`` si no está puesto.

    ``None`` es **peor** que un valor pequeño: sin la directiva, nginx usa
    su default (1 MB) y nadie lo ve en el fichero.
    """
    texto = ruta.read_text(encoding="utf-8")
    encontrados = RE_DIRECTIVA.findall(texto)
    if not encontrados:
        return None
    # Si hay varias, manda la MENOR: el cliente queyosabe el menor.
    limites = [
        int(cantidad) * _MULTIPLICADORES[unidad.lower()]
        for cantidad, unidad in encontrados
    ]
    return min(limites)


def comparar(limite_nginx: int | None, max_bytes: int, max_files: int) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []
    tope_backend = max_bytes * max_files
    if limite_nginx is None:
        problemas.append(
            "la plantilla de nginx no pone `client_max_body_size`: nginx usa su "
            f"default (1 MB) y el backend acepta hasta {tope_backend} bytes "
            f"({max_files} ficheros x {max_bytes} bytes). En produccion, "
            "subir una foto de mas de 1 MB falla con un 413 de nginx."
        )
        return problemas
    if limite_nginx < tope_backend:
        problemas.append(
            f"nginx acepta {limite_nginx} bytes por peticion y el backend "
            f"acepta {tope_backend} ({max_files} ficheros x {max_bytes} bytes): "
            f"faltan {tope_backend - limite_nginx} bytes. En produccion, la "
            "subida de fotos de incidente falla con un 413 de nginx."
        )
    return problemas


def _escribir(base: Path, nombre: str, texto: str) -> Path:
    ruta = base / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del limite de cuerpo:")
    fallos = 0

    casos = [
        (
            "nginx con el default de 1 MB y el backend pidiendo 30 MB",
            "1m", 10 * 1024 * 1024, 3, False,
        ),
        (
            "nginx sin la directiva (usa su default de 1 MB)",
            None, 10 * 1024 * 1024, 3, False,
        ),
        (
            "nginx con 32 MB y el backend pidiendo 30 MB",
            "32m", 10 * 1024 * 1024, 3, True,
        ),
        (
            "nginx con exactamente 30 MB (el tope del backend)",
            "30m", 10 * 1024 * 1024, 3, True,
        ),
        (
            "nginx con 60 MB y el backend pidiendo 60 MB",
            "60m", 20 * 1024 * 1024, 3, True,
        ),
        (
            "nginx con 60 MB y el backend pidiendo 90 MB",
            "60m", 30 * 1024 * 1024, 3, False,
        ),
    ]

    with tempfile.TemporaryDirectory() as temporal:
        base = Path(temporal)
        for nombre, directiva, max_bytes, max_files, debe_pasar in casos:
            if directiva is None:
                plantilla = "server {\n    listen 80;\n}\n"
            else:
                plantilla = (
                    "server {\n    listen 80;\n"
                    f"    client_max_body_size {directiva};\n}}\n"
                )
            ruta = _escribir(base, "nginx.conf", plantilla)
            limite = leer_limite_nginx(ruta)
            problemas = comparar(limite, max_bytes, max_files)
            paso = not problemas
            if paso != debe_pasar:
                fallos += 1
                print(f"  FALLO {nombre}: la puerta {'paso' if paso else 'fallo'}")
                for p in problemas:
                    print(f"          {p}")
            else:
                print(f"  OK    {nombre}: la puerta {'pasa' if paso else 'falla'}")

    if fallos:
        print(f"AUTOPRUEBA FALLIDA ({fallos} problema(s))")
        return 1
    print("AUTOPRUEBA CORRECTA: la puerta puede fallar y puede pasar")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba que nginx admite los cuerpos que el backend acepta."
    )
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (casos de mentira escritos a mano)",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return autoprueba()

    try:
        max_bytes, max_files = leer_tope_backend()
    except (OSError, ValueError, SyntaxError) as error:
        print(f"  FALLO  no se puede leer el tope del backend: {error}")
        return 1
    try:
        limite = leer_limite_nginx()
    except OSError as error:
        print(f"  FALLO  no se puede leer la plantilla de nginx: {error}")
        return 1

    problemas = comparar(limite, max_bytes, max_files)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    print(
        f"OK: nginx admite {limite} bytes por peticion y el backend acepta "
        f"{max_bytes * max_files} ({max_files} x {max_bytes})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
