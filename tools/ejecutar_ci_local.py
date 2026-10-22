"""Ejecuta un job del workflow de CI en local, leyendo el YAML.

El CI remoto no puede correr por la facturación de la cuenta, así que
este script lo ejecuta **tal y como está escrito**: lee
``.github/workflows/ci.yml``, saca los pasos ``run:`` del job indicado
y los ejecuta con su ``working-directory`` y sus variables de entorno.

No duplica los pasos (que se desincronizarían del workflow): lo que
comprueba de verdad es el cableado — rutas relativas, nombres de las
variables de entorno, orden de los pasos y que las órdenes existen.

Los pasos ``uses:`` (checkout, setup-python) se omiten: aquí el
repositorio ya está y las dependencias ya están instaladas.

Uso:
    python tools/ejecutar_ci_local.py                    # job 'integration'
    python tools/ejecutar_ci_local.py --job backend
    python tools/ejecutar_ci_local.py --all              # TODOS los jobs
    python tools/ejecutar_ci_local.py --list
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOW = RAIZ / ".github" / "workflows" / "ci.yml"

#: Bash de Git para Windows (el ``bash.exe`` del sistema es el de WSL y
#: puede no estar instalado).
BASH = [
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
]


def _bash() -> str | None:
    for ruta in BASH:
        if Path(ruta).is_file():
            return ruta
    return None


def _cargar_workflow() -> dict:
    import yaml

    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _pasos(job: dict) -> list[tuple[str, str, dict, bool]]:
    """(nombre, orden, env, continue_on_error) de cada paso con ``run:``."""
    salida: list[tuple[str, str, dict, bool]] = []
    for paso in job.get("steps", []):
        if "run" not in paso:
            continue
        salida.append((
            paso.get("name", "(sin nombre)"),
            paso["run"],
            paso.get("env", {}) or {},
            bool(paso.get("continue-on-error", False)),
        ))
    return salida


def _a_ipv4(valor: str) -> str:
    """Cambia ``localhost`` por ``127.0.0.1`` en las URLs de servicio.

    POR QUÉ (2026-10-21): en esta máquina (Windows) ``localhost``
    resuelve **primero a IPv6 (``::1``)**, y Docker publica PostgreSQL y
    Redis **sólo en IPv4**. El cliente de PostgreSQL prueba ``::1``
    primero, se queda esperando el *timeout* de conexión (8,4 s medidos
    para una conexión que con ``127.0.0.1`` tarda 1 ms) y sólo después
    prueba IPv4. Con los pasos del CI, que abren varias conexiones, eso
    convertía el job "integration" en un paso de minutos que parecía
    colgado.

    En un runner de Linux (el de GitHub) no pasa: ahí ``localhost`` es
    127.0.0.1. Por eso el cambio va **sólo en la réplica local**, no en
    el workflow.

    OJO con el patrón: la URL del CI es
    ``postgresql+psycopg://parking:parking@localhost:5432/...``, así que
    ``localhost`` va **detrás de la arroba**, no detrás de ``://``.
    """
    return re.sub(r"localhost(?=:\d)", "127.0.0.1", valor)


def _ejecutar_job(nombre_job: str, job: dict, bash: str, saltar: list[str]) -> tuple[int, int]:
    """Ejecuta un job. Devuelve (fallos, pasos tolerados)."""
    # El directorio de trabajo y las variables del job.
    cwd = RAIZ / job.get("defaults", {}).get("run", {}).get("working-directory", ".")
    entorno = {**os.environ, **(job.get("env", {}) or {})}
    entorno = {clave: _a_ipv4(valor) for clave, valor in entorno.items()}
    # Sin búfer: si un paso escribe en una tubería y el lector no está
    # pendiente, la salida se queda en el búfer del hijo y se pierde al
    # terminar. Con esto, lo que el paso ha escrito se ve ya.
    entorno["PYTHONUNBUFFERED"] = "1"
    # Git Bash (MSYS2) convierte las rutas POSIX que se pasan a un
    # programa Windows: ``/tmp/x.sh`` se convierte en
    # ``C:/Users/<usuario>/AppData/Local/Temp/x.sh``. En el CI (Linux)
    # eso NO pasa, así que sin esto la réplica local ejecutaría una
    # orden distinta que la del CI y daría falsos verdes (pasó con un
    # ``docker exec ... sh /tmp/verificar.sh`` que en realidad buscaba
    # el fichero en el temporal de Windows).
    entorno["MSYS_NO_PATHCONV"] = "1"
    entorno["MSYS2_ARG_CONV_EXCL"] = "*"

    print(f"\n{'=' * 70}\nJob '{nombre_job}' en {cwd}", flush=True)
    fallos = 0
    tolerados = 0
    for nombre, orden, env_paso, continue_on_error in _pasos(job):
        if any(m in nombre for m in saltar):
            print(f"\n=== {nombre}  (SALTADO)", flush=True)
            continue
        print(f"\n=== {nombre}", flush=True)
        entorno_paso = {**entorno, **env_paso}
        # El ``env`` del propio paso manda sobre el del job, así que
        # también hay que pasarlo por IPv4 (aquí es donde vive el
        # DATABASE_URL del job "integration").
        entorno_paso = {clave: _a_ipv4(valor) for clave, valor in entorno_paso.items()}
        resultado = subprocess.run(
            [bash, "-c", orden],
            cwd=str(cwd), env=entorno_paso, check=False,
        )
        if resultado.returncode != 0:
            if continue_on_error:
                # Así se comporta GitHub Actions: el paso queda marcado
                # como fallido, pero el job **sigue** y su conclusión no
                # cambia. Sin esto, el script declaraba el job rojo con
                # un paso que el workflow tolera a propósito.
                print(
                    f"    FALLO (código {resultado.returncode}) pero el paso es "
                    "continue-on-error: el job sigue"
                )
                tolerados += 1
                continue
            print(f"    FALLO (código {resultado.returncode})")
            fallos += 1
            break
    return fallos, tolerados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="integration")
    ap.add_argument("--all", action="store_true", help="Ejecutar TODOS los jobs del workflow")
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--saltar", action="append", default=[],
        help="No ejecutar los pasos cuyo nombre contenga este texto (repetible)",
    )
    args = ap.parse_args()

    workflow = _cargar_workflow()
    jobs = workflow.get("jobs", {})
    if args.list:
        for nombre, job in jobs.items():
            pasos = _pasos(job)
            print(f"{nombre}: {len(pasos)} paso(s) con 'run:'")
            for nombre_paso, _orden, _env, _coe in pasos:
                print(f"    - {nombre_paso}")
        return 0

    bash = _bash()
    if bash is None:
        print("No se ha encontrado bash (Git Bash). Instálalo o usa WSL.")
        return 2

    if args.all:
        # Todos los jobs, como en GitHub (donde corren en paralelo y uno
        # no para los demás). Al final, un resumen.
        #
        # OJO: todos los ``print`` van con ``flush=True``. Si el proceso
        # muere (o lo matan) a mitad, la salida que ya se ha producido
        # queda en el buffer y se pierde: sin ``flush``, el informe de
        # una ejecución que se cuelga es una pantalla en blanco, que es
        # justo cuando más falta hace.
        resultados: list[tuple[str, int, int]] = []
        for nombre_job, job in jobs.items():
            fallos, tolerados = _ejecutar_job(nombre_job, job, bash, args.saltar)
            resultados.append((nombre_job, fallos, tolerados))
        print("\n" + "=" * 70, flush=True)
        print("RESUMEN DEL CI LOCAL", flush=True)
        for nombre_job, fallos, tolerados in resultados:
            if fallos:
                estado = "ROJO"
            elif tolerados:
                estado = f"VERDE ({tolerados} paso(s) con continue-on-error)"
            else:
                estado = "VERDE"
            print(f"  {estado:<45} {nombre_job}", flush=True)
        total = sum(f for _n, f, _t in resultados)
        if total:
            print(f"\n{total} job(s) en rojo.", flush=True)
            return 1
        print("\nTodos los jobs pasan en local.", flush=True)
        return 0

    if args.job not in jobs:
        print(f"El workflow no tiene el job '{args.job}'. Hay: {list(jobs)}")
        return 2

    fallos, tolerados = _ejecutar_job(args.job, jobs[args.job], bash, args.saltar)

    print("\n" + "=" * 60)
    if tolerados:
        print(f"{tolerados} paso(s) fallaron con continue-on-error (el job sigue).")
    if fallos:
        print(f"El job '{args.job}' FALLARÍA en local.")
        return 1
    print(f"El job '{args.job}' pasa entero en local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
