"""Simulacro de restauración de backups, en un comando.

POR QUÉ (2026-10-21): la decisión D3 del plan fija que el procedimiento de
restauración se prueba **cada trimestre**, y hasta ahora eso era una
checklist en papel (``infra/backup/README.md``). Un backup sin restaurar
probado no es un backup, así que la prueba debería poder hacerse **cuando
haga falta**, no sólo en el trimestre.

Este script hace el simulacro completo, encadenando lo que ya existe:

1. ``infra/backup/simulacro.sh`` (dentro de la imagen de PostgreSQL):
   vuelca, comprueba que el ``.enc`` no es legible en claro, restaura en
   una base limpia y **compara el recuento de filas** entre el origen y la
   restauración.
2. ``alembic check`` contra la base restaurada: el esquema del backup
   tiene que ser **el que espera el código de hoy**. Es el fallo que de
   verdad duele: un backup de hace tres meses, restaurado, y la app no
   arranca porque le falta una columna.
3. El backend arrancado contra la base restaurada, con ``/health`` en 200.
4. Se borra la base de prueba.

La ejecución del backup y de la restauración necesita ``pg_dump``,
``pg_restore`` y ``openssl``: el host no los tiene, pero la imagen de
PostgreSQL sí (y su ``pg_dump`` es **la misma versión** que el servidor,
que es lo que evita el "unsupported version" al restaurar). Por eso el
simulacro corre dentro de un contenedor.

Uso:
    python tools/verificar_backup.py
    python tools/verificar_backup.py --red parking_default --db parking

Códigos de salida: 0 si el simulacro pasa, 1 si falla.
"""
from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKUP_DIR = RAIZ / "infra" / "backup"
IMAGEN_PG = "postgis/postgis:16-3.4"
CONTENEDOR_BACKEND = "parking-backend-1"


def _consola(texto: str) -> str:
    """Texto que la consola de Windows puede imprimir (cp1252)."""
    codificacion = getattr(sys.stdout, "encoding", None) or "utf-8"
    return texto.encode(codificacion, "replace").decode(codificacion, "replace")


def _log(mensaje: str) -> None:
    print(_consola(mensaje), flush=True)


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    """Ejecuta ``docker`` capturando stdout y stderr.

    OJO: la captura es **obligatoria**. Sin ella, ``resultado.stdout`` es
    ``None`` (la salida se escribe directamente en la consola) y cualquier
    comprobación sobre ella falla sin decir por qué.
    """
    kwargs.setdefault("capture_output", True)
    return subprocess.run(
        ["docker", *args], check=False, text=True,
        encoding="utf-8", errors="replace", **kwargs,
    )


def _simulacro(red: str, base: str, destino: Path, secrets: Path) -> tuple[bool, str]:
    """Corre ``simulacro.sh`` dentro de la imagen de PostgreSQL."""
    resultado = _docker(
        "run", "--rm",
        "--network", red,
        "-v", f"{BACKUP_DIR}:/backup:ro",
        "-v", f"{destino}:/backups",
        "-v", f"{secrets}:/secrets:ro",
        "-e", "PGHOST=db",
        "-e", "PGPORT=5432",
        "-e", "PGUSER=parking",
        "-e", "PGPASSWORD=parking",
        "-e", f"PGDATABASE={base}",
        "-e", "BACKUP_DIR=/backups",
        "-e", "BACKUP_PASSPHRASE_FILE=/secrets/backup.pass",
        "-e", f"TARGET_DB={base}_simulacro",
        IMAGEN_PG,
        "bash", "/backup/simulacro.sh",
    )
    salida = (resultado.stdout or "") + (resultado.stderr or "")
    return resultado.returncode == 0, salida


def _alembic_check(base: str) -> tuple[bool, str]:
    """``alembic check`` contra la base restaurada: ¿el esquema sirve?"""
    url = f"postgresql+psycopg://parking:parking@db:5432/{base}"
    resultado = _docker(
        "exec",
        "-e", f"DATABASE_URL={url}",
        "-e", f"ASYNC_DATABASE_URL=postgresql+asyncpg://parking:parking@db:5432/{base}",
        CONTENEDOR_BACKEND,
        "alembic", "check",
    )
    salida = (resultado.stdout or "") + (resultado.stderr or "")
    if resultado.returncode == 0:
        return True, "el esquema restaurado coincide con los modelos"
    return False, salida.strip().splitlines()[-1][:160] if salida.strip() else "alembic check falló"


