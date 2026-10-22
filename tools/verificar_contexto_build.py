"""Puerta: el contexto de build de la imagen de produccion esta limpio.

POR QUÉ (T-63, 2026-10-22): el contexto de ``frontend/Dockerfile.prod`` es
``frontend/``, y Docker busca el ``.dockerignore`` **en la raiz del
contexto**: el de la raiz del repositorio NO se aplica. Sin un
``.dockerignore`` en ``frontend/``, el ``COPY . .`` de la etapa de build se
llevaba el ``node_modules`` del HOST dentro de la imagen (en esta maquina,
el de Windows) por encima del que acababa de instalar ``npm ci``. La
imagen que se construia en local no era entonces la misma que construye
el CI, que parte de un checkout limpio.

Lo que exige:
  1. que exista ``frontend/.dockerignore``;
  2. que excluya ``node_modules`` y ``dist``;
  3. que el ``Dockerfile.prod`` no copie el ``node_modules`` del contexto a
     mano (las copias ``--from=`` si valen: son de otra etapa).

Uso:
    python tools/verificar_contexto_build.py
    python tools/verificar_contexto_build.py --autoprueba
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONTEXTO = RAIZ / "frontend"
DOCKERIGNORE = CONTEXTO / ".dockerignore"
DOCKERFILE = CONTEXTO / "Dockerfile.prod"

#: Lo que tiene que estar excluido del contexto.
EXCLUIDOS_OBLIGATORIOS = ("node_modules", "dist")

#: ``COPY node_modules ...`` o ``ADD dist ...`` **del contexto**.
#: Las copias ``--from=otra-etapa`` no cuentan (no vienen del contexto).
RE_COPIA_EXPLICITA = re.compile(
    r"^\s*(COPY|ADD)\s+(?!.*--from=)(.*)$", re.IGNORECASE | re.MULTILINE
)
RE_NOMBRE_PROHIBIDO = re.compile(r"\b(node_modules|dist)\b", re.IGNORECASE)


def leer_exclusiones(dockerignore: Path) -> list[str]:
    """Las exclusiones declaradas (sin comentarios ni líneas vacías)."""
    if not dockerignore.is_file():
        return []
    exclusiones: list[str] = []
    for linea in dockerignore.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        exclusiones.append(limpia)
    return exclusiones


def comprobar(
    exclusiones: list[str], dockerfile: str, hay_dockerignore: bool
) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []
    if not hay_dockerignore:
        problemas.append(
            "no existe frontend/.dockerignore: el contexto de build de la "
            "imagen de produccion es 'frontend/', y Docker busca el "
            ".dockerignore en la raiz del CONTEXTO (el de la raiz del "
            "repositorio no se aplica). Sin el, el 'COPY . .' se lleva el "
            "node_modules del host dentro de la imagen."
        )
        return problemas
    for excluido in EXCLUIDOS_OBLIGATORIOS:
        if excluido not in exclusiones:
            problemas.append(
                f"frontend/.dockerignore no excluye '{excluido}': el "
                f"'{excluido}' del host entraria en la imagen de produccion "
                "(y la imagen que se construye en local no seria la misma "
                "que construye el CI)."
            )
    for coincidencia in RE_COPIA_EXPLICITA.finditer(dockerfile):
        linea = coincidencia.group(2)
        encontrada = RE_NOMBRE_PROHIBIDO.search(linea)
        if encontrada:
            problemas.append(
                f"el Dockerfile.prod copia '{encontrada.group(0)}' del "
                f"contexto a mano ({linea.strip()}): con el .dockerignore de "
                "por medio, eso mete en la imagen lo que se quiso excluir."
            )
    return problemas


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del contexto de build:")
    fallos = 0
    casos = [
        ("sin .dockerignore", [], "", False, True),
        (".dockerignore sin node_modules", ["dist"], "", True, True),
        (".dockerignore sin dist", ["node_modules"], "", True, True),
        (".dockerignore con los dos", ["node_modules", "dist"], "", True, False),
        (
            ".dockerignore correcto pero el Dockerfile copia node_modules",
            ["node_modules", "dist"],
            "COPY node_modules /app/node_modules\n",
            True,
            True,
        ),
        (
            ".dockerignore correcto y el Dockerfile copia de otra etapa",
            ["node_modules", "dist"],
            "COPY --from=build /app/dist /usr/share/nginx/html\n",
            True,
            False,
        ),
    ]
    for nombre, exclusiones, dockerfile, hay, debe_fallar in casos:
        problemas = comprobar(exclusiones, dockerfile, hay)
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
        description="Comprueba que el contexto de build de la imagen de produccion esta limpio."
    )
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (casos de mentira escritos a mano)",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return autoprueba()

    hay = DOCKERIGNORE.is_file()
    exclusiones = leer_exclusiones(DOCKERIGNORE)
    dockerfile = DOCKERFILE.read_text(encoding="utf-8") if DOCKERFILE.is_file() else ""
    problemas = comprobar(exclusiones, dockerfile, hay)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    print(
        f"OK: el contexto de build excluye {', '.join(EXCLUIDOS_OBLIGATORIOS)} "
        f"({len(exclusiones)} exclusiones en frontend/.dockerignore)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
