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
    # Los endpoints de salud no viven en un router de la API: los define
    # ``create_app`` en ``app/main.py`` y van fuera del prefijo. La lista
    # vive en ``extraer_api`` para que no se duplique (duplicarla fue lo
    # que dejó el recuento del documento en 100 cuando ya eran 101).
    from extraer_api import RUTAS_FUERA_DE_ROUTER  # noqa: PLC0415

    reales.update(RUTAS_FUERA_DE_ROUTER)
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


def _comparar_con_openapi(
    extraidas: set[tuple[str, str]], openapi: set[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(rutas reales que el extractor NO vio, rutas del extractor que no existen).

    POR QUÉ (2026-10-22): hasta aquí, el verificador comparaba el
    documento contra el **extractor**, y el generador del documento usa el
    mismo extractor. Los dos salían del mismo código, así que una ruta que
    el extractor no viera **tampoco** aparecería en el documento y todo
    quadraría: verde sobre mentira.

    La tercera fuente es la **aplicación de verdad**: su OpenAPI. Si el
    extractor se deja una ruta, aquí se ve.
    """
    return sorted(openapi - extraidas), sorted(extraidas - openapi)


def _rutas_del_openapi() -> set[tuple[str, str]]:
    """Las rutas que la aplicación real expone (la verdad de referencia)."""
    from extraer_api import rutas_openapi  # noqa: PLC0415 — import tardío

    return rutas_openapi()


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

    # 3. Cambiar el RBAC ("Quién") de una ruta sin tocarla.
    #    Esto es lo que NO se detectaba: el juego de rutas era el mismo,
    #    pero el documento afirmaba "Público" para endpoints que exigen
    #    admin (pasó con los 9 endpoints de /plans, que declaran su
    #    dependencia con Annotated[..., Depends(require_role(...))]).
    generada = _seccion_generada()
    documentada = _seccion_del_documento(DOC)
    lineas = [
        x for x in documentada.splitlines() if x.startswith("| ") and "Público" in x
    ]
    if not lineas:
        print("FALLO: no hay ninguna fila 'Público' donde probar el cambio de RBAC")
        return 1
    fila = lineas[0]
    fila_mala = fila.replace("Público", "`require_role('admin')`")
    if fila_mala == fila:
        print("FALLO: no se ha podido alterar la fila de prueba")
        return 1
    documentada_mala = documentada.replace(fila, fila_mala, 1)
    if not _comparar_secciones(generada, documentada_mala):
        print("FALLO: cambiar el RBAC de una ruta no se ha detectado")
        return 1
    print("  OK: al cambiar el RBAC de una ruta se detecta")

    # 4. Que el extractor no se deje una ruta SIN que el documento lo note.
    #    Es el hueco que tapaba esta puerta: el documento y el extractor
    #    venían del mismo código, así que una ruta que el extractor no
    #    viera no aparecía en el documento y todo cuadraba. La tercera
    #    fuente es la aplicación real (su OpenAPI).
    #
    #    Aquí se comprueba con casos de mentira sobre la comparación, para
    #    que la autoprueba siga sin depender de la app instalada.
    openapi = {("GET", "/api/v1/lo-que-sea"), ("POST", "/api/v1/otra")}
    faltan, sobran_openapi = _comparar_con_openapi(set(), openapi)
    if len(faltan) != 2 or sobran_openapi:
        print(f"FALLO: una ruta que el extractor no ve no se ha detectado ({faltan})")
        return 1
    print("  OK: una ruta que el extractor no ve se detecta contra el OpenAPI")

    # Y al revés: una ruta que el extractor inventa.
    inventadas = {("GET", "/api/v1/inventada")}
    faltan, sobran_openapi = _comparar_con_openapi(inventadas, set())
    if not sobran_openapi:
        print("FALLO: una ruta inventada por el extractor no se ha detectado")
        return 1
    print("  OK: una ruta inventada por el extractor se detecta")

    print("Autoprueba correcta: el verificador detecta las cinco caras de la deriva.")
    return 0


def main() -> int:
    if "--autoprueba" in sys.argv:
        return _autoprueba()

    documentadas = rutas_documentadas(DOC)
    reales = rutas_del_codigo()

    # La verdad de referencia: las rutas que expone la aplicación REAL.
    # Sin esta comparación, el verificador sólo compararía el documento
    # contra el extractor, y los dos vienen del mismo código: una ruta que
    # el extractor no viera tampoco estaría en el documento y todo
    # quadraría (verde sobre mentira).
    openapi = _rutas_del_openapi()
    faltan_openapi, sobran_openapi = _comparar_con_openapi(reales, openapi)
    if faltan_openapi or sobran_openapi:
        print(f"\nEl EXTRACTOR no coincide con la aplicacion ({len(faltan_openapi)} "
              f"sin ver, {len(sobran_openapi)} de mas):")
        for metodo, ruta in faltan_openapi:
            print(f"  NO LA VE  {metodo:6} {ruta}")
        for metodo, ruta in sobran_openapi:
            print(f"  INVENTADA {metodo:6} {ruta}")
        print("\nEl documento se genera con este extractor, asi que el documento")
        print("tambien estara mal. Arregla el extractor y regenera:")
        print("    python tools/generar_seccion_api.py --escribir")
        return 1

    sin_doc, sobran = _comparar(documentadas, reales)

    print(f"rutas del codigo:    {len(reales)}")
    print(f"rutas del OpenAPI:   {len(openapi)} (la verdad de referencia)")
    print(f"rutas documentadas:  {len(documentadas)}")

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
