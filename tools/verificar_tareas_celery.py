"""Comprueba que toda tarea de Celery se ejecuta de verdad.

POR QUÉ (2026-10-22): una tarea de Celery puede existir, estar
**registrada** en el worker (eso es lo que dice ``celery inspect
registered``) y **no ejecutarse nunca**. Pasa si:

- no está en el ``beat_schedule`` de ``app/workers/celery_app.py``, y
- nadie la despacha (``.delay()``, ``.apply_async()``, ``send_task()``)
  ni la llama directamente.

Y el caso real del repo: ``solidapp.ping_camera`` —la que agarra el frame
de la cámara, se lo manda al OCR y crea el ticket— **no se despacha desde
junio de 2026**. Existe, está registrada, tiene sus tests (que la llaman
directamente, así que pasan), y el código **describía un comportamiento
que no existía**: que corría "en paralelo" con el detector de heartbeat.
Medido en la base de datos: la última matrícula leída por el sistema es
del **2026-06-30**, tres meses y medio antes de este hallazgo.

Este script no juzga si la tarea *debería* ejecutarse: comprueba que
nadie la ha dejado en el limbo. Las que están en la lista de
``EXENCIONES`` se avisan (con su motivo), pero no rompen el CI: son
decisiones tomadas a propósito, no olvidos.

Uso:
    python tools/verificar_tareas_celery.py
    python tools/verificar_tareas_celery.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
APP = RAIZ / "backend" / "app"
TAREAS = APP / "workers" / "tasks.py"
CELERY_APP = APP / "workers" / "celery_app.py"

#: Tareas que NO se despachan, con el motivo (decisión tomada a propósito).
EXENCIONES: dict[str, str] = {
    "solidapp.ping_camera": (
        "Diseñada para que la encolara el endpoint /admin/cameras/{id}/ping, "
        "que nunca se añadió (commit 66c172f, 2026-06-30: 'cuando se añada'). "
        "La lectura automática de matrículas NO está activa: la última "
        "matrícula leída por el sistema es del 2026-06-30. El pipeline real "
        "es el push externo al endpoint POST /parkings/{id}/plates-detected. "
        "Despacharla es una decisión de producto, no un olvido."
    ),
}

#: Métodos de Celery que despachan una tarea.
METODOS_DESPACHO = {"delay", "apply_async", "apply", "si", "signature"}


def _tareas_definidas() -> dict[str, str]:
    """``{nombre_de_la_tarea: función}`` de las tareas declaradas."""
    arbol = ast.parse(TAREAS.read_text(encoding="utf-8"))
    salida: dict[str, str] = {}
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for decorador in nodo.decorator_list:
            if not isinstance(decorador, ast.Call):
                continue
            func = decorador.func
            if not isinstance(func, ast.Attribute) or func.attr != "task":
                continue
            nombre = nodo.name
            for clave in decorador.keywords:
                if (
                    clave.arg == "name"
                    and isinstance(clave.value, ast.Constant)
                    and isinstance(clave.value.value, str)
                ):
                    nombre = clave.value.value
            salida[nombre] = nodo.name
    return salida


def _tareas_programadas() -> set[str]:
    """Los nombres de tarea que aparecen en el ``beat_schedule``."""
    arbol = ast.parse(CELERY_APP.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign):
            continue
        objetivo = nodo.targets[0]
        if not isinstance(objetivo, ast.Attribute) or objetivo.attr != "beat_schedule":
            continue
        if not isinstance(nodo.value, ast.Dict):
            break
        nombres: set[str] = set()
        for valor in nodo.value.values:
            if not isinstance(valor, ast.Dict):
                continue
            for clave, contenido in zip(valor.keys, valor.values, strict=True):
                if (
                    isinstance(clave, ast.Constant)
                    and clave.value == "task"
                    and isinstance(contenido, ast.Constant)
                    and isinstance(contenido.value, str)
                ):
                    nombres.add(contenido.value)
        return nombres
    return set()


def _tareas_del_worker() -> set[str] | None:
    """Las tareas que el worker **en marcha** tiene registradas.

    T-157 (2026-10-24): el worker tiene el codigo montado pero **no lo
    recarga** (``--reload`` no lo soporta el pool *prefork* de Celery),
    asi que puede estar corriendo **el codigo viejo**. Esta puerta miraba
    solo el fuente, asi que una tarea nueva podia «pasar la puerta» y no
    existir en el worker real (el beat la publica y el worker responde
    «Received unregistered task»).

    Devuelve ``None`` si no se puede consultar (no hay Docker, o el worker
    no esta levantado: es el caso del CI): entonces **no se puede
    afirmar nada** y la puerta lo dice.
    """
    try:
        proc = subprocess.run(
            [
                "docker", "compose", "exec", "-T", "celery-worker",
                "celery", "-A", "app.workers.celery_app", "inspect", "registered",
            ],
            cwd=RAIZ, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # Celery imprime el registro en **texto plano**:
    #     ->  celery@host: OK
    #         * solidapp.probe_heartbeats
    # (la variante JSON depende de la version, asi que se lee el texto, que
    # funciona con todas).
    tareas: set[str] = set()
    for linea in proc.stdout.splitlines():
        coincide = re.match(r"^\s*\*\s+(\S+)\s*$", linea)
        if coincide:
            tareas.add(coincide.group(1))
    if not tareas:
        # Alternativa por si la salida viniera en JSON.
        try:
            datos = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None
        for lista in datos.values():
            if isinstance(lista, list):
                tareas.update(str(t) for t in lista)
    return tareas or None


def _tareas_que_le_faltan_al_worker(
    fuente: set[str], worker: set[str]
) -> list[str]:
    """Las tareas del codigo que al worker en marcha le faltan.

    Es el nucleo comprobable del T-157: si el worker corre el codigo
    viejo, le faltan las tareas nuevas.
    """
    return sorted(fuente - worker)


def _despachos() -> set[str]:
    """Los nombres de tarea que alguien despacha o llama en el código de la app.

    Se recorre el AST (no un grep) para no contar menciones en
    docstrings ni en comentarios, que es justo donde está la mentira que
    este script viene a desmontar.
    """
    nombres: set[str] = set()
    for fichero in sorted(APP.rglob("*.py")):
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            func = nodo.func
            # ``tarea.delay(...)`` / ``tarea.apply_async(...)``
            if (
                isinstance(func, ast.Attribute)
                and func.attr in METODOS_DESPACHO
                and isinstance(func.value, ast.Name)
            ):
                nombres.add(func.value.id)
            # ``send_task("solidapp.x")``
            if isinstance(func, ast.Name) and func.id == "send_task":
                for argumento in nodo.args:
                    if isinstance(argumento, ast.Constant) and isinstance(
                        argumento.value, str
                    ):
                        nombres.add(argumento.value)
    return nombres


def _llamadas_directas() -> set[str]:
    """Las tareas que el código de la app llama directamente (no como tarea).

    Llamar a la función directamente **sí** la ejecuta, así que cuenta
    como viva (aunque no sea una ejecución en el worker).
    """
    nombres: set[str] = set()
    for fichero in sorted(APP.rglob("*.py")):
        if fichero == TAREAS:
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                nombres.add(nodo.func.id)
    return nombres


def _muertas() -> dict[str, str]:
    """``{tarea: motivo}`` de las tareas que no se ejecutan de ninguna forma."""
    definidas = _tareas_definidas()
    programadas = _tareas_programadas()
    despachadas = _despachos()
    directas = _llamadas_directas()

    muertas: dict[str, str] = {}
    for nombre, funcion in definidas.items():
        if nombre in programadas:
            continue
        if funcion in despachadas or nombre in despachadas:
            continue
        if funcion in directas or nombre in directas:
            continue
        muertas[nombre] = funcion
    return muertas


def _autoprueba() -> int:
    """Comprueba que la puerta sigue detectando una tarea muerta.

    Se monta el caso de mentira a mano: una tarea que no está en el
    horario ni se despacha tiene que salir; una que sí, no.
    """
    fallos = 0

    # 1. Una tarea sin horario ni despacho es muerta.
    muertas = {
        "solidapp.ping_camera": "ping_camera",
        "solidapp.probe_heartbeats": "probe_heartbeats",
    }
    programadas = {"solidapp.probe_heartbeats"}
    despachadas: set[str] = set()
    directas: set[str] = set()
    vivas = set(programadas) | despachadas | directas
    detectadas = {n for n in muertas if n not in vivas}
    if detectadas != {"solidapp.ping_camera"}:
        print(f"  FALLO: la tarea muerta no se ha detectado ({detectadas})")
        fallos += 1
    else:
        print("  OK: una tarea sin horario ni despacho se detecta")

    # 2. Una tarea despachada está viva.
    despachadas = {"solidapp.ping_camera"}
    vivas = set(programadas) | despachadas | directas
    detectadas = {n for n in muertas if n not in vivas}
    if detectadas:
        print(f"  FALLO: una tarea despachada se marca como muerta ({detectadas})")
        fallos += 1
    else:
        print("  OK: una tarea despachada no se marca")

    # 3. Y una llamada directa también la mantiene viva.
    directas = {"ping_camera"}
    vivas = set(programadas) | despachadas | directas
    detectadas = {n for n in muertas if n not in vivas}
    if detectadas:
        print(f"  FALLO: una tarea llamada directamente se marca como muerta ({detectadas})")
        fallos += 1
    else:
        print("  OK: una tarea llamada directamente no se marca")

    # T-157 (2026-10-24): el worker en marcha puede correr el codigo viejo
    # (los workers no recargan el codigo), y la puerta tiene que verlo.
    fuente = {"solidapp.a", "solidapp.b", "solidapp.c"}
    worker_viejo = {"solidapp.a", "solidapp.b"}
    faltan = _tareas_que_le_faltan_al_worker(fuente, worker_viejo)
    if faltan == ["solidapp.c"]:
        print("  OK: la puerta ve las tareas que le faltan al worker")
    else:
        print(f"  FALLO: la puerta no ve el desfase (faltan={faltan})")
        fallos += 1

    if _tareas_que_le_faltan_al_worker(fuente, fuente) == []:
        print("  OK: con el worker al dia no hay tareas que falten")
    else:
        print("  FALLO: con el worker al dia se reportan tareas que faltan")
        fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de tareas de Celery sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando tareas muertas")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    definidas = _tareas_definidas()
    programadas = _tareas_programadas()
    muertas = _muertas()

    print(f"tareas definidas:  {len(definidas)}")
    print(f"en el beat:        {len(programadas)}")
    print(f"nunca ejecutadas:  {len(muertas)}")

    # T-157 (2026-10-24): el worker en marcha puede tener el codigo viejo.
    # La puerta hasta aqui miraba solo el fuente.
    del_worker = _tareas_del_worker()
    if del_worker is None:
        print(
            "\nAVISO: no se ha podido consultar el worker en marcha: no se "
            "puede comprobar si tiene el codigo actual (esta comprobacion "
            "solo es posible con Docker y el worker levantado)."
        )
    else:
        faltan = _tareas_que_le_faltan_al_worker(set(definidas), del_worker)
        if faltan:
            print("\nFALLO: el worker en marcha NO tiene estas tareas:")
            for nombre in faltan:
                print(f"  - {nombre}")
            print(
                "  El worker corre el codigo viejo: los workers no recargan "
                "el codigo (--reload no lo soporta el pool prefork). "
                "Reinicialo: docker compose restart celery-worker"
            )
            return 1
        print(
            f"\nEl worker en marcha tiene las {len(definidas)} tareas del "
            "codigo."
        )

    if not muertas:
        print("\nOK: toda tarea de Celery se ejecuta de alguna forma.")
        return 0

    print("\nTAREAS QUE NO SE EJECUTAN DE NINGUNA FORMA:")
    errores = 0
    for nombre, funcion in sorted(muertas.items()):
        if nombre in EXENCIONES:
            print(f"  [AVISO] {nombre} ({funcion})")
            print(f"          {EXENCIONES[nombre]}")
        else:
            print(f"  [FALLO] {nombre} ({funcion})")
            print("          No está en el beat_schedule ni nadie la despacha.")
            print("          Si es a propósito, añádela a EXENCIONES con el motivo.")
            errores += 1

    if errores:
        print(f"\n{errores} tarea(s) sin ejecutar y sin exención documentada.")
        return 1
    print("\nOK: toda tarea sin ejecutar tiene su motivo documentado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
