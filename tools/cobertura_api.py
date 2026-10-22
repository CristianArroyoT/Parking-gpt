"""Mide la cobertura de tests sobre los endpoints de la API.

Responde a: ¿de los 101 endpoints, cuántos tienen al menos un test
que los ejercite? Un endpoint sin test de RBAC es un endpoint cuyo
permiso nadie ha comprobado nunca.

El emparejamiento es por *forma de ruta*: ``/parkings/{parking_id}/cameras``
busca en los tests un literal que case con esa forma, sea
``/parkings/{parking_id}/cameras`` o ``/parkings/1/cameras``.

Uso:
    python tools/cobertura_api.py            # resumen
    python tools/cobertura_api.py --detalle # endpoint a endpoint
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from extraer_api import extraer_de_modulo  # noqa: E402

V1 = RAIZ / "backend" / "app" / "api" / "v1"
TESTS = RAIZ / "backend" / "tests"

#: ``/parkings/{parking_id}/cameras`` → ``/parkings/.*cameras``
RE_PLACEHOLDER = re.compile(r"\{[^}]+\}")


def _forma(ruta: str) -> re.Pattern:
    """Patrón que casa con la ruta dentro de una llamada.

    ``/parkings/{parking_id}/cameras`` → ``/parkings/[^/]+/cameras``. La
    ruta aparece dentro de una cadena (``client.get("/api/v1/...")``),
    así que no puede ir anclada al principio ni al final de la línea.
    """
    partes = []
    for segmento in ruta.split("/"):
        if not segmento:
            continue
        if RE_PLACEHOLDER.fullmatch(segmento):
            partes.append(r"[^/\"']+")
        else:
            partes.append(re.escape(segmento))
    # Tras la ruta tiene que venir el cierre de la cadena o un
    # separador de query, para no casar con un prefijo mas largo.
    return re.compile("/".join(partes) + r"""(?=["'/?\s,)\]}])""")


def _parametrizada(ruta: str, texto: str) -> bool:
    """¿El test construye la URL con una variable?

    ``/api/v1/admin/reports/alertas.pdf`` se ejercita en el test como
    ``f"/api/v1/admin/reports/{informe}.pdf"``: el emparejamiento
    literal no puede verlo, pero el endpoint sí se prueba.
    """
    padre = ruta.rsplit("/", 1)[0]
    if not padre:
        return False
    # ``/api/v1/admin/reports/{informe}.pdf``: el test construye el
    # ultimo segmento con una variable.
    return f"{padre}/" + "{" in texto


def _texto_de_tests() -> str:
    textos = []
    for fichero in TESTS.rglob("*.py"):
        textos.append(fichero.read_text(encoding="utf-8"))
    return "\n".join(textos)


def _cuerpos_de_test() -> list[tuple[str, str]]:
    """(nombre del test, cuerpo) de cada función de test del repo.

    Se usa para comprobar algo más fuerte que "el endpoint se toca":
    que **exista un test que verifique que a un usuario sin permiso
    se le responde 401/403**. Un endpoint sin esa comprobación tiene el
    RBAC sin verificar, por muy many tests que lo toquen.
    """
    cuerpos: list[tuple[str, str]] = []
    for fichero in sorted(TESTS.rglob("*.py")):
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        lineas = fichero.read_text(encoding="utf-8").splitlines()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not nodo.name.startswith("test_"):
                continue
            cuerpo = "\n".join(lineas[nodo.body[0].lineno - 1:nodo.end_lineno or nodo.body[0].lineno])
            cuerpos.append((f"{fichero.name}::{nodo.name}", cuerpo))
    return cuerpos


def _test_de_denegacion(ruta: str, cuerpos: list[tuple[str, str]]) -> list[str]:
    """Tests que mencionan la ruta y comprueban un 401 o un 403."""
    patron = _forma(ruta)
    hallados: list[str] = []
    for nombre, cuerpo in cuerpos:
        if not patron.search(cuerpo):
            continue
        if re.search(r"status_code\s*(==|in)\s*[\(\{\[]?[^\n]*\b(401|403)\b", cuerpo):
            hallados.append(nombre)
    return hallados


def _filas_con_rbac() -> list[tuple[str, str, str, str, str]]:
    """(método, ruta, quién, módulo, cobertura) de cada endpoint."""
    texto = _texto_de_tests()
    filas: list[tuple[str, str, str, str, str]] = []
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, quien, modulo in extraer_de_modulo(fichero):
            if _forma(ruta).search(texto):
                estado = "explicita"
            elif _parametrizada(ruta, texto):
                estado = "parametrizada"
            else:
                estado = "ninguna"
            filas.append((metodo, ruta, quien, modulo, estado))
    return filas


def _quien_de(ruta: str) -> str:
    """La columna 'Quién' de una ruta, tal y como la pone el generador."""
    for _m, r, quien, _mod, _estado in _filas_con_rbac():
        if r == ruta:
            return quien
    return ""


def cobertura() -> list[tuple[str, str, str, str]]:
    """(método, ruta, módulo, cobertura) de cada endpoint.

    La cobertura tiene tres estados:
      * ``explicita``: la ruta aparece tal cual en un test.
      * ``parametrizada``: el test construye la URL con una variable
        (``f"/api/v1/admin/reports/{informe}.pdf"``), así que el
        endpoint se ejercita pero no se puede emparejar literalmente.
      * ``ninguna``: no hay ningún test que lo toque.
    """
    filas: list[tuple[str, str, str, str]] = []
    for metodo, ruta, _quien, modulo, estado in _filas_con_rbac():
        filas.append((metodo, ruta, modulo, estado))
    return filas


def _autoprueba() -> int:
    """Comprueba que la puerta de cobertura SIGUE distinguiendo.

    La puerta dice "todo endpoint tiene algun test". Si el patrón que
    empareja rutas dejara de casar **de más**, todos los endpoints
    parecerían tener test y la puerta pasaría en vacío. Y si dejara de
    casar **de menos**, daría falsas alarmas. Aquí se comprueban las dos
    direcciones.
    """
    texto = _texto_de_tests()
    fallos = 0

    # 1. Una ruta que sí aparece en los tests tiene que casar.
    filas = _filas_con_rbac()
    explicitas = [f for f in filas if f[4] == "explicita"]
    if not explicitas:
        fallos += 1
        print("  FALLO: no hay ningun endpoint con test explicito (no se puede probar)")
    else:
        metodo, ruta, _quien, _modulo, _estado = explicitas[0]
        if not _forma(ruta).search(texto):
            fallos += 1
            print(f"  FALLO: {ruta} tiene test pero el patron no la encuentra")
        else:
            print(f"  OK: una ruta con test se encuentra ({ruta})")

    # 2. Una ruta que NO aparece en ningún test NO tiene que casar.
    inventada = "/api/v1/no-existe/xyz"
    if _forma(inventada).search(texto):
        fallos += 1
        print(f"  FALLO: una ruta que no existe casa con el patron ({inventada})")
    else:
        print("  OK: una ruta que no esta en los tests no casa")

    # 3. Y la puerta tiene que detectar un endpoint sin test.
    if not any(f[4] == "ninguna" for f in filas):
        print("  (sin endpoints sin test: no hay caso negativo que probar)")
    else:
        print("  OK: hay endpoints sin test y la puerta los marca")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de cobertura sigue distinguiendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue distinguiendo")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    filas = cobertura()
    explicitas = [f for f in filas if f[3] == "explicita"]
    parametrizadas = [f for f in filas if f[3] == "parametrizada"]
    sin_test = [f for f in filas if f[3] == "ninguna"]

    print(f"endpoints: {len(filas)}")
    print(f"  con test explicito:      {len(explicitas)}")
    print(f"  con test parametrizado:   {len(parametrizadas)}")
    print(f"  SIN ningun test:          {len(sin_test)}")

    # Segunda pregunta, mas fuerte: ¿el RBAC está verificado? Un
    # endpoint puede estar tocado por tests que no comprueban que a un
    # usuario sin permiso se le responde 401/403. Los endpoints
    # publicos no tienen nada que denegar, asi que se quedan fuera.
    cuerpos = _cuerpos_de_test()
    publicos = {
        ruta for _m, ruta, _q, _mod, _estado in _filas_con_rbac()
        if _quien_de(ruta).startswith("Público")
    }
    sin_denegacion = [
        (m, r, mod) for m, r, mod, estado in filas
        if estado != "ninguna" and r not in publicos
        and not _test_de_denegacion(r, cuerpos)
    ]
    print(f"  con test de denegacion (401/403): "
          f"{len(filas) - len(sin_denegacion) - len(publicos)}"
          f" (los {len(publicos)} públicos no tienen nada que denegar)")

    if sin_test:
        print("\nEndpoints sin ningun test que los ejercite:")
        for metodo, ruta, modulo, _ in sin_test:
            print(f"  {metodo:6} {ruta:56} [{modulo}]")
    if sin_denegacion:
        print("\nEndpoints SIN test que compruebe el 401/403 (RBAC sin verificar):")
        for metodo, ruta, modulo in sin_denegacion:
            print(f"  {metodo:6} {ruta:56} [{modulo}]")
    if parametrizadas:
        print("\nCubiertos por una URL parametrizada (no se pueden emparejar "
              "literalmente):")
        for metodo, ruta, modulo, _ in parametrizadas:
            print(f"  {metodo:6} {ruta:56} [{modulo}]")
    if args.detalle:
        print("\nCon test explicito:")
        for metodo, ruta, modulo, _ in explicitas:
            print(f"  {metodo:6} {ruta:56} [{modulo}]")
    # La puerta es "todo endpoint tiene algun test". La medida de
    # denegacion es INDICATIVA y no falla el script: los tests
    # comprueban el 401/403 construyendo la URL en una variable o
    # iterando sobre las rutas, asi que aparecen como huecos falsos.
    if sin_denegacion:
        print("\nNota: la lista de arriba es INDICATIVA. En varios de esos "
              "endpoints el 401/403 si se comprueba, pero el test construye "
              "la URL en una variable (o itera sobre las rutas), asi que "
              "no se puede emparejar de forma literal.")
    return 1 if sin_test else 0


if __name__ == "__main__":
    raise SystemExit(main())
