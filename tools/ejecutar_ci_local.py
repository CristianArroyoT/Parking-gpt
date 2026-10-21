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
    python tools/ejecutar_ci_local.py --list
"""
from __future__ import annotations

import argparse
import os
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


def _pasos(job: dict) -> list[tuple[str, str, dict]]:
    """(nombre, orden, env) de cada paso con ``run:``."""
    salida: list[tuple[str, str, dict]] = []
    for paso in job.get("steps", []):
        if "run" not in paso:
            continue
        salida.append((
            paso.get("name", "(sin nombre)"),
            paso["run"],
            paso.get("env", {}) or {},
        ))
    return salida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="integration")
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
            for nombre_paso, _orden, _env in pasos:
                print(f"    - {nombre_paso}")
        return 0

    if args.job not in jobs:
        print(f"El workflow no tiene el job '{args.job}'. Hay: {list(jobs)}")
        return 2
    job = jobs[args.job]

    bash = _bash()
    if bash is None:
        print("No se ha encontrado bash (Git Bash). Instálalo o usa WSL.")
        return 2

    # El directorio de trabajo y las variables del job.
    cwd = RAIZ / job.get("defaults", {}).get("run", {}).get("working-directory", ".")
    entorno = {**os.environ, **(job.get("env", {}) or {})}

    print(f"Job '{args.job}' en {cwd}")
    fallos = 0
    for nombre, orden, env_paso in _pasos(job):
        if any(m in nombre for m in args.saltar):
            print(f"\n=== {nombre}  (SALTADO)")
            continue
        print(f"\n=== {nombre}")
        entorno_paso = {**entorno, **env_paso}
        resultado = subprocess.run(
            [bash, "-c", orden],
            cwd=str(cwd), env=entorno_paso, check=False,
        )
        if resultado.returncode != 0:
            print(f"    FALLO (código {resultado.returncode})")
            fallos += 1
            break

    print("\n" + "=" * 60)
    if fallos:
        print(f"El job '{args.job}' FALLARÍA en local.")
        return 1
    print(f"El job '{args.job}' pasa entero en local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
