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


def main() -> int:
    hallazgos = 0
    for fichero in sorted(ESQUEMAS.glob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        clases = {
            nodo.name: nodo for nodo in arbol.body if isinstance(nodo, ast.ClassDef)
        }
        for nombre, nodo in clases.items():
            if not nombre.endswith("Create"):
                continue
            pareja = nombre[:-5] + "Update"
            if pareja not in clases:
                continue
            campos_create = _campos(nodo)
            campos_update = _campos(clases[pareja])
            for campo, texto in campos_create.items():
                if campo not in campos_update:
                    continue
                if "Field" not in texto:
                    continue
                if "Field" in campos_update[campo]:
                    continue
                # El update no valida lo que el create sí valida.
                print(
                    f"{fichero.name}: '{campo}' se valida en {nombre} "
                    f"({texto}) pero NO en {pareja}"
                )
                hallazgos += 1
    if hallazgos:
        print(f"\n{hallazgos} asimetria(s) de validacion entre Create y Update.")
        return 1
    print("OK: los campos validados en el alta se validan igual en la edicion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
