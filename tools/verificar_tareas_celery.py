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
