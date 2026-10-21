"""Mide la cobertura de tests sobre los endpoints de la API.

Responde a: ¿de los 100 endpoints, cuántos tienen al menos un test
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


def cobertura() -> list[tuple[str, str, str, str]]:
    """(método, ruta, módulo, cobertura) de cada endpoint.

    La cobertura tiene tres estados:
      * ``explicita``: la ruta aparece tal cual en un test.
      * ``parametrizada``: el test construye la URL con una variable
        (``f"/api/v1/admin/reports/{informe}.pdf"``), así que el
        endpoint se ejercita pero no se puede emparejar literalmente.
      * ``ninguna``: no hay ningún test que lo toque.
    """
    texto = _texto_de_tests()
    filas: list[tuple[str, str, str, str]] = []
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, _quien, modulo in extraer_de_modulo(fichero):
            if _forma(ruta).search(texto):
                estado = "explicita"
            elif _parametrizada(ruta, texto):
                estado = "parametrizada"
            else:
                estado = "ninguna"
            filas.append((metodo, ruta, modulo, estado))
    return filas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    args = ap.parse_args()

    filas = cobertura()
    explicitas = [f for f in filas if f[3] == "explicita"]
    parametrizadas = [f for f in filas if f[3] == "parametrizada"]
    sin_test = [f for f in filas if f[3] == "ninguna"]

    print(f"endpoints: {len(filas)}")
    print(f"  con test explicito:      {len(explicitas)}")
    print(f"  con test parametrizado:   {len(parametrizadas)}")
    print(f"  SIN ningun test:          {len(sin_test)}")

    if sin_test:
        print("\nEndpoints sin ningun test que los ejercite:")
        for metodo, ruta, modulo, _ in sin_test:
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
    return 1 if sin_test else 0


if __name__ == "__main__":
    raise SystemExit(main())
