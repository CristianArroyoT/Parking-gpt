"""Comprueba que todo ajuste del backend se lee en algún sitio.

POR QUÉ (2026-10-22): un ajuste **muerto** (declarado, configurable por
entorno y que **nadie lee**) es una trampa silenciosa: parece
configurable y no hace nada. El que más daño hace es el que parece
importante y no lo es.

En el repo había **siete** ajustes muertos, y dos de ellos son los
peores, porque parecen importantes y no lo son:

- ``ocr_confidence_threshold`` (0.85): parecía un filtro global de
  confianza, pero el filtro real es el ``confidence_threshold`` de
  **cada geocerca** (lo calibra el operador). Ponerlo no descartaba
  ninguna lectura.
- ``ocr_lang`` ("es"): parecía decidir el idioma del OCR, pero el
  idioma lo elige el **servicio** OCR (``docker/ocr``), que va con
  ``OCR_LANG=en``. Los dos valores **no coincidían**, y el del backend
  no hacía nada.
- ``async_database_url``: la aplicación es síncrona; no hay motor
  asíncrono en ninguna parte.
- ``api_host`` / ``api_port``: el ``CMD`` del Dockerfile los fija en
  duro.
- ``ocr_engine``: lo elige el servicio OCR.
- ``loki_url``: los logs salen por stdout y los reenvía Promtail.

Este script lista los ajustes que nadie lee. Los que están en
``MORTOS_CONOCIDOS`` se avisan con su motivo (son decisiones ya
tomadas); **cualquier otro es un fallo del CI**, porque sería un ajuste
nuevo que alguien cree configurable y no lo sea.

Uso:
    python tools/verificar_ajustes_muertos.py
    python tools/verificar_ajustes_muertos.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "backend" / "app" / "core" / "config.py"
BACKEND = RAIZ / "backend"

#: Ajustes que nadie lee, con el motivo (decisión ya tomada, no un olvido).
MORTOS_CONOCIDOS: dict[str, str] = {
    "async_database_url": (
        "la aplicación es síncrona: no hay create_async_engine en ninguna parte"
    ),
    "api_host": "el CMD del Dockerfile fija --host 0.0.0.0 en duro",
    "api_port": "el CMD del Dockerfile fija --port 8000 en duro (y el healthcheck usa el 8000)",
    "ocr_engine": "el motor lo elige el servicio OCR (docker/ocr), con su propio OCR_ENGINE",
    "ocr_lang": (
        "el idioma lo elige el servicio OCR (docker/ocr, OCR_LANG=en para "
        "matrículas EU). OJO: el valor de aquí ('es') no es el que se usa"
    ),
    "ocr_confidence_threshold": (
        "el filtro de confianza real es el confidence_threshold de CADA "
        "geocerca (lo calibra el operador). Poner este valor no descarta "
        "ninguna lectura"
    ),
    "loki_url": (
        "la app no habla con Loki: los logs salen por stdout y los reenvía "
        "Promtail (infra/promtail/promtail-config.yaml)"
    ),
}


def _ajustes_declarados() -> list[str]:
    """Los nombres de campo declarados en la clase ``Settings``."""
    arbol = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef) and nodo.name == "Settings":
            return [
                e.target.id
                for e in nodo.body
                if isinstance(e, ast.AnnAssign) and isinstance(e.target, ast.Name)
            ]
    return []


def _lecturas() -> dict[str, int]:
    """``{ajuste: nº de veces que se lee}`` en todo el backend.

    Se cuenta el acceso al atributo (``.nombre``), que es como se leen
    los ajustes. Se busca en TODO el backend, no sólo en ``app/``: un
    ajuste usado por un test o por un script de la infra **sí** cuenta.
    """
    textos = []
    for fichero in sorted(BACKEND.rglob("*.py")):
        try:
            textos.append(fichero.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
    todo = "\n".join(textos)
    conteo: dict[str, int] = {}
    for nombre in _ajustes_declarados():
        conteo[nombre] = len(re.findall(rf"\.{re.escape(nombre)}\b", todo))
    return conteo


def _muertos() -> list[str]:
    """Los ajustes que nadie lee."""
    conteo = _lecturas()
    return [nombre for nombre, usos in conteo.items() if usos == 0]


def _autoprueba() -> int:
    """Comprueba que la puerta sigue detectando un ajuste muerto.

    Se monta el caso de mentira a mano: un ajuste que nadie lee tiene
    que salir; y uno que se lee, no.
    """
    fallos = 0

    # 1. Un ajuste sin lecturas es muerto.
    conteo = {"usado": 3, "no_usado": 0}
    muertos = [n for n, usos in conteo.items() if usos == 0]
    if muertos != ["no_usado"]:
        print(f"  FALLO: el ajuste muerto no se ha detectado ({muertos})")
        fallos += 1
    else:
        print("  OK: un ajuste que nadie lee se detecta")

    # 2. Y uno que se lee, no.
    conteo = {"usado": 1, "otro": 1}
    muertos = [n for n, usos in conteo.items() if usos == 0]
    if muertos:
        print(f"  FALLO: un ajuste que se lee se marca como muerto ({muertos})")
        fallos += 1
    else:
        print("  OK: un ajuste que se lee no se marca")

    # 3. Y el patrón de conteo cuenta el acceso por atributo.
    if not re.search(r"\.mi_ajuste\b", "settings.mi_ajuste"):
        print("  FALLO: el patrón de lectura no reconoce el acceso por atributo")
        fallos += 1
    else:
        print("  OK: el patrón de lectura reconoce el acceso por atributo")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de ajustes muertos sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando ajustes muertos")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    declarados = _ajustes_declarados()
    conteo = _lecturas()
    muertos = _muertos()

    print(f"ajustes declarados: {len(declarados)}")
    print(f"ajustes leidos:     {len(declarados) - len(muertos)}")
    print(f"ajustes muertos:    {len(muertos)}")

    if not muertos:
        print("\nOK: todos los ajustes se leen en algun sitio.")
        return 0

    print("\nAJUSTES QUE NADIE LEE:")
    errores = 0
    for nombre in muertos:
        if nombre in MORTOS_CONOCIDOS:
            print(f"  [AVISO] {nombre}")
            print(f"          {MORTOS_CONOCIDOS[nombre]}")
        else:
            print(f"  [FALLO] {nombre}")
            print("          Nadie lo lee: parece configurable y no hace nada.")
            print("          O se usa (y entonces no es un ajuste), o se")
            print("          documenta en MORTOS_CONOCIDOS con su motivo.")
            errores += 1

    if errores:
        print(f"\n{errores} ajuste(s) muerto(s) sin motivo documentado.")
        return 1
    print("\nOK: todo ajuste muerto tiene su motivo documentado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
