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
    """Rutas (método, ruta) que documenta el fichero, en su forma escrita.

    Las rutas del documento son relativas a ``/api/v1``, salvo
    ``/health`` (que va fuera del prefijo).
    """
    texto = doc.read_text(encoding="utf-8")
    encontradas: set[tuple[str, str]] = set()
    for metodo, ruta in RE_FILA.findall(texto):
        encontradas.add((metodo.upper(), ruta))
    return encontradas


def _forma_larga(metodo: str, ruta: str) -> tuple[str, str]:
    """La misma ruta escrita con el prefijo ``/api/v1`` delante."""
    if ruta.startswith(PREFIJO):
        return metodo, ruta
    return metodo, f"{PREFIJO}{ruta}"


def rutas_del_codigo() -> set[tuple[str, str]]:
    """Rutas que exponen los routers, leídos del código."""
    reales: set[tuple[str, str]] = set()
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, _quien, _modulo in extraer_de_modulo(fichero):
            reales.add((metodo, ruta))
    # El endpoint de salud no vive en un router de la API: lo define
    # ``create_app`` en ``app/main.py`` y va fuera del prefijo.
    reales.add(("GET", "/health"))
    return reales


def _comparar(documentadas: set[tuple[str, str]], reales: set[tuple[str, str]]):
    """(rutas del codigo sin documentar, rutas documentadas que no existen)."""
    documentadas_ambos = set(documentadas) | {
        _forma_larga(m, r) for m, r in documentadas
    }
    sin_doc = sorted(reales - documentadas_ambos)
    sobran = sorted(
        (m, r) for m, r in documentadas
        if (m, r) not in reales and _forma_larga(m, r) not in reales
    )
    return sin_doc, sobran


def _seccion_del_documento(doc: Path) -> str:
    """La sección 3 tal y como está en el documento."""
    texto = doc.read_text(encoding="utf-8")
    inicio = texto.index("## 3. Mapa de recursos y RBAC")
    fin = texto.index("## 4. Versionado y política de deprecación")
    return texto[inicio:fin].rstrip()


def _seccion_generada() -> str:
    """La sección 3 que se generaría hoy desde el código."""
    from generar_seccion_api import seccion  # noqa: PLC0415 — import tardío

    return seccion().rstrip()


def _comparar_secciones(generada: str, documentada: str, max_lineas: int = 12) -> list[str]:
    """Líneas en las que difieren las dos secciones."""
    lineas_gen = [linea.rstrip() for linea in generada.splitlines()]
    lineas_doc = [linea.rstrip() for linea in documentada.splitlines()]
    diferencias: list[str] = []
    for i in range(max(len(lineas_gen), len(lineas_doc))):
        a = lineas_gen[i] if i < len(lineas_gen) else "(falta)"
        b = lineas_doc[i] if i < len(lineas_doc) else "(falta)"
        if a != b:
            diferencias.append(f"  L{i + 1}: codigo={a!r}  documento={b!r}")
        if len(diferencias) >= max_lineas:
            break
    return diferencias


def _autoprueba() -> int:
    """Comprueba que el verificador DETECTA la deriva.

    Una puerta que no detecta nada no es una puerta: aquí se borra una
    ruta del documento y se añade otra que no existe, y se comprueba que
    el verificador las echa en las dos caras.
    """
    reales = rutas_del_codigo()
    documentadas = rutas_documentadas(DOC)

    sin_doc, sobran = _comparar(documentadas, reales)
    if sin_doc or sobran:
        print(f"FALLO: el documento real ya tiene deriva ({len(sin_doc)} sin documentar, "
              f"{len(sobran)} sobrantes)")
        return 1

    # 1. Quitar una ruta del documento.
    quitada = sorted(documentadas)[0]
    sin_ruta = {r for r in documentadas if r != quitada}
    sin_doc, sobran = _comparar(sin_ruta, reales)
    if not sin_doc:
        print("FALLO: quitar una ruta del documento no se ha detectado")
        return 1
    print(f"  OK: al quitar {quitada[0]} {quitada[1]} se detecta")

    # 2. Anadir una ruta que no existe.
    inventada = ("GET", "/no/existe")
    sin_doc, sobran = _comparar(documentadas | {inventada}, reales)
    if not sobran:
        print("FALLO: anadir una ruta inexistente no se ha detectado")
        return 1
    print(f"  OK: al anadir {inventada[0]} {inventada[1]} se detecta")

    print("Autoprueba correcta: el verificador detecta las dos caras de la deriva.")
    return 0


def main() -> int:
    if "--autoprueba" in sys.argv:
        return _autoprueba()

    documentadas = rutas_documentadas(DOC)
    reales = rutas_del_codigo()

    sin_doc, sobran = _comparar(documentadas, reales)

    print(f"rutas del codigo:    {len(reales)}")
    print(f"rutas documentadas: {len(documentadas)}")

    if sin_doc:
        print(f"\n{len(sin_doc)} ruta(s) DEL CODIGO SIN DOCUMENTAR:")
        for metodo, ruta in sin_doc:
            print(f"  {metodo:6} {ruta}")
    if sobran:
        print(f"\n{len(sobran)} ruta(s) DOCUMENTADAS QUE YA NO EXISTEN:")
        for metodo, ruta in sobran:
            print(f"  {metodo:6} {ruta}")

    # Ademas de las rutas, la seccion entera (incluida la columna
    # 'Quien' con el ambito de datos) tiene que coincidir con lo que
    # genera el codigo: si no, el documento esta desfasado aunque las
    # rutas coincidan.
    diferencias = _comparar_secciones(
        _seccion_generada(), _seccion_del_documento(DOC),
    )
    if diferencias:
        print(f"\nLa seccion 3 NO coincide con el codigo ({len(diferencias)}+ lineas):")
        for linea in diferencias:
            print(linea)
        print("\nPara arreglarlo: python tools/generar_seccion_api.py --escribir")
        return 1

    if not sin_doc and not sobran:
        print("\nEl inventario coincide con el codigo (rutas y columna 'Quien').")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
