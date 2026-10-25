"""Puerta: la documentacion dice como desplegar en produccion.

POR QUE (T-80, 2026-10-22): el T-74 arreglo el compose de produccion
(``docker-compose.prod.yml``, con el secreto, la URL publica y los
origenes OBLIGATORIOS), pero la documentacion seguia diciendo solo
``docker compose up -d --build``: el stack de DESARROLLO, que acepta el
secreto JWT por defecto (publico). O sea: alguien que siguiera el README
para montar una sucursal desplegaba con un secreto publico, y sin saber
que existia ``FRONTEND_BASE_URL`` ni ``TRUSTED_PROXIES`` (que no estaban
ni en el ``.env.example``).

Lo que exige:
  1. que el README mentione ``docker-compose.prod.yml`` y el comando con
     los dos ficheros;
  2. que el README nombre las tres variables obligatorias (JWT_SECRET,
     FRONTEND_BASE_URL, CORS_ORIGINS) y advierta de que el
     ``docker compose up -d`` a secas es el stack de desarrollo;
  3. que el ``.env.example`` declare ``FRONTEND_BASE_URL`` y
     ``TRUSTED_PROXIES``.

Uso:
    python tools/verificar_readme_despliegue.py
    python tools/verificar_readme_despliegue.py --autoprueba
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
README = RAIZ / "README.md"
ENV_EXAMPLE = RAIZ / ".env.example"

#: La seccion del README donde se explica el despliegue en una sucursal.
#: Las menciones se comprueban **ahi**, no en el README entero: el README
#: ya decia ``alembic upgrade head`` en la seccion de DESARROLLO, asi
#: que mirar el README entero no hacia falta para que nadie se enterase de
#: que faltaba en la de produccion (T-185).
SECCION_PRODUCCION = "### Despliegue en una sucursal"

#: Lo que el README tiene que decir del despliegue en produccion.
MENCIONES_README = (
    "docker-compose.prod.yml",
    "JWT_SECRET",
    "FRONTEND_BASE_URL",
    "CORS_ORIGINS",
    # T-142 (2026-10-24): el SMTP es obligatorio en el compose de produccion.
    # Sin el, el despliegue arranca y los correos no salen nunca.
    "SMTP_HOST",
    # T-185 (2026-10-25): sin aplicar las migraciones, la base se queda
    # sin tablas y todas las peticiones devuelven 500 (medido).
    "alembic upgrade head",
    # T-185 (2026-10-25): sin el primer administrador, nadie puede entrar
    # (la aplicacion solo crea usuarios si ya hay un admin, y el seed se
    # niega a arrancar en produccion).
    "create_admin",
)


def _seccion_produccion(readme: str) -> str:
    """La parte del README que explica el despliegue en una sucursal."""
    if SECCION_PRODUCCION not in readme:
        return ""
    resto = readme.split(SECCION_PRODUCCION, 1)[1]
    # Se corta en el siguiente encabezado de nivel 2.
    for separador in ("\n## ", "\n### "):
        if separador in resto:
            resto = resto.split(separador, 1)[0]
            break
    return resto
#: Lo que el .env.example tiene que declarar.
MENCIONES_ENV = ("FRONTEND_BASE_URL", "TRUSTED_PROXIES")


def comprobar(readme: str, env_example: str) -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problemas: list[str] = []

    seccion = _seccion_produccion(readme)
    if not seccion:
        problemas.append(
            f"el README no tiene la seccion '{SECCION_PRODUCCION}': sin ella, "
            "nadie sabe como se despliega una sucursal"
        )
    for mencion in MENCIONES_README:
        if mencion not in seccion:
            problemas.append(
                f"el README no menciona '{mencion}' en la seccion de "
                "despliegue en una sucursal: sin eso, quien monte una "
                "sucursal sigue el camino de desarrollo (secreto JWT publico)"
            )

    # El aviso de que el compose a secas es el stack de desarrollo.
    if "desarrollo" not in readme.lower():
        problemas.append(
            "el README no dice que el stack por defecto es el de desarrollo"
        )

    for mencion in MENCIONES_ENV:
        if f"{mencion}=" not in env_example:
            problemas.append(
                f"el .env.example no declara '{mencion}': quien configura el "
                "entorno no ve la variable"
            )

    # T-81: el .env.example NO puede proponer un secreto de mentira: ese
    # fichero se copia a .env y el valor acababa en produccion (con el
    # filtro por comparacion exacta, "change-me-in-production-32-bytes-min"
    # se colaba).
    for linea in env_example.splitlines():
        limpia = linea.strip()
        if limpia.startswith("JWT_SECRET="):
            valor = limpia.split("=", 1)[1].strip()
            if valor:
                problemas.append(
                    f"el .env.example propone un JWT_SECRET de mentira "
                    f"({valor!r}): ese fichero se copia a .env y el valor "
                    "acaba en produccion (tokens de administrador "
                    "falsificables)"
                )

    return problemas


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta del README de despliegue:")
    fallos = 0
    readme_ok = (
        "### Despliegue en una sucursal (produccion)\n"
        "Para una sucursal:\n"
        "  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d\n"
        "  docker compose -f docker-compose.yml -f docker-compose.prod.yml "
        "exec backend alembic upgrade head\n"
        "  python -m app.scripts.create_admin\n"
        "Con JWT_SECRET, FRONTEND_BASE_URL, CORS_ORIGINS y SMTP_HOST (obligatorios).\n"
        "El stack por defecto es el de desarrollo.\n"
        "## Cuentas demo\n"
    )
    env_ok = (
        "FRONTEND_BASE_URL=https://app.ejemplo.es\n"
        "TRUSTED_PROXIES=10.0.0.0/8\n"
        "JWT_SECRET=\n"
    )

    casos = [
        ("todo correcto", readme_ok, env_ok, False),
        ("sin el compose de produccion", readme_ok.replace("docker-compose.prod.yml", ""), env_ok, True),
        ("sin JWT_SECRET", readme_ok.replace("JWT_SECRET", ""), env_ok, True),
        ("sin FRONTEND_BASE_URL", readme_ok.replace("FRONTEND_BASE_URL", ""), env_ok, True),
        ("sin CORS_ORIGINS", readme_ok.replace("CORS_ORIGINS", ""), env_ok, True),
        ("sin SMTP_HOST", readme_ok.replace("SMTP_HOST", ""), env_ok, True),
        ("sin el aviso de desarrollo", readme_ok.replace("desarrollo", ""), env_ok, True),
        (
            "sin las migraciones",
            readme_ok.replace("alembic upgrade head", ""),
            env_ok,
            True,
        ),
        (
            "sin el primer administrador",
            readme_ok.replace("create_admin", ""),
            env_ok,
            True,
        ),
        (
            "las migraciones solo en la seccion de desarrollo",
            readme_ok.replace("  docker compose -f docker-compose.yml -f "
                              "docker-compose.prod.yml exec backend alembic "
                              "upgrade head\n", "")
            + "\n## Desarrollo\nalembic upgrade head\n",
            env_ok,
            True,
        ),
        ("sin FRONTEND_BASE_URL en el .env.example", readme_ok, env_ok.replace("FRONTEND_BASE_URL", ""), True),
        ("sin TRUSTED_PROXIES en el .env.example", readme_ok, env_ok.replace("TRUSTED_PROXIES", ""), True),
        (
            "el .env.example con un secreto de mentira",
            readme_ok,
            env_ok.replace("JWT_SECRET=\n", "JWT_SECRET=change-me-in-production\n"),
            True,
        ),
    ]
    for nombre, readme, env, debe_fallar in casos:
        problemas = comprobar(readme, env)
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
        description="Comprueba que la documentacion dice como desplegar en produccion."
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
        readme = README.read_text(encoding="utf-8")
        env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    except OSError as error:
        print(f"  FALLO  no se puede leer la documentacion: {error}")
        return 1

    problemas = comprobar(readme, env_example)
    if problemas:
        for p in problemas:
            print(f"  FALLO  {p}")
        return 1
    print(
        "OK: el README dice como desplegar en produccion (compose de "
        "produccion + las cuatro variables obligatorias) y el .env.example "
        "declara FRONTEND_BASE_URL y TRUSTED_PROXIES."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
