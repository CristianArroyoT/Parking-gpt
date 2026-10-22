"""Puerta: el ``package-lock.json`` está sincronizado con el ``package.json``.

POR QUÉ (T-71, 2026-10-22): el ``Dockerfile.prod`` hacía
``RUN npm ci || npm install``. Ese "fallback" es una trampa:

- si ``npm ci`` falla (lockfile desincronizado con el ``package.json``),
  la imagen se construye con las **últimas versiones del registro**, sin
  lockfile: el build deja de ser reproducible y **el fallo queda
  escondido**;
- el ``npm install`` sin ``package-lock.json`` es además más lento y
  descarga mas.

La puerta comprueba lo mismo que comprueba ``npm ci`` antes de instalar:
que las dependencias declaradas en el ``package.json`` y las del
``package-lock.json`` (en ``packages[""]``) sean las mismas. Es lo que
hace que un "añadí una dependencia y no regeneré el lockfile" salte
**antes** de construir la imagen, y no en pleno build.

Uso:
    python tools/verificar_lockfile.py
    python tools/verificar_lockfile.py --autoprueba
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FRONTEND = RAIZ / "frontend"
PACKAGE_JSON = FRONTEND / "package.json"
LOCKFILE = FRONTEND / "package-lock.json"

#: Las secciones del package.json que npm refleja en el lockfile.
SECCIONES = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def comprobar(
    package: dict, lock: dict
) -> list[str]:
    """Devuelve la lista de problemas (vacía si el lockfile está al día)."""
    problemas: list[str] = []

    raiz_lock = (lock.get("packages") or {}).get("")
    if raiz_lock is None:
        return [
            "el package-lock.json no tiene la entrada packages[\"\"]: no es "
            "un lockfile v2/v3 (npm no puede verificarlo con `npm ci`)"
        ]

    for seccion in SECCIONES:
        declarados = package.get(seccion) or {}
        en_lock = raiz_lock.get(seccion) or {}
        if declarados == en_lock:
            continue
        solo_package = {
            k: v for k, v in declarados.items() if en_lock.get(k) != v
        }
        solo_lock = {
            k: v for k, v in en_lock.items() if declarados.get(k) != v
        }
        detalle = []
        if solo_package:
            detalle.append(f"en el package.json y no en el lockfile: {solo_package}")
        if solo_lock:
            detalle.append(f"en el lockfile y no en el package.json: {solo_lock}")
        problemas.append(
            f"la sección '{seccion}' no coincide entre el package.json y el "
            f"package-lock.json ({'; '.join(detalle)}). `npm ci` fallaria: "
            "regenera el lockfile con `npm install`."
        )

    return problemas


def _leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del lockfile:")
    fallos = 0

    def _lock(dep: dict, dev: dict) -> dict:
        return {"packages": {"": {"dependencies": dep, "devDependencies": dev}}}

    casos = [
        (
            "package.json y lockfile iguales",
            {"dependencies": {"a": "^1.0.0"}, "devDependencies": {"b": "^2.0.0"}},
            _lock({"a": "^1.0.0"}, {"b": "^2.0.0"}),
            False,
        ),
        (
            "una dependencia nueva en el package.json",
            {"dependencies": {"a": "^1.0.0", "c": "^3.0.0"}, "devDependencies": {}},
            _lock({"a": "^1.0.0"}, {}),
            True,
        ),
        (
            "una version cambiada en el package.json",
            {"dependencies": {"a": "^1.2.0"}, "devDependencies": {}},
            _lock({"a": "^1.0.0"}, {}),
            True,
        ),
        (
            "una dependencia quitada del package.json",
            {"dependencies": {}, "devDependencies": {}},
            _lock({"a": "^1.0.0"}, {}),
            True,
        ),
        (
            "una devDependency nueva (el caso tipico)",
            {"dependencies": {}, "devDependencies": {"b": "^2.0.0"}},
            _lock({}, {}),
            True,
        ),
        (
            "lockfile sin packages[\"\"]",
            {"dependencies": {}, "devDependencies": {}},
            {"packages": {}},
            True,
        ),
    ]
    for nombre, package, lock, debe_fallar in casos:
        problemas = comprobar(package, lock)
        fallo = bool(problemas)
        if fallo != debe_fallar:
            fallos += 1
            print(
                f"  FALLO {nombre}: la puerta {'falla' if fallo else 'pasa'} "
                f"y se esperaba que {'fallase' if debe_fallar else 'pasase'}"
            )
            for p in problemas:
                print(f"          {p}")
        else:
            print(f"  OK    {nombre}: la puerta {'falla' if fallo else 'pasa'}")

    if fallos:
        print(f"AUTOPRUEBA FALLIDA ({fallos} problema(s))")
        return 1
    print("AUTOPRUEBA CORRECTA: la puerta puede fallar y puede pasar")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba que el package-lock.json está sincronizado con el package.json."
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
        package = _leer(PACKAGE_JSON)
        lock = _leer(LOCKFILE)
    except (OSError, json.JSONDecodeError) as error:
        print(f"  FALLO  no se puede leer el package.json o el lockfile: {error}")
        return 1

    problemas = comprobar(package, lock)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    total = sum(len(package.get(s) or {}) for s in SECCIONES)
    print(
        f"OK: el package-lock.json está sincronizado con el package.json "
        f"({total} dependencias declaradas)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
