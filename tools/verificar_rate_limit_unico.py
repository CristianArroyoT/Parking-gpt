"""Puerta (v2): el rate-limit por endpoint tiene UNA sola implementacion, y
el flag ``User.no_rate_limit`` se LEE de verdad.

POR QUÉ (T-68/T-69, 2026-10-22):

1. El campo ``User.no_rate_limit`` prometía (en el comentario del propio
   modelo) que las cuentas de servicio —un cronjob de carga inicial de
   datos— se saltan el rate-limit de los CRUDs. El mecanismo existía
   (``EndpointRateLimiter.check(skip=True)``) y tenía su propio test, pero
   **nadie lo pedía**: el flag no se leía en ningún sitio de la
   aplicación, así que una cuenta de servicio se comía un 429 igual que
   un humano. El test del mecanismo daba verde mientras la capacidad no
   existía.
2. Y el helper ``_enforce_endpoint_rate_limit`` estaba **copiado** en
   cinco routers (``users``, ``vehicles``, ``cameras``, ``parkings``,
   ``tariffs``), con un sexto (``gestor_operadores``) escrito en línea:
   seis copias del mismo código, de modo que arreglar una no arreglaba
   las otras cinco.

Lo que exige:
  1. que el rate-limit por endpoint se aplique **siempre** por
     ``enforce_endpoint_rate_limit`` (una sola implementación);
  2. que en los routers no haya llamadas directas a
     ``endpoint_rate_limiter.check(``;
  3. que el flag ``no_rate_limit`` se **LEA** (un acceso al atributo, no
     una mención en un comentario: se comprueba con el árbol sintáctico).

Uso:
    python tools/verificar_rate_limit_unico.py
    python tools/verificar_rate_limit_unico.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
API_V1 = RAIZ / "backend" / "app" / "api" / "v1"
SERVICIO = RAIZ / "backend" / "app" / "services" / "endpoint_rate_limit.py"
APP = RAIZ / "backend" / "app"
MODELO = APP / "models" / "user.py"

#: La llamada directa que no debe existir en los routers.
LLAMADA_DIRECTA = "endpoint_rate_limiter.check("
#: La función que sí debe existir (implementación única).
FUNCION_UNICA = "def enforce_endpoint_rate_limit("
#: El flag que debe leerse en la aplicación.
FLAG = "no_rate_limit"

#: Routers que SÍ pueden llamar al limitador directamente, con el motivo.
EXCEPCIONES: dict[str, str] = {
    "password_reset.py": (
        "los endpoints de recuperación de contraseña son PÚBLICOS: no hay "
        "actor autenticado al que se le pueda saltar el límite (y ahí el "
        "flag `no_rate_limit` no aplicaría)"
    ),
}


def _accesos_al_flag(texto: str) -> int:
    """Cuántos accesos REALES al atributo ``no_rate_limit`` hay.

    Se cuenta con el árbol sintáctico y no buscando la cadena: una
    mención en un docstring o en un comentario **no** es leer el flag.
    """
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return 0
    return sum(
        1
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Attribute) and nodo.attr == FLAG
    )


def comprobar(
    routers: dict[str, str],
    servicio: str,
    lecturas_flag: dict[str, int],
) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []

    if FUNCION_UNICA not in servicio:
        problemas.append(
            "el servicio no define `enforce_endpoint_rate_limit`: la "
            "implementación única del rate-limit por endpoint (T-69)"
        )
    if _accesos_al_flag(servicio) == 0:
        problemas.append(
            "el servicio no ACCEDE a `no_rate_limit`: el flag de las "
            "cuentas de servicio no se leería (T-68)"
        )

    for nombre, contenido in routers.items():
        if nombre in EXCEPCIONES:
            # La excepción tiene que seguir siendo cierta: si el fichero
            # ya no llama al limitador, la excepción se queda obsoleta y
            # acabaría silenciando a otro router.
            if LLAMADA_DIRECTA not in contenido:
                problemas.append(
                    f"la excepción de '{nombre}' ya no aplica (no llama al "
                    "limitador): quítala de EXCEPCIONES o explica por qué "
                    "sigue siendo necesaria"
                )
            continue
        if LLAMADA_DIRECTA in contenido:
            problemas.append(
                f"backend/app/api/v1/{nombre} llama directamente a "
                "`endpoint_rate_limiter.check(`: el rate-limit por endpoint "
                "tiene que pasar por `enforce_endpoint_rate_limit`, que es la "
                "única implementación (T-69). Con las copias, arreglar una "
                "no arreglaba las otras cinco."
            )

    if not lecturas_flag:
        problemas.append(
            "el flag `User.no_rate_limit` no se LEE en ninguna parte de la "
            "aplicación: parece configurable y no hace nada (T-68)"
        )

    return problemas


def _leer_lecturas_flag() -> dict[str, int]:
    """Los ficheros de la aplicación (menos el modelo) que leen el flag."""
    lecturas: dict[str, int] = {}
    for ruta in APP.rglob("*.py"):
        if ruta == MODELO:
            continue
        accesos = _accesos_al_flag(ruta.read_text(encoding="utf-8"))
        if accesos:
            lecturas[str(ruta.relative_to(RAIZ)).replace("\\", "/")] = accesos
    return lecturas


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del rate-limit unico:")
    fallos = 0
    servicio_ok = (
        "def enforce_endpoint_rate_limit(request, db, *, scope, actor_id, skip=False):\n"
        "    actor = db.get(User, actor_id)\n"
        "    skip = bool(actor is not None and actor.no_rate_limit)\n"
    )
    servicio_sin_flag = (
        "def enforce_endpoint_rate_limit(request, db, *, scope, actor_id, skip=False):\n"
        "    skip = False\n"
    )
    servicio_menciona = (
        "def enforce_endpoint_rate_limit(request, db, *, scope, actor_id, skip=False):\n"
        '    """El flag `User.no_rate_limit` se lee aqui."""\n'
        "    skip = False\n"
    )
    casos = [
        ("todo correcto",
         {"users.py": "enforce_endpoint_rate_limit(request, db)\n"},
         servicio_ok, {"app/services/x.py": 1}, False),
        ("un router con una copia del limitador",
         {"users.py": "allowed, bucket, count = endpoint_rate_limiter.check(\n"},
         servicio_ok, {"app/services/x.py": 1}, True),
        ("el servicio no define la funcion unica",
         {"users.py": "enforce_endpoint_rate_limit(request, db)\n"},
         "class EndpointRateLimiter:\n    pass\n",
         {"app/services/x.py": 1}, True),
        ("el servicio no accede al flag",
         {"users.py": "enforce_endpoint_rate_limit(request, db)\n"},
         servicio_sin_flag, {"app/services/x.py": 1}, True),
        ("el servicio solo MENCIONA el flag (en el docstring)",
         {"users.py": "enforce_endpoint_rate_limit(request, db)\n"},
         servicio_menciona, {"app/services/x.py": 1}, True),
        ("nadie accede al flag",
         {"users.py": "enforce_endpoint_rate_limit(request, db)\n"},
         servicio_ok, {}, True),
        ("un router en la lista de excepciones (no es un fallo)",
         {"password_reset.py": "endpoint_rate_limiter.check(\n"},
         servicio_ok, {"app/services/x.py": 1}, False),
        ("una excepcion que ya no aplica",
         {"password_reset.py": "enforce_endpoint_rate_limit(x)\n"},
         servicio_ok, {"app/services/x.py": 1}, True),
    ]
    for nombre, routers, servicio, lecturas, debe_fallar in casos:
        problemas = comprobar(routers, servicio, lecturas)
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
        description="Comprueba que el rate-limit por endpoint tiene una sola implementación."
    )
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (casos de mentira escritos a mano)",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return autoprueba()

    routers = {
        ruta.name: ruta.read_text(encoding="utf-8") for ruta in sorted(API_V1.glob("*.py"))
    }
    servicio = SERVICIO.read_text(encoding="utf-8") if SERVICIO.is_file() else ""
    lecturas = _leer_lecturas_flag()

    problemas = comprobar(routers, servicio, lecturas)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    print(
        f"OK: el rate-limit por endpoint tiene una sola implementación "
        f"({len(routers)} routers revisados) y el flag `no_rate_limit` se lee "
        f"en {len(lecturas)} fichero(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
