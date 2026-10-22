"""Comprueba que la QA visual recorre TODAS las pantallas del router.

POR QUÉ (2026-10-22): la QA visual recorre una lista de pantallas
escritas a mano (``PANTALLAS`` en ``frontend/scripts/qa_visual.py``) y
esa lista es una **copia** de las rutas del router. **Nada las
comparaba.**

El resultado era que seis rutas del router no se revisaban nunca: el
dashboard de admin, la lista de parkings, la de costes y las dos
pantallas de error (acceso denegado y no encontrada). Si cualquiera de
ellas se hubiera roto (contenido que no cabe, error de consola,
pantalla en blanco), la QA lo habría dado por bueno: el veredicto era
"21 pantallas sin incidencias" cuando de verdad se estaban revisando 21
de 27.

Y lo mismo hacia delante: si alguien añade una pantalla nueva al
router y se olvida de añadirla a la QA, la puerta nueva lo dice.

A propósito, este script **no** reutiliza el extractor de rutas de
``verificar_roles_frontend.py``: dos extractores independientes que se
vigilan mutuamente valen más que uno solo compartido (si los dos
comparten código, los dos pueden quedarse ciegos a la vez).

Uso:
    python tools/verificar_cobertura_frontend.py
    python tools/verificar_cobertura_frontend.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ROUTER = RAIZ / "frontend" / "src" / "router" / "index.ts"
QA = RAIZ / "frontend" / "scripts" / "qa_visual.py"

#: ``path: '/algo'`` dentro del array de rutas.
RE_PATH = re.compile(r"^\s*path:\s*'([^']+)'", re.MULTILINE)

#: Rutas del router que la QA visual NO recorre, con el motivo.
#:
#: No es una lista de "excepciones cómodas": cada entrada tiene que
#: decir POR QUÉ no se puede recorrer, y esa razón se documenta.
EXENCIONES: dict[str, str] = {
    "/": (
        "es una redireccion por rol (cada rol va a su dashboard), no una "
        "pantalla: no hay nada que capturar"
    ),
    "/calibrate/:parkingId/:cameraId": (
        "necesita el id de un parking y el de una cámara que existan de verdad "
        "(con su RTSP). Con ids inventados la pantalla se abriría sobre una "
        "cámara inexistente, que es un fallo de verdad y no de la pantalla: "
        "la QA daría un falso positivo."
    ),
}


def _rutas_del_router() -> list[str]:
    """Todas las rutas declaradas en el router, en orden."""
    texto = ROUTER.read_text(encoding="utf-8")
    return RE_PATH.findall(texto)


def _pantallas_de_la_qa() -> list[str]:
    """Las rutas que recorre la QA visual."""
    arbol = ast.parse(QA.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            destinos = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
            if "PANTALLAS" not in destinos or not isinstance(nodo.value, ast.List):
                continue
            rutas = []
            for entrada in nodo.value.elts:
                if isinstance(entrada, ast.Tuple) and len(entrada.elts) >= 2:
                    try:
                        rutas.append(ast.literal_eval(entrada.elts[1]))
                    except ValueError:
                        continue
            return rutas
    return []


def _sin_cubrir(rutas: list[str], pantallas: list[str]) -> list[str]:
    """Las rutas del router que la QA no recorre (y no están exentas)."""
    vistas = set(pantallas)
    rutas_visor = set(rutas)
    #: La ruta comodín ("no encontrada") se cubre si la QA visita
    #: deliberadamente alguna ruta que no existe en el router.
    hay_404 = any(p not in rutas_visor for p in pantallas)
    sin_cubrir = []
    for ruta in rutas:
        if ruta in EXENCIONES:
            continue
        if ruta in vistas:
            continue
        if "*" in ruta and hay_404:
            continue
        sin_cubrir.append(ruta)
    return sin_cubrir


def _huerfanas(rutas: list[str], pantallas: list[str]) -> list[str]:
    """Las rutas que recorre la QA y que no existen en el router.

    Una pantalla huerfana significa que la QA está comprobando algo que
    ya no existe (o que se ha escrito mal). La **única** excepción es
    la visita deliberada a una ruta inexistente, para comprobar la
    pantalla de "no encontrada": si el router tiene esa ruta comodín, se
    admite **una** visita así, y si hay más de una es que alguna ruta
    está mal escrita.
    """
    vistas = set(rutas)
    fuera = [p for p in pantallas if p not in vistas and "?" not in p]
    if not fuera:
        return []
    if not any("*" in r for r in rutas):
        # Sin ruta comodín, cualquier ruta fuera del router es un error.
        return fuera
    return fuera[1:] if len(fuera) > 1 else []


def _falta_el_404(rutas: list[str], pantallas: list[str]) -> bool:
    """¿El router tiene la pantalla de "no encontrada" y nadie la comprueba?

    El router declara una ruta comodín (``/:pathMatch(.*)*``). Si la QA
    no visita ninguna ruta inexistente, esa pantalla no se revisa nunca.
    """
    if not any("*" in r for r in rutas):
        return False
    vistas = set(rutas)
    return not any(p not in vistas for p in pantallas)


def _autoprueba() -> int:
    """Comprueba que la puerta sigue detectando una pantalla sin cubrir.

    Se monta el caso de mentira a mano: un router con una ruta que la QA
    no recorre. Si la puerta no lo ve, no es una puerta.
    """
    fallos = 0

    # 1. Una ruta que nadie recorre tiene que salir.
    rutas = ["/login", "/dashboard", "/admin/costs"]
    pantallas = ["/login", "/dashboard"]
    sin_cubrir = _sin_cubrir(rutas, pantallas)
    if "/admin/costs" not in sin_cubrir:
        print("  FALLO: una ruta sin recorrer no se ha detectado")
        fallos += 1
    else:
        print("  OK: una ruta que la QA no recorre se detecta")

    # 2. Y si la recorre, no debe salir.
    sin_cubrir = _sin_cubrir(rutas, rutas)
    if sin_cubrir:
        print(f"  FALLO: salen rutas que sí se recorren: {sin_cubrir}")
        fallos += 1
    else:
        print("  OK: una ruta que la QA recorre no se marca")

    # 3. La ruta comodín se cubre si la QA visita algo que no existe.
    con_404 = ["/login", "/ruta-que-no-existe"]
    sin_cubrir = _sin_cubrir(["/login", "/:pathMatch(.*)*"], con_404)
    if sin_cubrir:
        print(f"  FALLO: la ruta comodín no se reconoce como cubierta: {sin_cubrir}")
        fallos += 1
    else:
        print("  OK: la ruta comodín se cubre con la pantalla de 'no encontrada'")

    # 4. Y las exenciones se respetan (con su motivo).
    if "/calibrate/:parkingId/:cameraId" not in EXENCIONES:
        print("  FALLO: falta la exención de la ruta de calibración")
        fallos += 1
    else:
        print("  OK: la exención de la ruta de calibración está documentada")

    # 5. Y una pantalla huerfana se detecta (sin ruta comodín, cualquier
    #    ruta fuera del router es un error).
    huerfanas = _huerfanas(["/login"], ["/login", "/ruta-que-no-existe"])
    if "/ruta-que-no-existe" not in huerfanas:
        print("  FALLO: una pantalla huerfana no se ha detectado")
        fallos += 1
    else:
        print("  OK: una pantalla huerfana se detecta")

    # 6. Con ruta comodín, una visita fuera del router es la del 404, pero
    #    sólo puede haber una: si hay más, alguna ruta está mal escrita.
    huerfanas = _huerfanas(
        ["/login", "/:pathMatch(.*)*"],
        ["/login", "/ruta-que-no-existe", "/otra-que-no-existe"],
    )
    if not huerfanas:
        print("  FALLO: dos visitas fuera del router no se han marcado")
        fallos += 1
    else:
        print("  OK: más de una visita fuera del router se marca (posible errata)")

    # 7. Y si nadie comprueba la pantalla de "no encontrada", se avisa.
    if not _falta_el_404(["/login", "/:pathMatch(.*)*"], ["/login"]):
        print("  FALLO: la pantalla de 'no encontrada' sin comprobar no se detecta")
        fallos += 1
    else:
        print("  OK: la pantalla de 'no encontrada' sin comprobar se detecta")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de cobertura sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando pantallas sin cubrir")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    rutas = _rutas_del_router()
    pantallas = _pantallas_de_la_qa()
    print(f"rutas del router: {len(rutas)}")
    print(f"pantallas de la QA: {len(pantallas)}")

    sin_cubrir = _sin_cubrir(rutas, pantallas)
    huerfanas = _huerfanas(rutas, pantallas)
    falta_404 = _falta_el_404(rutas, pantallas)

    if sin_cubrir:
        print(f"\nPANTALLAS DEL ROUTER QUE LA QA NO RECORRE ({len(sin_cubrir)}):")
        for ruta in sin_cubrir:
            print(f"  - {ruta}")
            print(f"      (si no se puede recorrer, añadela a EXENCIONES en "
                  f"{Path(__file__).name} con el motivo)")
        return 1

    if huerfanas:
        print(f"\nLA QA RECORRE RUTAS QUE NO EXISTEN ({len(huerfanas)}):")
        for ruta in huerfanas:
            print(f"  - {ruta}")
        print("  (sólo se admite UNA visita fuera del router: la de la pantalla")
        print("   de 'no encontrada'. Si hay más, alguna ruta está mal escrita.)")
        return 1

    if falta_404:
        print("\nLA PANTALLA DE 'NO ENCONTRADA' NO SE COMPRUEBA NUNCA:")
        print("  El router declara una ruta comodín y la QA no visita ninguna")
        print("  ruta inexistente. Añade una pantalla con una ruta que no exista.")
        return 1

    print("\nOK: la QA visual recorre todas las pantallas del router.")
    if EXENCIONES:
        print(f"   (con {len(EXENCIONES)} excepcion(es) documentada(s): "
              f"{', '.join(EXENCIONES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
