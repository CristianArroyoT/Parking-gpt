"""Compara dos informes de Locust: peticiones, fallos y previews omitidos
por 409 (la cámara ocupada).

Uso: python tools/comparar_informes.py informe_a.json informe_b.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def resumen(ruta: Path) -> dict:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    # Locust escribe una lista de "stats" (uno por intervalo) o un dict
    # con la misma clave, según la versión.
    if isinstance(datos, list):
        entradas: list = datos
    else:
        entradas = datos.get("stats", [])
    filas: dict[str, dict] = {}
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        nombre = entrada.get("name", "")
        if not nombre:
            continue
        acc = filas.setdefault(nombre, {"reqs": 0, "fails": 0, "total_content_length": 0})
        acc["reqs"] += entrada.get("num_requests", 0)
        acc["fails"] += entrada.get("num_failures", 0)
        acc["total_content_length"] += entrada.get("total_content_length", 0)
    return filas


def main() -> int:
    problemas = 0
    for arg in sys.argv[1:]:
        ruta = Path(arg)
        filas = resumen(ruta)
        total = sum(v["reqs"] for v in filas.values())
        fallos = sum(v["fails"] for v in filas.values())
        omitidos = filas.get("preview_mjpeg_omitido_409", {}).get("reqs", 0)
        print(f"=== {ruta.name}")
        print(f"    peticiones={total}  fallos={fallos}  previews_omitidos_409={omitidos}")
        for nombre in sorted(filas):
            v = filas[nombre]
            if v["reqs"]:
                print(
                    f"    {nombre:<40} reqs={v['reqs']:<5} fails={v['fails']:<4} "
                    f"bytes={v['total_content_length']}"
                )
        # Un informe con fallos o con previews descartados por 409 no es
        # un informe limpio: se avisa con el codigo de salida.
        if fallos or omitidos:
            problemas += 1
    if problemas:
        print(f"\n{problemas} informe(s) con fallos o con previews descartados (409)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
