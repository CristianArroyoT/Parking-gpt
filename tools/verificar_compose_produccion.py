"""Puerta: el compose de producción es seguro, y sus valores se pueden cargar.

POR QUÉ (T-74/T-75, 2026-10-22):

1. El ``docker-compose.yml`` de la raíz es el de DESARROLLO, y el ADR-0001
   dice que "es el fichero que se copia a una sucursal". Con él, el backend
   arranca con ``ENVIRONMENT: development`` (o sea: **sin** exigir el
   secreto JWT real, que es público en este repositorio) y con el
   dev-server de Vite en vez de la imagen de producción. Por eso existe
   ``docker-compose.prod.yml``, con los valores **obligatorios** (si
   faltan, ``docker compose`` falla al arrancar).

2. Un valor de entorno con el formato equivocado hace que el backend
   **no arranque**: ``pydantic-settings`` parsea los campos de tipo lista
   antes de los validadores y solo entiende JSON, así que un
   ``TRUSTED_PROXIES="a,b"`` (el formato que documentaba el propio código)
   provocaba un ``SettingsError`` al arrancar. Y el compose lo llevaba:
   el despliegue de producción no arrancaba.

Lo que exige:
  1. que exista ``docker-compose.prod.yml``;
  2. que el backend arranque en ``production``;
  3. que ``JWT_SECRET``, ``FRONTEND_BASE_URL`` y ``CORS_ORIGINS`` sean
     **obligatorios** (sin valor por defecto: un default sería un secreto
     público);
  4. que no aparezca el secreto por defecto en el compose de producción;
  5. que el frontend de producción use el ``Dockerfile.prod``;
  6. que **todos** los valores de ``environment`` de los dos compose se
     puedan cargar en ``Settings`` (esto es lo que habría cazado el
     punto 2 antes de que seiese en producción).

Uso:
    python tools/verificar_compose_produccion.py
    python tools/verificar_compose_produccion.py --autoprueba
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE_DEV = RAIZ / "docker-compose.yml"
COMPOSE_PROD = RAIZ / "docker-compose.prod.yml"

#: Valores que son obligatorios en el compose de producción.
OBLIGATORIOS = ("JWT_SECRET", "FRONTEND_BASE_URL", "CORS_ORIGINS")

#: El secreto por defecto, que está en este repositorio público.
SECRETO_POR_DEFECTO = "change-me-in-production"

#: Servicios que usan la configuracion del backend (``app.core.config``).
SERVICIOS_DEL_BACKEND = ("backend", "celery-worker", "celery-beat")

#: Valor de prueba con el que se sustituyen las variables interpoladas
#: SIN default (``${VAR:?...}``) al validar: lo que pongra el operador.
VALOR_DE_PRUEBA = {
    "JWT_SECRET": "secreto-de-prueba-para-validar-la-configuracion",
    "FRONTEND_BASE_URL": "https://ejemplo.es",
    "CORS_ORIGINS": "https://ejemplo.es",
}

#: ``${VAR:-valor}`` y ``${VAR:?mensaje}``.
RE_INTERPOLACION = re.compile(r"^\$\{([A-Za-z0-9_]+)(:-|:\?)(.*)\}$")


def _resolver(clave: str, valor: str) -> str:
    """Resuelve una variable interpolada al valor que se usaria de verdad.

    ``${VAR:-5}`` -> "5" (su default). ``${VAR:?mensaje}`` -> el valor de
    prueba (lo que pondra el operador). Si no esta interpolada, se
    devuelve tal cual.
    """
    coincidencia = RE_INTERPOLACION.match(valor)
    if not coincidencia:
        return valor
    nombre, operador, resto = coincidencia.groups()
    if operador == ":-":
        return resto
    return VALOR_DE_PRUEBA.get(nombre, "valor-de-prueba")

#: ``CLAVE: ${CLAVE:?mensaje}`` → obligatorio (sin default).
RE_OBLIGATORIO = re.compile(r"^\s*([A-Z0-9_]+):\s*\"?\$\{\1:\?")
#: ``CLAVE: ${CLAVE:-valor}`` → tiene default.
RE_CON_DEFAULT = re.compile(r"\$\{[A-Z0-9_]+:-")


def _servicios(ruta: Path) -> dict[str, dict[str, str]]:
    """Extrae ``{servicio: {CLAVE: valor}}`` de los bloques ``environment``.

    Parser propio (sin PyYAML, que no es dependencia del repo) y sin
   ={(entorno)}: solo sirve para este formato, que es el del compose.
    """
    if not ruta.is_file():
        return {}
    servicios: dict[str, dict[str, str]] = {}
    servicio = None
    en_environment = False
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.strip().startswith("#"):
            continue
        sangria = len(linea) - len(linea.lstrip())
        if sangria == 2 and linea.rstrip().endswith(":"):
            servicio = linea.strip()[:-1]
            en_environment = False
            continue
        if sangria == 4 and linea.strip() == "environment:":
            en_environment = True
            if servicio:
                servicios.setdefault(servicio, {})
            continue
        if en_environment and sangria >= 6 and ":" in linea:
            clave, _, valor = linea.strip().partition(":")
            if servicio:
                servicios[servicio][clave.strip()] = valor.strip().strip('"')
            continue
        if sangria <= 4:
            en_environment = False
    return servicios


def comprobar(
    servicios_dev: dict[str, dict[str, str]],
    servicios_prod: dict[str, dict[str, str]],
    texto_prod: str,
) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []

    if not servicios_prod:
        problemas.append(
            "no existe docker-compose.prod.yml (o no se ha podido leer): es el "
            "fichero con los valores de producción que se copia a una "
            "sucursal (T-74)"
        )
        return problemas

    backend = servicios_prod.get("backend", {})
    if backend.get("ENVIRONMENT") != "production":
        problemas.append(
            "el backend del compose de producción no arranca en "
            f"'production' (dice {backend.get('ENVIRONMENT')!r}): con "
            "'development' no se exige el secreto JWT real, que es público "
            "en este repositorio (T-74)"
        )

    for clave in OBLIGATORIOS:
        valor = backend.get(clave)
        if valor is None:
            problemas.append(
                f"el compose de producción no define {clave}: sin ella el "
                "despliegue no es seguro (T-74)"
            )
            continue
        if not RE_OBLIGATORIO.match(f"{clave}: {valor}"):
            problemas.append(
                f"{clave} en el compose de producción debería ser "
                "obligatorio (`${...:?...}`): un valor por defecto seria un "
                "secreto publico (T-74)"
            )
        if RE_CON_DEFAULT.search(valor):
            problemas.append(
                f"{clave} en el compose de producción tiene un valor por "
                "defecto: eso es justo lo que no debe pasar (T-74)"
            )

    # El secreto por defecto, en los VALORES (un comentario que lo
    # menciona no es un valor).
    for servicio, variables in sorted(servicios_prod.items()):
        for clave, valor in sorted(variables.items()):
            if SECRETO_POR_DEFECTO in valor:
                problemas.append(
                    f"el compose de produccion usa el secreto por defecto "
                    f"('{SECRETO_POR_DEFECTO}') en {servicio}/{clave}, y esta "
                    "en este repositorio publico (T-74)"
                )

    frontend = servicios_prod.get("frontend", {})
    if "Dockerfile.prod" not in frontend.get("__build__", "") + texto_prod:
        # El build del frontend se comprueba sobre el texto (el parser
        # anterior solo recoge `environment`).
        if "dockerfile: Dockerfile.prod" not in texto_prod:
            problemas.append(
                "el frontend del compose de producción no se construye con "
                "el Dockerfile.prod: en una sucursal se serviria el "
                "dev-server de Vite en vez de la imagen de produccion (T-74)"
            )

    # Los valores de los servicios del backend tienen que poder cargarse
    # en ``Settings``. Se valida el CONJUNTO de variables de cada servicio
    # (una a una daria falsos positivos: ``ENVIRONMENT=production`` sin
    # ``JWT_SECRET`` falla, pero en el compose el secreto llega del
    # operador).
    for etiqueta, servicios in (("desarrollo", servicios_dev), ("produccion", servicios_prod)):
        for servicio in SERVICIOS_DEL_BACKEND:
            variables = servicios.get(servicio)
            if not variables:
                continue
            efectivo = {
                clave: _resolver(clave, valor)
                for clave, valor in variables.items()
                if re.match(r"^[A-Za-z0-9_]+$", clave)
            }
            problema = _cargar_en_settings(efectivo)
            if problema:
                detalle = ", ".join(f"{k}={v!r}" for k, v in sorted(efectivo.items()))
                problemas.append(
                    f"{etiqueta}/{servicio}: [{detalle}] no se puede cargar en "
                    f"la configuracion del backend ({problema}). El arranque "
                    "del backend fallaria (T-75)."
                )
    return problemas


def _cargar_en_settings(variables: dict[str, str]) -> str | None:
    """Intenta cargar el conjunto de variables en ``Settings``.

    Devuelve el motivo si falla, o ``None`` si todo bien.
    """
    if str(RAIZ / "backend") not in sys.path:
        sys.path.insert(0, str(RAIZ / "backend"))
    try:
        from app.core.config import Settings
    except Exception as exc:  # noqa: BLE001
        return f"no se pudo importar la configuracion: {exc}"
    try:
        Settings(**variables)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del compose de produccion:")
    fallos = 0

    prod_ok = {
        "backend": {
            "ENVIRONMENT": "production",
            "JWT_SECRET": "${JWT_SECRET:?falta JWT_SECRET}",
            "FRONTEND_BASE_URL": "${FRONTEND_BASE_URL:?falta FRONTEND_BASE_URL}",
            "CORS_ORIGINS": "${CORS_ORIGINS:?falta CORS_ORIGINS}",
        },
        "frontend": {},
    }
    texto_ok = "      dockerfile: Dockerfile.prod\n"

    casos = [
        ("todo correcto", {}, prod_ok, texto_ok, False),
        (
            "el backend no arranca en production",
            {},
            {**prod_ok, "backend": {**prod_ok["backend"], "ENVIRONMENT": "development"}},
            texto_ok,
            True,
        ),
        (
            "el secreto con valor por defecto",
            {},
            {
                **prod_ok,
                "backend": {**prod_ok["backend"], "JWT_SECRET": "${JWT_SECRET:-change-me-in-production}"},
            },
            texto_ok,
            True,
        ),
        (
            "el secreto por defecto en el worker",
            {},
            {
                **prod_ok,
                "celery-worker": {
                    "JWT_SECRET": "${JWT_SECRET:-change-me-in-production}",
                },
            },
            texto_ok,
            True,
        ),
        (
            "un comentario que menciona el secreto no es un fallo",
            {},
            prod_ok,
            texto_ok + "      # no uses change-me-in-production\n",
            False,
        ),
        (
            "sin FRONTEND_BASE_URL",
            {},
            {
                **prod_ok,
                "backend": {
                    k: v for k, v in prod_ok["backend"].items() if k != "FRONTEND_BASE_URL"
                },
            },
            texto_ok,
            True,
        ),
        (
            "el frontend con el Dockerfile de desarrollo",
            {},
            prod_ok,
            "      dockerfile: Dockerfile\n",
            True,
        ),
        ("sin compose de produccion", {}, {}, "", True),
        (
            "un valor de entorno que el backend no puede cargar",
            {
                "backend": {
                    "ENVIRONMENT": "development",
                    "TRUSTED_PROXIES": "172.16.0.0/12,10.0.0.0/8",
                }
            },
            prod_ok,
            texto_ok,
            False,  # con el arreglo (T-75) este valor SÍ se puede cargar
        ),
    ]
    for nombre, dev, prod, texto, debe_fallar in casos:
        problemas = comprobar(dev, prod, texto)
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
        description="Comprueba que el compose de produccion es seguro y que sus valores cargan."
    )
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (casos de mentira escritos a mano)",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return autoprueba()

    servicios_dev = _servicios(COMPOSE_DEV)
    servicios_prod = _servicios(COMPOSE_PROD)
    texto_prod = COMPOSE_PROD.read_text(encoding="utf-8") if COMPOSE_PROD.is_file() else ""

    problemas = comprobar(servicios_dev, servicios_prod, texto_prod)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    print(
        f"OK: el compose de produccion exige el secreto, la URL publica y los "
        f"origenes, y los valores de los {len(servicios_dev) + len(servicios_prod)} "
        "servicios se pueden cargar en la configuracion del backend."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
