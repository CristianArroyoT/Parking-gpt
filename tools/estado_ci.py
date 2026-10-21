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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="owner/repo (por defecto, el del remoto)")
    args = ap.parse_args()

    repo = args.repo or _gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()

    runs = _api(f"repos/{repo}/actions/runs?per_page=5")["workflow_runs"]
    if not runs:
        print("No hay ninguna ejecucion del CI.")
        return ROJO_DE_CODIGO

    ultimo = runs[0]
    jobs = _api(f"repos/{repo}/actions/runs/{ultimo['id']}/jobs")["jobs"]

    lineas = [
        f"Repositorio: {repo}",
        f"Ultimo run: {ultimo['display_title']}",
        f"  id {ultimo['id']} | rama {ultimo['head_branch']} | "
        f"{ultimo['status']} / {ultimo['conclusion']}",
        f"  {ultimo['html_url']}",
        "",
        f"Jobs ({len(jobs)}):",
    ]
    sin_pasos = 0
    for job in jobs:
        pasos = job.get("steps") or []
        ok = job.get("conclusion") == "success"
        lineas.append(f"  [{'OK ' if ok else 'ROJO'}] {job['name']} ({len(pasos)} paso/s)")
        if not pasos and not ok:
            sin_pasos += 1

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
        _informe(lineas)
        return RECHAZADO_POR_LA_CUENTA

    rojos = [j for j in jobs if j.get("conclusion") not in ("success", "skipped", None)]
    if rojos:
        lineas += ["", f"DIAGNOSTICO: {len(rojos)} job(s) en rojo ejecutando pasos: es el codigo."]
        for job in rojos:
            for paso in job.get("steps") or []:
                if paso.get("conclusion") not in ("success", "skipped", None):
                    lineas.append(f"  {job['name']} -> {paso['name']} ({paso.get('conclusion')})")
        _informe(lineas)
        return ROJO_DE_CODIGO

    lineas += ["", "El CI de main esta EN VERDE."]
    _informe(lineas)
    return VERDE


if __name__ == "__main__":
    raise SystemExit(main())