def _backend_arranca(base: str) -> tuple[bool, str]:
    """Arranca el backend contra la base restaurada y comprueba /health."""
    url = f"postgresql+psycopg://parking:parking@db:5432/{base}"
    # El puerto 8099 es interno del contenedor: se comprueba desde dentro.
    # OJO: ``sh -lc`` (shell de login) reinicia el PATH y se queda sin el
    # venv, donde vive el script ``uvicorn``. Con ``python -m uvicorn``
    # no depende del PATH.
    _docker(
        "exec", "-d",
        "-e", f"DATABASE_URL={url}",
        "-e", f"ASYNC_DATABASE_URL=postgresql+asyncpg://parking:parking@db:5432/{base}",
        CONTENEDOR_BACKEND,
        "sh", "-c",
        "python -m uvicorn app.main:app --host 127.0.0.1 --port 8099 --log-level warning",
    )
    inicio = time.time()
    ok = False
    detalle = "el backend no llegó a responder en 40 s"
    while time.time() - inicio < 40:
        time.sleep(1.0)
        resultado = _docker(
            "exec", CONTENEDOR_BACKEND,
            "python", "-c",
            "import urllib.request;"
            "print(urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=3).read().decode())",
        )
        if resultado.returncode == 0 and '"status"' in (resultado.stdout or ""):
            ok = True
            detalle = (resultado.stdout or "").strip()[:120]
            break
    # Se mata el uvicorn temporal (el proceso principal del contenedor no se toca).
    _docker("exec", CONTENEDOR_BACKEND, "sh", "-c", "pkill -f 'port 8099' || true")
    return ok, detalle


def _borrar_base(base: str) -> None:
    _docker(
        "exec", "parking-db-1", "psql", "-U", "parking", "-d", "postgres",
        "-c", f'DROP DATABASE IF EXISTS "{base}";',
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", default="parking_default", help="red de Docker del stack")
    ap.add_argument("--db", default="parking", help="base de datos de la que se hace el backup")
    args = ap.parse_args()

    base_restore = f"{args.db}_simulacro"
    temporal = Path(tempfile.mkdtemp(prefix="solidapp-simulacro-"))
    secretos = temporal / "secrets"
    secretos.mkdir()
    # Passphrase aleatoria, sólo para este simulacro: no toca la real.
    # Se genera con ``secrets`` de la biblioteca estándar (el host no tiene
    # ``openssl``; el contenedor sí, pero la clave no necesita salir de aquí).
    (secretos / "backup.pass").write_text(
        secrets.token_urlsafe(32), encoding="utf-8"
    )
    try:
        (secretos / "backup.pass").chmod(0o600)
    except OSError:
        pass

    _log("Simulacro de restauracion de backups (T-12)")
    _log("=" * 70)
    inicio = time.time()
    # El directorio de volcados tiene que existir ANTES: Docker lo montaría
    # como root si no existiera, y luego no se podría limpiar desde el host.
    destino = temporal / "backups"
    destino.mkdir()
    ok, salida = _simulacro(args.red, args.db, destino, secretos)

    # La salida del simulacro se imprime aunque falle: es el diagnostico.
    for linea in salida.splitlines():
        if linea.strip():
            _log("  " + linea)
    if not ok:
        _log("")
        _log("FALLO: el simulacro (volcado + restauracion) no paso.")
        _borrar_base(base_restore)
        shutil.rmtree(temporal, ignore_errors=True)
        return 1

    _log("")
    _log("Comprobando que el esquema restaurado es el que espera el codigo de hoy...")
    ok_esquema, detalle = _alembic_check(base_restore)
    _log(f"  {'OK' if ok_esquema else 'FALLO'}: {detalle}")
    if not ok_esquema:
        _borrar_base(base_restore)
        shutil.rmtree(temporal, ignore_errors=True)
        return 1

    _log("Arrancando el backend contra la base restaurada...")
    ok_app, detalle = _backend_arranca(base_restore)
    _log(f"  {'OK' if ok_app else 'FALLO'}: {detalle}")

    _borrar_base(base_restore)
    shutil.rmtree(temporal, ignore_errors=True)

    _log("=" * 70)
    if ok_app:
        _log(f"SIMULACRO CORRECTO en {time.time() - inicio:.0f} s "
             "(volcado, cifrado, restauracion, esquema y arranque de la app).")
        return 0
    _log("FALLO: el backend no arranca contra la base restaurada.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
