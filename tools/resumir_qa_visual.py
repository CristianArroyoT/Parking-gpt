"""Resume el informe de la QA visual: pantallas OK, avisos y errores de
consola.

Uso: python tools/resumir_qa_visual.py D:\\tmp\\qa-solidapp-p2\\informe.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    ruta = Path(sys.argv[1])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    filas = datos if isinstance(datos, list) else datos.get("pantallas", [])
    ok = 0
    con_avisos = 0
    errores_consola = 0
    for fila in filas:
        etiqueta = fila.get("etiqueta", "?")
        vacia = fila.get("vacia", False)
        consola = fila.get("consola", []) or []
        red = fila.get("red", []) or []
        errores = [c for c in consola if c.startswith("error")]
        if not vacia and not red:
            ok += 1
        else:
            con_avisos += 1
        errores_consola += len(errores)
        if vacia or red or errores:
            print(f"[AVISO] {etiqueta}")
            if vacia:
                print("        pantalla vacia")
            for c in errores:
                print(f"        consola: {c[:140]}")
            for r in red:
                print(f"        red: {r[:140]}")
    total = len(filas)
    print(f"pantallas: {total} | sin incidencias: {ok} | con avisos: {con_avisos}")
    print(f"errores de consola: {errores_consola}")
    if errores_consola:
        print("\nHAY ERRORES DE CONSOLA: revisa el detalle de arriba")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
