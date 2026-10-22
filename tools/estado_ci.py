"""Estado del CI de GitHub Actions sobre ``main``.

Responde a una pregunta concreta: **¿el CI remoto está en verde o no, y
por qué no?** Es la comprobación que queda pendiente por la facturación de
la cuenta, asi que interesa distinguir tres casos:

1. **En verde**: todos los jobs del ultimo run acabaron en ``success``.
2. **En rojo de verdad**: algun job ejecuto pasos y uno fallo. Eso es un
   defecto del codigo y hay que arreglarlo.
3. **Rechazado antes de arrancar**: los jobs terminan en ``failure`` **sin
   un solo paso**. No es el codigo: es la cuenta (pago pendiente o limite
   de gasto excedido). Los runners de GitHub rechazan el job en el
   momento de encolarlo.

El caso 3 es el que se ha visto durante todo el 2026-10-21, asi que el
script lo distingue explicitamente en vez de decir "el CI falla".

El informe completo se escribe en un fichero **UTF-8** (la consola de
Windows se come los acentos y los simbolos) y la consola recibe un
resumen sin caracteres problematicos.

Uso:
    python tools/estado_ci.py
    python tools/estado_ci.py --repo CristianArroyoT/Parking-gpt
    python tools/estado_ci.py --rama mi-rama
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

#: Fichero del informe (UTF-8). Va al .gitignore: es un artefacto.
INFORME = Path("tools/_informe_ci.txt")

#: Codigos de salida.
VERDE = 0
ROJO_DE_CODIGO = 1
RECHAZADO_POR_LA_CUENTA = 2
#: El run todavia no ha terminado: no se puede afirmar nada (y desde luego
#: no es "verde"). Antes este caso caia en el "verde" y era un falso verde.
EN_CURSO = 3


def _gh(*args: str) -> str:
    """Ejecuta ``gh`` y devuelve su salida; si falla, propaga el error.

    OJO: la salida de ``gh`` es **UTF-8** y en esta maquina la consola usa
    cp1252, asi que hay que forzar la decodificacion. Con
    ``text=True`` (que usa la codificacion del sistema) el ``gh api`` de
    un repositorio con acentos en los titulos de commit revienta con un
    ``UnicodeDecodeError``.
    """
    resultado = subprocess.run(
        ["gh", *args],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if resultado.returncode != 0:
        raise SystemExit(
            f"gh {' '.join(args)} fallo (codigo {resultado.returncode}):\n"
            f"{(resultado.stderr or '').strip()}"
        )
    return resultado.stdout


def _api(ruta: str) -> dict | list:
    return json.loads(_gh("api", ruta))


def _informe(lineas: list[str]) -> None:
    """Escribe el informe en UTF-8 y muestra un resumen en la consola."""
    INFORME.parent.mkdir(parents=True, exist_ok=True)
    INFORME.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    # En la consola, ASCII puro: la de Windows (cp1252) no representa
    # bien los acentos ni los simbolos, y un informe ilegible no sirve.
    for linea in lineas:
        ascii_ = linea.encode("ascii", "replace").decode("ascii")
        print(ascii_)


def _clasificar(run: dict, jobs: list[dict]) -> tuple[int, list[str]]:
    """(codigo de salida, lineas del informe) a partir del run y sus jobs.

    OJO: la lógica está **separada** de la API para que se pueda probar
    con casos de mentira (ver ``_autoprueba``). Un script que sólo dice
    "el CI falla" sin poder verse fallar es una línea de texto, no una
    puerta.
    """
    lineas = [
        f"Ultimo run: {run.get('display_title', '')}",
        f"  id {run.get('id')} | rama {run.get('head_branch')} | "
        f"{run.get('status')} / {run.get('conclusion')}",
        f"  commit {run.get('head_sha', '')[:12]}",
        f"  {run.get('html_url', '')}",
        "",
        f"Jobs ({len(jobs)}):",
    ]
    sin_pasos = 0
    for job in jobs:
        pasos = job.get("steps") or []
        ok = job.get("conclusion") == "success"
        lineas.append(f"  [{'OK ' if ok else 'ROJO'}] {job.get('name')} ({len(pasos)} paso/s)")
        if not pasos and not ok:
            sin_pasos += 1

    # Un run que no ha terminado NO es verde. Antes, un run recien creado
    # (sin jobs todavia) caia en el "verde": un falso verde justo en el
    # momento en que se decide si el ultimo criterio del plan esta
    # cumplido.
    if run.get("status") != "completed":
        lineas += [
            "",
            f"DIAGNOSTICO: el run sigue en curso ({run.get('status')}).",
            "No se puede afirmar nada todavia: no cuenta como verde.",
        ]
        return EN_CURSO, lineas

    if jobs and sin_pasos == len(jobs):
        lineas += [
            "",
            "DIAGNOSTICO: todos los jobs terminan en 'failure' SIN ejecutar un solo paso.",
            "Eso no es el codigo: GitHub rechaza el job antes de asignarle un runner.",
            "Lo mas probable es la cuenta: pago pendiente o limite de gasto excedido",
            "(Billing & plans en https://github.com/settings/billing/actions).",
            "Los jobs del workflow estan replicados y verificados en local:",
            "    python tools/ejecutar_ci_local.py --job backend",
            "    python tools/ejecutar_ci_local.py --job integration",
        ]
        return RECHAZADO_POR_LA_CUENTA, lineas

    rojos = [j for j in jobs if j.get("conclusion") not in ("success", "skipped", None)]
    if rojos:
        lineas += ["", f"DIAGNOSTICO: {len(rojos)} job(s) en rojo ejecutando pasos: es el codigo."]
        for job in rojos:
            for paso in job.get("steps") or []:
                if paso.get("conclusion") not in ("success", "skipped", None):
                    lineas.append(
                        f"  {job.get('name')} -> {paso.get('name')} ({paso.get('conclusion')})"
                    )
        return ROJO_DE_CODIGO, lineas

    if not jobs:
        lineas += [
            "",
            "DIAGNOSTICO: el run no tiene jobs. No se puede afirmar que este en verde.",
        ]
        return EN_CURSO, lineas

    lineas += ["", "El CI de main esta EN VERDE."]
    return VERDE, lineas


def _autoprueba() -> int:
    """Comprueba que la clasificación sigue distinguiendo los tres casos.

    Esta herramienta decide si el **último criterio del plan** está
    cumplido (los 4 checks del CI sobre ``main`` en SUCCESS). Si clasificara
    mal, el plan se cerraría (o se dejaría abierto) por un motivo falso.
    """
    fallos = 0

    def _job(nombre: str, conclusion: str, pasos: int) -> dict:
        return {
            "name": nombre,
            "conclusion": conclusion,
            "steps": [{"name": f"paso{i}", "conclusion": "success"} for i in range(pasos)],
        }

    run_ok = {
        "id": 1, "display_title": "prueba", "head_branch": "main",
        "status": "completed", "conclusion": "success", "head_sha": "a" * 40,
        "html_url": "http://ejemplo",
    }

    # 1. Todo en verde -> VERDE.
    codigo, _ = _clasificar(run_ok, [_job("Backend", "success", 3) for _ in range(4)])
    if codigo != VERDE:
        print(f"  FALLO: 4 jobs en verde no se han clasificado como VERDE ({codigo})")
        fallos += 1
    else:
        print("  OK: 4 jobs en verde -> VERDE")

    # 2. Un job en rojo ejecutando pasos -> ROJO_DE_CODIGO.
    jobs = [_job("Backend", "success", 3) for _ in range(3)]
    jobs.append(_job("Frontend", "failure", 2))
    codigo, _ = _clasificar({**run_ok, "conclusion": "failure"}, jobs)
    if codigo != ROJO_DE_CODIGO:
        print(f"  FALLO: un job en rojo no se ha clasificado como ROJO ({codigo})")
        fallos += 1
    else:
        print("  OK: un job en rojo con pasos -> ROJO_DE_CODIGO")

    # 3. Todos en failure SIN pasos -> RECHAZADO_POR_LA_CUENTA.
    jobs = [_job(f"Job{i}", "failure", 0) for i in range(4)]
    codigo, _ = _clasificar({**run_ok, "conclusion": "failure"}, jobs)
    if codigo != RECHAZADO_POR_LA_CUENTA:
        print(f"  FALLO: jobs rechazados sin pasos no se han clasificado bien ({codigo})")
        fallos += 1
    else:
        print("  OK: 4 jobs en failure sin pasos -> RECHAZADO_POR_LA_CUENTA")

    # 4. Un run EN CURSO sin jobs -> NO verde. Este era el falso verde.
    codigo, _ = _clasificar({**run_ok, "status": "in_progress", "conclusion": None}, [])
    if codigo == VERDE:
        print("  FALLO: un run en curso se ha clasificado como VERDE (falso verde)")
        fallos += 1
    elif codigo != EN_CURSO:
        print(f"  FALLO: un run en curso debería dar EN_CURSO ({codigo})")
        fallos += 1
    else:
        print("  OK: un run en curso sin jobs -> EN_CURSO (no verde)")

    # 5. Un run completado pero sin jobs tampoco es verde.
    codigo, _ = _clasificar(run_ok, [])
    if codigo == VERDE:
        print("  FALLO: un run sin jobs se ha clasificado como VERDE")
        fallos += 1
    else:
        print("  OK: un run sin jobs no es VERDE")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la clasificacion del CI sigue distinguiendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="owner/repo (por defecto, el del remoto)")
    ap.add_argument("--rama", default="main", help="rama a mirar (por defecto, main)")
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la clasificacion sigue distinguiendo")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    repo = args.repo or _gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()

    runs = _api(f"repos/{repo}/actions/runs?branch={args.rama}&per_page=5")["workflow_runs"]
    if not runs:
        print(f"No hay ninguna ejecucion del CI en la rama '{args.rama}'.")
        return ROJO_DE_CODIGO

    ultimo = runs[0]
    jobs = _api(f"repos/{repo}/actions/runs/{ultimo['id']}/jobs")["jobs"]

    codigo, lineas = _clasificar(ultimo, jobs)
    _informe([f"Repositorio: {repo}", f"Rama: {args.rama}", ""] + lineas)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
