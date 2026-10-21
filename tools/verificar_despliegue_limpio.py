"""Smoke test de un despliegue limpio: base vacía -> migrar -> sembrar -> servir.

Hasta ahora nadie había probado el camino entero de un despliegue
nuevo: las migraciones se ejecutaban en la base de QA (que ya estaba
sembrada) y el seed se ejecutaba a mano, pero nunca los tres juntos
sobre una base **vacía**. Un despliegue roto (una migración que no
aplica sobre el esquema limpio, o un seed que usa una columna que ya
no existe) sólo se habría visto en el primer cliente.

Qué hace, paso a paso:

1. Crea una base de datos VACÍA en el mismo servidor.
2. ``alembic upgrade head`` sobre ella: todas las migraciones, de cero.
3. ``python -m app.scripts.seed``: los datos demo.
4. Levanta la aplicación (uvicorn) contra esa base.
5. Comprueba que responde: login del admin y los listados principales.
6. Borra la base y para la aplicación.

Uso:
    DATABASE_URL=postgresql+psycopg://parking:parking@localhost:5432/solidapp_despliegue \\
        python tools/verificar_despliegue_limpio.py

El ``DATABASE_URL`` es el de la base que se quiere CREAR (se borra al
terminar). La conexión de mantenimiento usa el mismo servidor pero la
base ``postgres``.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
BASE_MAINTENANCE = "postgres"
ESPERA_SALUD_S = 45
PUERTO_APP = 8021
#: Timeout de cada peticion. El login hashea la contrasena (bcrypt), que
#: es lento: con la maquina cargada se puede pasar de 15 s.
TIEMPO_PETICION_S = 30


def _parte_de_url(url: str) -> tuple[str, str, str, str, int]:
    """(servidor, puerto, usuario, clave, base) de una URL de SQLAlchemy.

    Ojo con el separador: la contraseña puede llevar ``@`` (``user:p@ss@host``),
    así que el userinfo se separa por el **último** ``@``.
    """
    resto = url.split("://", 1)[-1]
    userinfo_host, _, ruta = resto.partition("/")
    userinfo, _, host = userinfo_host.rpartition("@")
    usuario, _, clave = userinfo.partition(":")
    servidor, _, p = host.partition(":")
    puerto = int(p) if p else 5432
    base = ruta.split("?", 1)[0]
    return servidor, puerto, usuario, clave, base


def _url_de_mantenimiento(url: str) -> str:
    """La misma URL pero apuntando a la base de mantenimiento."""
    servidor, puerto, usuario, clave, _base = _parte_de_url(url)
    credenciales = f"{usuario}:{clave}" if clave else usuario
    return f"postgresql://{credenciales}@{servidor}:{puerto}/{BASE_MAINTENANCE}"


def _recrear_base(url_mantenimiento: str, base: str) -> None:
    """Crea la base de datos vacía (borrando la anterior si estaba)."""
    import psycopg

    with psycopg.connect(url_mantenimiento, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{base}"')
        conn.execute(f'CREATE DATABASE "{base}"')


def _peticion(metodo: str, url: str, token: str | None = None, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO_PETICION_S) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _diagnostico_401(cuerpo: bytes) -> None:
    """Explica un 401 que en realidad es "Redis no está disponible".

    El ``AuditMiddleware`` va a *fail-closed* cuando Redis no responde (no
    se puede comprobar la blacklist de tokens, así que no se deja pasar
    ningún token) y devuelve 401 con este texto. Es un fallo de
    servicio, no de credenciales, y sin esta explicación el error parece
    de autenticación.
    """
    texto = cuerpo.decode("utf-8", "replace")
    if "no disponible" in texto:
        print("  AVISO: el 401 es por servicio, no por credenciales.")
        print("  El AuditMiddleware va a fail-closed cuando Redis no responde:")
        print("  para comprobar la blacklist de tokens hace falta Redis.")
        print("  Comprueba que REDIS_URL apunte a un Redis alcanzable desde aqui")
        print("  (en el CI es redis://localhost:6379/0, el del service container).")


def _esperar_salud(proc: subprocess.Popen, url: str) -> tuple[bool, str]:
    """Espera a que la aplicación esté lista.

    Devuelve (lista, motivo_del_fracaso). Si la aplicación responde
    **503** a ``/health/ready``, no se espera al timeout: ya se sabe que
    no va a estar lista, y el cuerpo dice qué dependencia falla.
    """
    for _ in range(ESPERA_SALUD_S * 2):
        if proc.poll() is not None:
            return False, "la aplicación se cerró antes de estar lista"
        try:
            estado, cuerpo = _peticion("GET", url)
            if estado == 200:
                return True, ""
            if estado == 503:
                return False, (
                    "la aplicación responde 503 (no está lista): "
                    f"{cuerpo.decode('utf-8', 'replace')[:300]}"
                )
        except OSError:
            pass
        time.sleep(0.5)
    return False, f"la aplicación no estuvo lista en {ESPERA_SALUD_S} s"


def main() -> int:
    url_objetivo = os.environ.get("DATABASE_URL")
    if not url_objetivo:
        print("Falta la variable DATABASE_URL (la base que se quiere crear).")
        return 2
    servidor, _puerto, _usuario, _clave, base = _parte_de_url(url_objetivo)
    print(f"Despliegue limpio sobre {servidor}/{base}")

    entorno = {**os.environ, "DATABASE_URL": url_objetivo}
    proc: subprocess.Popen | None = None
    try:
        # 1. Base vacía.
        print("  1/5. Creando la base vacía...")
        _recrear_base(_url_de_mantenimiento(url_objetivo), base)

        # 2. Migraciones desde cero.
        print("  2/5. Migrando de cero...")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(BACKEND), env=entorno, check=True,
        )

        # 3. Seed.
        print("  3/5. Sembrando los datos demo...")
        subprocess.run(
            [sys.executable, "-m", "app.scripts.seed"],
            cwd=str(BACKEND), env=entorno, check=True,
        )

        # 4. La aplicación, contra esa base.
        print("  4/5. Levantando la aplicación...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(PUERTO_APP),
             "--log-level", "warning"],
            cwd=str(BACKEND), env=entorno,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Se espera a /health/ready y no a /health: /health es liveness y
        # responde 200 aunque la base de datos o Redis estén caídos.
        lista, motivo = _esperar_salud(
            proc, f"http://127.0.0.1:{PUERTO_APP}/health/ready"
        )
        if not lista:
            print(f"  FALLO: {motivo}")
            if "503" in motivo:
                print("  La dependencia que falla está en el detalle de arriba")
                print("  (database o redis). En el CI, REDIS_URL apunta al")
                print("  service container: redis://localhost:6379/0")
            return 1

        # 5. La API responde con los datos del seed.
        print("  5/5. Comprobando la API...")
        base_api = f"http://127.0.0.1:{PUERTO_APP}/api/v1"
        estado, cuerpo = _peticion(
            "POST", f"{base_api}/auth/login",
            cuerpo={"email": "admin@solidapp.es", "password": "admin12345"},
        )
        if estado != 200:
            print(f"  FALLO: el login devolvió {estado}: {cuerpo[:200]!r}")
            _diagnostico_401(cuerpo)
            return 1
        token = json.loads(cuerpo)["access_token"]
        for ruta, cuenta in (("/parkings", 5), ("/plans", 3), ("/users", 4)):
            estado, cuerpo = _peticion("GET", f"{base_api}{ruta}", token=token)
            if estado != 200:
                print(f"  FALLO: {ruta} -> {estado}")
                _diagnostico_401(cuerpo)
                return 1
            datos = json.loads(cuerpo)
            n = len(datos) if isinstance(datos, list) else 1
            if n != cuenta:
                print(f"  FALLO: {ruta} devolvió {n} elementos (se esperaban {cuenta})")
                return 1
    except subprocess.CalledProcessError as exc:
        print(f"  FALLO: {exc.cmd[2:]} devolvió {exc.returncode}")
        if exc.stderr:
            print("  " + exc.stderr.strip()[-600:])
        return 1
    finally:
        if proc is not None:
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
        with contextlib.suppress(Exception):
            _recrear_base(_url_de_mantenimiento(url_objetivo), base)

    print("OK: despliegue limpio verificado (migraciones + seed + API).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
