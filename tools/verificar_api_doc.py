"""Comprueba que ``docs/API-INTERNAL.md`` sigue contando la historia.

Un inventario de API se queda viejo en cuanto se toca el contrato: un
endpoint nuevo que no se documenta, o uno documentado que ya no existe.
Este script compara las rutas **del código** (que a su vez se validan
contra el OpenAPI real) con las del documento y dice qué falta y qué
sobra.

Uso:
    python tools/verificar_api_doc.py     # sale con 1 si hay deriva
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from extraer_api import extraer_de_modulo  # noqa: E402

V1 = RAIZ / "backend" / "app" / "api" / "v1"
DOC = RAIZ / "docs" / "API-INTERNAL.md"
PREFIJO = "/api/v1"

#: Fila de tabla del documento: | GET | `/parkings` | Quién |
RE_FILA = re.compile(
    r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|",
    re.IGNORECASE | re.MULTILINE,
)


def rutas_documentadas(doc: Path) -> set[tuple[str, str]]:
    """Rutas (método, ruta) que documenta el fichero."""
    texto = doc.read_text(encoding="utf-8")
    encontradas: set[tuple[str, str]] = set()
    for metodo, ruta in RE_FILA.findall(texto):
        m = metodo.upper()
        # Las rutas del documento son relativas a /api/v1.
        r = ruta if ruta.startswith(PREFIJO) else f"{PREFIJO}{ruta}"
        encontradas.add((m, r))
    return encontradas


def rutas_del_codigo() -> set[tuple[str, str]]:
    """Rutas que exponen los routers, leídos del código."""
    reales: set[tuple[str, str]] = set()
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, _quien, _modulo in extraer_de_modulo(fichero):
            reales.add((metodo, ruta))
    return reales


def main() -> int:
    documentadas = rutas_documentadas(DOC)
    reales = rutas_del_codigo()

    sin_doc = reales - documentadas
    sobran = documentadas - reales

    print(f"rutas del codigo:    {len(reales)}")
    print(f"rutas documentadas: {len(documentadas)}")

    if sin_doc:
        print(f"\n{len(sin_doc)} ruta(s) DEL CODIGO SIN DOCUMENTAR:")
        for metodo, ruta in sorted(sin_doc):
            print(f"  {metodo:6} {ruta}")
    if sobran:
        print(f"\n{len(sobran)} ruta(s) DOCUMENTADAS QUE YA NO EXISTEN:")
        for metodo, ruta in sorted(sobran):
            print(f"  {metodo:6} {ruta}")
    if not sin_doc and not sobran:
        print("\nEl inventario coincide con el codigo.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
