"""Busca asimetrias de validacion entre los esquemas Create y Update.

Si un campo se valida al crear (min_length, max_length...) pero no al
editar, la API acepta un valor invalido por el PATCH que el POST
rechaza. Es el agujero que se encontro con ``CameraUpdate.rtsp_url``
(2026-10-21).

Uso: python tools/revisar_esquemas.py
"""
from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESQUEMAS = RAIZ / "backend" / "app" / "schemas"


def _campos(clase: ast.ClassDef) -> dict[str, str]:
    """Campo → texto de la anotación (incluye el Field(...))."""
    campos: dict[str, str] = {}
    for nodo in clase.body:
        if not isinstance(nodo, ast.AnnAssign):
            continue
        if not isinstance(nodo.target, ast.Name):
            continue
        valor = ""
        if nodo.value is not None:
            valor = ast.unparse(nodo.value)
        campos[nodo.target.id] = valor
    return campos


def _campos_con_herencia(
    clase: ast.ClassDef, clases: dict[str, ast.ClassDef], vistos: set[str] | None = None
) -> dict[str, str]:
    """Los campos de la clase **y de sus bases** definidas en el módulo.

    OJO: sin esto, el detector era ciego a los esquemas que heredan sus
    campos de una clase base (``ParkingCreate(ParkingBase)``,
    ``UserCreate(UserBase)``): sus campos no están en el cuerpo de la
    clase, así que no se comparaban nunca.
    """
    if vistos is None:
        vistos = set()
    if clase.name in vistos:
        return {}
    vistos.add(clase.name)
    campos: dict[str, str] = {}
    for base in clase.bases:
        if isinstance(base, ast.Name) and base.id in clases:
            campos.update(_campos_con_herencia(clases[base.id], clases, vistos))
    campos.update(_campos(clase))
    return campos


def _asimetrias(arbol: ast.Module, nombre_fichero: str) -> list[str]:
    """Las asimetrías de validación entre Create y Update de un fichero.

    Extraído como función aparte para poder **probarlo** (ver
    ``--autoprueba``): la lógica es la que encontró el hueco del
    ``CameraUpdate.rtsp_url``, así que tiene que seguir encontrándolo.
    """
    hallazgos: list[str] = []
    clases = {
        nodo.name: nodo for nodo in arbol.body if isinstance(nodo, ast.ClassDef)
    }
    for nombre, nodo in clases.items():
        if not nombre.endswith("Create"):
            continue
        # OJO: "Create" tiene SEIS letras. Con ``[:-5]`` la pareja salía
        # "CameraCUpdate" y no se encontraba nunca: el detector no
        # comparaba nada y su "OK" era vacío.
        pareja = nombre[: -len("Create")] + "Update"
        if pareja not in clases:
            continue
        campos_create = _campos_con_herencia(nodo, clases)
        campos_update = _campos_con_herencia(clases[pareja], clases)
        for campo, texto in campos_create.items():
            if campo not in campos_update:
                continue
            if "Field" not in texto:
                continue
            if "Field" in campos_update[campo]:
                continue
            # El update no valida lo que el create sí valida.
            hallazgos.append(
                f"{nombre_fichero}: '{campo}' se valida en {nombre} "
                f"({texto}) pero NO en {pareja}"
            )
    return hallazgos


def _autoprueba() -> int:
    """Comprueba que el detector SIGUE encontrando las asimetrías.

    Una puerta que no se puede ver fallar no es una puerta: este
    detector es el que encontró el hueco del ``CameraUpdate.rtsp_url``
    (el PATCH aceptaba una URL vacía que el POST rechazaba), así que
    tiene que seguir encontrándolo.
    """
    asimetrico = ast.parse(
        "class WidgetCreate(BaseModel):\n"
        "    nombre: str = Field(min_length=3)\n"
        "\n"
        "class WidgetUpdate(BaseModel):\n"
        "    nombre: str\n"
    )
    simetrico = ast.parse(
        "class WidgetCreate(BaseModel):\n"
        "    nombre: str = Field(min_length=3)\n"
        "\n"
        "class WidgetUpdate(BaseModel):\n"
        "    nombre: str = Field(min_length=3)\n"
    )

    fallos = 0
    hallazgos = _asimetrias(asimetrico, "prueba.py")
    if not hallazgos:
        fallos += 1
        print("  FALLO: una asimetria de validacion NO se ha detectado")
    else:
        print(f"  OK: una asimetria se detecta -> {hallazgos[0][:70]}")

    hallazgos = _asimetrias(simetrico, "prueba.py")
    if hallazgos:
        fallos += 1
        print(f"  FALLO: una simetria se ha marcado como asimetria: {hallazgos[0]}")
    else:
        print("  OK: una pareja simetrica no se marca")

    # Y los esquemas de verdad tienen que estar limpios.
    reales: list[str] = []
    for fichero in sorted(ESQUEMAS.glob("*.py")):
        reales.extend(
            _asimetrias(ast.parse(fichero.read_text(encoding="utf-8")), fichero.name)
        )
    if reales:
        fallos += 1
        print(f"  FALLO: los esquemas reales tienen {len(reales)} asimetria(s)")
        for h in reales[:5]:
            print(f"        {h}")
    else:
        print("  OK: los esquemas reales no tienen asimetrias")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el detector de asimetrias sigue viendo.")
    return 0


def main() -> int:
    import sys

    if "--autoprueba" in sys.argv:
        return _autoprueba()

    hallazgos: list[str] = []
    for fichero in sorted(ESQUEMAS.glob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        hallazgos.extend(_asimetrias(arbol, fichero.name))
    for h in hallazgos:
        print(h)
    if hallazgos:
        print(f"\n{len(hallazgos)} asimetria(s) de validacion entre Create y Update.")
        return 1
    print("OK: los campos validados en el alta se validan igual en la edicion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
