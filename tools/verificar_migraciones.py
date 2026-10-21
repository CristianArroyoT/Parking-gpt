"""Comprueba que las migraciones y los modelos cuentan la misma historia.

Qué hace, sobre una base de datos **VACÍA**:

1. La crea (con ``psycopg``, que ya es dependencia del backend: así el
   paso del CI no depende de que el cliente ``psql`` esté en la imagen).
2. ``alembic upgrade head``: todas las migraciones, de cero.
3. ``alembic check``: el esquema resultante tiene que coincidir con los
   modelos. Si no coinciden, el comando falla.
4. Borra la base.

Por qué esto importa: los tests crean el esquema con
``Base.metadata.create_all``, es decir, **no ejecutan las migraciones**.
Una migración rota sólo se habría descubierto en producción, en el
primer despliegue de una sucursal.

Uso:
    DATABASE_URL=postgresql+psycopg://parking:parking@localhost:5432/solidapp_migraciones \\
        python tools/verificar_migraciones.py
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
BASE_MAINTENANCE = "postgres"


def _parte_de_url(url: str) -> tuple[str, int, str, str, str]:
    """(servidor, puerto, usuario, clave, base) de una URL de SQLAlchemy."""
    resto = url.split("://", 1)[-1]
    userinfo_host, _, ruta = resto.partition("/")
    userinfo, _, host = userinfo_host.rpartition("@")
    usuario, _, clave = userinfo.partition(":")
    servidor, _, p = host.partition(":")
    puerto = int(p) if p else 5432
    return servidor, puerto, usuario, clave, ruta.split("?", 1)[0]


def _url_de_mantenimiento(url: str) -> str:
    servidor, puerto, usuario, clave, _base = _parte_de_url(url)
    credenciales = f"{usuario}:{clave}" if clave else usuario
    return f"postgresql://{credenciales}@{servidor}:{puerto}/{BASE_MAINTENANCE}"


def _recrear_base(url_mantenimiento: str, base: str) -> None:
    import psycopg

    with psycopg.connect(url_mantenimiento, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{base}"')
        conn.execute(f'CREATE DATABASE "{base}"')


def main() -> int:
    url_objetivo = os.environ.get("DATABASE_URL")
    if not url_objetivo:
        print("Falta la variable DATABASE_URL (la base que se quiere crear).")
        return 2
    _servidor, _puerto, _usuario, _clave, base = _parte_de_url(url_objetivo)
    entorno = {**os.environ, "DATABASE_URL": url_objetivo}

    print(f"Migraciones sobre una base vacía ({base})...")
    try:
        _recrear_base(_url_de_mantenimiento(url_objetivo), base)

        print("  alembic upgrade head")
        resultado = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(BACKEND), env=entorno, check=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if resultado.returncode != 0:
            print(resultado.stdout[-2000:])
            print(resultado.stderr[-2000:])
            print("  FALLO: las migraciones no se aplican sobre una base vacía.")
            return 1

        print("  alembic check")
        resultado = subprocess.run(
            [sys.executable, "-m", "alembic", "check"],
            cwd=str(BACKEND), env=entorno, check=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if resultado.returncode != 0:
            print(resultado.stdout[-3000:])
            print(resultado.stderr[-2000:])
            print("  FALLO: el esquema migrado NO coincide con los modelos.")
            return 1
        print("  OK: el esquema migrado coincide con los modelos.")
    finally:
        with contextlib.suppress(Exception):
            _recrear_base(_url_de_mantenimiento(url_objetivo), base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
