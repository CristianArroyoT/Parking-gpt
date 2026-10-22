"""Las puertas, a prueba de sí mismas.

POR QUÉ (2026-10-22): en este repositorio los bugs más caros no estaban
en el código de la aplicación, sino en las **herramientas que lo
describen o lo miden**: el extractor de RBAC que decía "Público" en 9
endpoints de admin, el script de lint del frontend que nunca funcionó,
los healthcheck que no existían y el recuento de endpoints que se quedó
en 100 cuando ya eran 101.

En todos ellos faltaba lo mismo: **la puerta no tenía forma de
demostrar que detectaba lo que dice detectar**. Una puerta que no se
puede ver fallar no es una puerta.

Este script ejecuta la autoprueba de cada detector que la tenga y falla
si alguna no detecta su propia clase de defecto. Añadir una puerta
nueva es añadirla a la lista de aquí.

Uso:
    python tools/autopruebas.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: (nombre, comando de la autoprueba)
AUTOPRUEBAS: list[tuple[str, list[str]]] = [
    (
        "El inventario de la API detecta las tres caras de la deriva",
        [sys.executable, "tools/verificar_api_doc.py", "--autoprueba"],
    ),
    (
        "El escaner de texto detecta cada clase de corrupcion",
        [sys.executable, "tools/escanear_texto.py", "--autoprueba"],
    ),
    (
        "El escaner de secretos detecta los secretos y respeta las exenciones",
        [sys.executable, "tools/escanear_secretos.py", "--autoprueba"],
    ),
    (
        "La puerta de cobertura sigue distinguiendo",
        [sys.executable, "tools/cobertura_api.py", "--autoprueba"],
    ),
    (
        "El detector de asimetrias de esquemas sigue viendo",
        [sys.executable, "tools/revisar_esquemas.py", "--autoprueba"],
    ),
    (
        "El verificador de contrato frontend-backend sigue viendo",
        [sys.executable, "tools/verificar_contrato_frontend.py", "--autoprueba"],
    ),
    (
        "El extractor de la API sigue sacando todos los roles",
        [sys.executable, "tools/extraer_api.py", "--autoprueba"],
    ),
    (
        "La puerta de roles del frontend sigue viendo",
        [sys.executable, "tools/verificar_roles_frontend.py", "--autoprueba"],
    ),
    (
        "El detector de desbordes de la QA sigue viendo",
        [sys.executable, "frontend/scripts/qa_visual.py", "--autoprueba"],
    ),
    (
        "La puerta del repo detecta los fallos",
        [sys.executable, "tools/verificar_repo.py", "--autoprueba"],
    ),
]


def main() -> int:
    print("AUTOPRUEBAS DE LAS PUERTAS", flush=True)
    print("=" * 74, flush=True)
    fallos = 0
    for nombre, comando in AUTOPRUEBAS:
        print(f"\n--- {nombre}", flush=True)
        resultado = subprocess.run(
            comando, cwd=str(RAIZ), check=False, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        if resultado.returncode != 0:
            fallos += 1
            print(f"  FALLO: {nombre} (codigo {resultado.returncode})", flush=True)
    print("\n" + "=" * 74, flush=True)
    if fallos:
        print(
            f"{fallos} autoprueba(s) en FALLO: alguna puerta ya no detecta lo que dice.",
            flush=True,
        )
        return 1
    print(
        f"Las {len(AUTOPRUEBAS)} autopruebas pasan: las puertas siguen detectando.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
