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
OBLIGATORIOS = ("JWT_SECRET", "FRONTEND_BASE_URL", "CORS_ORIGINS", "SMTP_HOST")

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
    "SMTP_HOST": "smtp.ejemplo.es",
}

#: ``${VAR:-valor}`` y ``${VAR:?mensaje}``.
RE_INTERPOLACION = re.compile(r"^\$\{([A-Za-z0-9_]+)(:-|:\?)(.*)\}$")

#: Avisos que no son fallos pero hay que decir. T-147 (2026-10-24): esta
#: puerta corre en el CI en jobs **sin** las dependencias del backend (el de
#: las autopruebas va ANTES del ``pip install``, y el de las imagenes Docker
#: no las instala). Sin esto, la puerta fallaba por el entorno y no por el
#: compose: el CI remoto, al arrancar por primera vez, enseño justo eso.
AVISOS: list[str] = []


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


def _fusionar(
    servicios_dev: dict[str, dict[str, str]],
    servicios_prod: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """El ``environment`` **efectivo** del despliegue: dev + produccion.

    El compose de produccion es un OVERRIDE del de desarrollo: lo que no
    redefine se hereda. Y ``environment`` es un mapa, asi que lo que
    redefines pisa lo heredado. Sin esta fusion, un servicio que el
    compose de produccion no menciona parece no tener ``ENVIRONMENT``
    cuando en realidad hereda el ``development`` del compose de
    desarrollo (T-142).
    """
    efectivo: dict[str, dict[str, str]] = {
        nombre: dict(variables) for nombre, variables in servicios_dev.items()
    }
    for nombre, variables in servicios_prod.items():
        combinado = dict(efectivo.get(nombre, {}))
        combinado.update(variables)
        efectivo[nombre] = combinado
    return efectivo


def _bloque_del_servicio(texto: str, nombre: str) -> str:
    """El bloque de un servicio del compose (de su nombre al siguiente).

    Se busca por sangria (dos espacios), como el resto de los parsers de
    este repo: sin PyYAML, que no es dependencia del repo.

    OJO: se **quitan los comentarios**. Una puerta que lee el texto sin
    más confunde un comentario con una configuracion: este repo ya lo
    aprendio con una puerta que daba el visto bueno a un endpoint que NO
    acotaba la sucursal, porque su docstring mencionaba el helper
    correcto. Y con este mismo bloque de codigo: el comentario que
    explica el T-145 menciona `--reload`, y el compose ya no lo tiene.
    """
    lineas = texto.splitlines()
    bloque: list[str] = []
    dentro = False
    for linea in lineas:
        sangria = len(linea) - len(linea.lstrip())
        if sangria == 2 and linea.rstrip().endswith(":"):
            if dentro:
                break
            dentro = linea.strip()[:-1] == nombre
            if dentro:
                bloque.append(linea)
            continue
        if dentro:
            if linea.strip().startswith("#"):
                continue
            bloque.append(linea)
    return "\n".join(bloque)


def comprobar(
    servicios_dev: dict[str, dict[str, str]],
    servicios_prod: dict[str, dict[str, str]],
    texto_prod: str,
    texto_dev: str = "",
) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []

    AVISOS.clear()

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

    # T-101: todos los servicios se levantan solos si mueren. El compose
    # de produccion es un OVERRIDE del de desarrollo: los servicios los
    # define el de desarrollo y el de produccion solo cambia algunas
    # cosas de algunos. Sin `restart: unless-stopped`, un servicio que
    # se cae (un OOM, un SIGKILL) se queda caido hasta que alguien lo
    # levante a mano. En el worker es lo mas grave: el beat sigue
    # publicando cada 60 s y la cola crece sin que nadie la consuma.
    reinicios = _politicas_de_restart(texto_dev)
    for servicio, valor in _politicas_de_restart(texto_prod).items():
        if valor is not None:
            reinicios[servicio] = valor
    # T-155 (2026-10-24): los one-shot (los que declaran `profiles`) quedan
    # exentos: se ejecutan a proposito y terminan; con
    # `restart: unless-stopped` Docker los volveria a arrancar en bucle.
    one_shot = _servicios_one_shot(texto_dev) | _servicios_one_shot(texto_prod)
    for servicio, valor in sorted(reinicios.items()):
        if servicio in one_shot:
            continue
        if valor != "unless-stopped":
            problemas.append(
                f"el servicio {servicio} no tiene 'restart: unless-stopped' "
                f"(dice {valor!r}): si se cae se queda caido hasta que "
                "alguien lo levante a mano (T-101)"
            )

    # T-145 (2026-10-24): en una sucursal el backend NO puede arrancar con
    # `--reload` ni con el codigo del host montado (`./backend:/app`).
    #
    # Con el bind mount, el codigo que corre es el del disco de la
    # maquina, no el de la imagen que se construyo y se verifico: el
    # artefacto desplegado deja de ser el que se probó. Y `--reload` pone
    # un watcher que recarga en caliente y consume CPU.
    #
    # OJO: el compose de produccion es un OVERRIDE: si no dice nada del
    # `command` ni de los `volumes` del backend, hereda los del compose de
    # desarrollo (que son los de desarrollo). Por eso se mira el bloque
    # del servicio en el compose de PRODUCCION: si no dice nada, el
    # defecto esta.
    for servicio in ("backend", "celery-worker", "celery-beat"):
        bloque = _bloque_del_servicio(texto_prod, servicio)
        if not bloque:
            continue
        if "--reload" in bloque:
            problemas.append(
                f"docker-compose.prod.yml: {servicio} arranca con --reload: en "
                "produccion no hay recarga en caliente (T-145)"
            )
        if re.search(r"^\s*-\s*\./backend:/app", bloque, re.M):
            problemas.append(
                f"docker-compose.prod.yml: {servicio} monta el codigo del host "
                "en /app: lo que corre seria el codigo del disco, no el de la "
                "imagen que se construyo y se verifico (T-145)"
            )

    # El `build:` del frontend se comprueba sobre el texto: el parser de
    # arriba solo recoge los bloques `environment`.
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

    # T-142 (2026-10-24): el worker y el beat tienen que arrancar en
    # 'production' y con el SMTP configurado.
    #
    # Medido (compose combinado, el que se copia a una sucursal): antes el
    # override de produccion solo le daba ENVIRONMENT al backend, asi que
    # el worker se quedaba en 'development' — y ahi los correos son
    # SIMULADOS (dry-run): el reset de contrasena respondia 200 «te hemos
    # enviado un correo» y el correo no salia NUNCA, sin que nadie se
    # enterara. Lo mismo con las alertas de camara caida.
    efectivo = _fusionar(servicios_dev, servicios_prod)
    for servicio in ("celery-worker", "celery-beat"):
        variables = efectivo.get(servicio)
        if not variables:
            continue
        if variables.get("ENVIRONMENT") != "production":
            problemas.append(
                f"{servicio} del compose de produccion no arranca en "
                f"'production' (dice {variables.get('ENVIRONMENT')!r}): en "
                "'development' los correos son SIMULADOS y no salen nunca "
                "(T-142)"
            )
        smtp = variables.get("SMTP_HOST")
        if smtp is None:
            problemas.append(
                f"{servicio} del compose de produccion no define SMTP_HOST: "
                "los correos del worker no se pueden enviar (T-142)"
            )
        elif not RE_OBLIGATORIO.match(f"SMTP_HOST: {smtp}"):
            problemas.append(
                f"{servicio} del compose de produccion da a SMTP_HOST un "
                "valor por defecto: deberia ser obligatorio, para que el "
                "arranque falle si falta (T-142)"
            )

    # El enlace del correo de reset de contrasena lo construye el worker.
    worker = efectivo.get("celery-worker") or {}
    if worker and "FRONTEND_BASE_URL" not in worker:
        problemas.append(
            "celery-worker del compose de produccion no define "
            "FRONTEND_BASE_URL: el enlace del correo de reset de contrasena "
            "saldria con la URL de desarrollo (T-142)"
        )
    return problemas


def _politicas_de_restart(texto: str) -> dict[str, str | None]:
    """Servicios del compose y su politica de reinicio (``None`` si no tiene).

    Solo cuenta los bloques que tienen ``image:`` o ``build:`` (los
    volumenes de abajo del compose no son servicios).
    """
    servicios: dict[str, str | None] = {}
    nombre = None
    es_servicio = False
    reinicio: str | None = None
    for linea in texto.splitlines():
        if not linea.strip() or linea.strip().startswith("#"):
            continue
        sangria = len(linea) - len(linea.lstrip())
        if sangria == 2 and linea.rstrip().endswith(":"):
            if nombre and es_servicio:
                servicios[nombre] = reinicio
            nombre = linea.strip()[:-1]
            es_servicio = False
            reinicio = None
            continue
        if sangria == 4 and (
            linea.strip().startswith("image:")
            or linea.strip().startswith("build:")
        ):
            es_servicio = True
            continue
        if sangria == 4 and linea.strip().startswith("restart:"):
            reinicio = linea.strip().split(":", 1)[1].strip().strip('"')
            continue
    if nombre and es_servicio:
        servicios[nombre] = reinicio
    return servicios


def _servicios_one_shot(texto: str) -> set[str]:
    """Los servicios que declaran ``profiles``: se ejecutan a proposito.

    T-155 (2026-10-24): un one-shot (por ejemplo el servicio ``backup``)
    **no** puede llevar ``restart: unless-stopped``: el script termina al
    hacer su trabajo, Docker lo ve caido y lo vuelve a arrancar en bucle.
    Asi que estos servicios quedan exentos de la regla del reinicio
    automatico.
    """
    one_shot: set[str] = set()
    nombre: str | None = None
    es_servicio = False
    tiene_profiles = False
    for linea in texto.splitlines():
        if not linea.strip() or linea.strip().startswith("#"):
            continue
        sangria = len(linea) - len(linea.lstrip())
        if sangria == 2 and linea.rstrip().endswith(":"):
            if nombre and es_servicio and tiene_profiles:
                one_shot.add(nombre)
            nombre = linea.strip()[:-1]
            es_servicio = False
            tiene_profiles = False
            continue
        if sangria == 4 and (
            linea.strip().startswith("image:")
            or linea.strip().startswith("build:")
        ):
            es_servicio = True
            continue
        if sangria == 4 and linea.strip().startswith("profiles:"):
            tiene_profiles = True
            continue
    if nombre and es_servicio and tiene_profiles:
        one_shot.add(nombre)
    return one_shot


def _cargar_en_settings(variables: dict[str, str]) -> str | None:
    """Intenta cargar el conjunto de variables en ``Settings``.

    Devuelve el motivo si falla, o ``None`` si todo bien.
    """
    if str(RAIZ / "backend") not in sys.path:
        sys.path.insert(0, str(RAIZ / "backend"))
    try:
        from app.core.config import Settings
    except Exception as exc:  # noqa: BLE001
        # T-147: no es un fallo de la puerta, es que este entorno no tiene
        # las dependencias del backend. Se avisa (no se calla) y la
        # comprobacion se hace en el job `backend`, tras instalar.
        if not any("configuracion del backend" in a for a in AVISOS):
            AVISOS.append(
            "la configuracion del backend no se ha podido importar "
            f"({exc}): NO se ha comprobado que las variables del compose "
            "carguen en ella. Se comprueba en el job 'backend', despues de "
            "instalar las dependencias."
        )
        return None
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
            "SMTP_HOST": "${SMTP_HOST:?falta SMTP_HOST}",
        },
        "celery-worker": {
            "ENVIRONMENT": "production",
            "JWT_SECRET": "${JWT_SECRET:?falta JWT_SECRET}",
            "SMTP_HOST": "${SMTP_HOST:?falta SMTP_HOST}",
            "FRONTEND_BASE_URL": "${FRONTEND_BASE_URL:?falta FRONTEND_BASE_URL}",
        },
        "celery-beat": {
            "ENVIRONMENT": "production",
            "JWT_SECRET": "${JWT_SECRET:?falta JWT_SECRET}",
            "SMTP_HOST": "${SMTP_HOST:?falta SMTP_HOST}",
            "FRONTEND_BASE_URL": "${FRONTEND_BASE_URL:?falta FRONTEND_BASE_URL}",
        },
        "frontend": {},
    }
    texto_ok = (
        "  backend:\n"
        "    command: !override [\"uvicorn\", \"app.main:app\"]\n"
        "    volumes: !override\n"
        "      - incident_attachments:/var/lib/solidapp/incident-attachments\n"
        "      dockerfile: Dockerfile.prod\n"
    )

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
            "el worker no arranca en production",
            {},
            {
                **prod_ok,
                "celery-worker": {
                    **prod_ok["celery-worker"],
                    "ENVIRONMENT": "development",
                },
            },
            texto_ok,
            True,
        ),
        (
            "el beat no arranca en production",
            {},
            {
                **prod_ok,
                "celery-beat": {
                    **prod_ok["celery-beat"],
                    "ENVIRONMENT": "development",
                },
            },
            texto_ok,
            True,
        ),
        (
            "el worker no tiene SMTP_HOST",
            {},
            {
                **prod_ok,
                "celery-worker": {
                    k: v
                    for k, v in prod_ok["celery-worker"].items()
                    if k != "SMTP_HOST"
                },
            },
            texto_ok,
            True,
        ),
        (
            "el SMTP del worker tiene valor por defecto",
            {},
            {
                **prod_ok,
                "celery-worker": {
                    **prod_ok["celery-worker"],
                    "SMTP_HOST": "${SMTP_HOST:-localhost}",
                },
            },
            texto_ok,
            True,
        ),
        (
            "el worker no tiene FRONTEND_BASE_URL",
            {},
            {
                **prod_ok,
                "celery-worker": {
                    k: v
                    for k, v in prod_ok["celery-worker"].items()
                    if k != "FRONTEND_BASE_URL"
                },
            },
            texto_ok,
            True,
        ),
        (
            "el backend arranca con --reload",
            {},
            prod_ok,
            "  backend:\n"
            "    command: !override [\"uvicorn\", \"app.main:app\", \"--reload\"]\n",
            True,
        ),
        (
            "el backend monta el codigo del host",
            {},
            prod_ok,
            "  backend:\n"
            "    volumes: !override\n"
            "      - ./backend:/app\n",
            True,
        ),
        (
            "un comentario que menciona --reload no es un fallo",
            {},
            prod_ok,
            "  backend:\n"
            "    # OJO: NO arrancar con --reload en produccion.\n"
            "    command: !override [\"uvicorn\", \"app.main:app\"]\n"
            "      dockerfile: Dockerfile.prod\n",
            False,
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
            "un servicio sin politica de reinicio",
            {},
            prod_ok,
            texto_ok,
            True,
            "  backend:\n    image: ejemplo\n",
        ),
        (
            "todos los servicios con politica de reinicio",
            {},
            prod_ok,
            texto_ok,
            False,
            "  backend:\n    image: ejemplo\n    restart: unless-stopped\n",
        ),
        (
            "un servicio one-shot (con profiles) no necesita politica de reinicio",
            {},
            prod_ok,
            "  backend:\n"
            "    command: !override [\"uvicorn\", \"app.main:app\"]\n"
            "    volumes: !override\n"
            "      - incident_attachments:/var/lib/solidapp/incident-attachments\n"
            "      dockerfile: Dockerfile.prod\n"
            "  backup:\n"
            "    image: ejemplo\n"
            "    profiles: [\"backup\"]\n"
            "    restart: \"no\"\n",
            False,
        ),
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
    for caso in casos:
        nombre, dev, prod, texto, debe_fallar = caso[:5]
        texto_dev = caso[5] if len(caso) > 5 else ""
        problemas = comprobar(dev, prod, texto, texto_dev)
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
    texto_dev = COMPOSE_DEV.read_text(encoding="utf-8") if COMPOSE_DEV.is_file() else ""

    problemas = comprobar(servicios_dev, servicios_prod, texto_prod, texto_dev)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    # T-147: los avisos no son fallos, pero se dicen (un verde silencioso
    # sobre una comprobacion que no se ha hecho no vale).
    for aviso in AVISOS:
        print(f"  AVISO  {aviso}")
    print(
        f"OK: el compose de produccion exige el secreto, la URL publica y los "
        f"origenes, y los valores de los {len(servicios_dev) + len(servicios_prod)} "
        "servicios se pueden cargar en la configuracion del backend."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
