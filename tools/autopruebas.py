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

Los códigos de salida de cada autoprueba tienen un significado:

* ``0`` — pasa.
* ``1`` — falla: la puerta ya no detecta.
* ``3`` — **no se ha podido comprobar** (falta un navegador, por
  ejemplo). No es un verde: la meta-puerta lo cuenta aparte y lo dice.
  Con ``--estricto`` (lo que usa el CI) es un fallo.

Uso:
    python tools/autopruebas.py
    python tools/autopruebas.py --estricto
"""
from __future__ import annotations

import argparse
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
        "La puerta del contrato del refresco sigue viendo",
        [sys.executable, "tools/verificar_contrato_refresh.py", "--autoprueba"],
    ),
    (
        "El extractor de la API sigue sacando todos los roles",
        [sys.executable, "tools/extraer_api.py", "--autoprueba"],
    ),
    (
        "La puerta de aislamiento por sucursal sigue viendo los tres patrones",
        [sys.executable, "tools/verificar_aislamiento_sucursal.py", "--autoprueba"],
    ),
    (
        "La puerta de la cache del service worker sigue viendo",
        [sys.executable, "tools/verificar_cache_service_worker.py", "--autoprueba"],
    ),
    (
        "La puerta del backup con adjuntos sigue viendo",
        [sys.executable, "tools/verificar_backup_adjuntos.py", "--autoprueba"],
    ),
    (
        "La puerta de la sesion caducada sigue viendo",
        [sys.executable, "tools/verificar_sesion_caducada.py", "--autoprueba"],
    ),
    (
        "La puerta del volumen de adjuntos sigue viendo",
        [sys.executable, "tools/verificar_volumen_adjuntos.py", "--autoprueba"],
    ),
    (
        "Las pruebas inversas siguen detectando su defecto",
        [sys.executable, "tools/verificar_pruebas_inversas.py", "--autoprueba"],
    ),
    (
        "La clasificacion del CI remoto sigue distinguiendo",
        [sys.executable, "tools/estado_ci.py", "--autoprueba"],
    ),
    (
        "La puerta de cuentas demo sigue viendo",
        [sys.executable, "tools/verificar_cuentas_demo.py", "--autoprueba"],
    ),
    (
        "La puerta de cobertura de pantallas sigue viendo",
        [sys.executable, "tools/verificar_cobertura_frontend.py", "--autoprueba"],
    ),
    (
        "La puerta de enums del backend sigue viendo",
        [sys.executable, "tools/verificar_enums_frontend.py", "--autoprueba"],
    ),
    (
        "La puerta de tareas de Celery sigue viendo",
        [sys.executable, "tools/verificar_tareas_celery.py", "--autoprueba"],
    ),
    (
        "La puerta de ajustes muertos sigue viendo",
        [sys.executable, "tools/verificar_ajustes_muertos.py", "--autoprueba"],
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
        "La puerta del servidor de produccion sigue viendo",
        [sys.executable, "frontend/scripts/verificar_servidor_produccion.py", "--autoprueba"],
    ),
    (
        "La puerta del limite de cuerpo de nginx sigue viendo",
        [sys.executable, "tools/verificar_nginx_body_size.py", "--autoprueba"],
    ),
    (
        "La puerta de la IP real del visitante sigue viendo",
        [sys.executable, "tools/verificar_ip_real_nginx.py", "--autoprueba"],
    ),
    (
        "La puerta del contexto de build sigue viendo",
        [sys.executable, "tools/verificar_contexto_build.py", "--autoprueba"],
    ),
    (
        "La puerta del rate-limit unico sigue viendo",
        [sys.executable, "tools/verificar_rate_limit_unico.py", "--autoprueba"],
    ),
    (
        "La puerta del lockfile sigue viendo",
        [sys.executable, "tools/verificar_lockfile.py", "--autoprueba"],
    ),
    (
        "La puerta del compose de produccion sigue viendo",
        [sys.executable, "tools/verificar_compose_produccion.py", "--autoprueba"],
    ),
    (
        "La puerta del README de despliegue sigue viendo",
        [sys.executable, "tools/verificar_readme_despliegue.py", "--autoprueba"],
    ),
    (
        "La puerta de dependencias vulnerables sigue viendo",
        [sys.executable, "tools/verificar_dependencias.py", "--autoprueba"],
    ),
    (
        "La puerta del repo detecta los fallos",
        [sys.executable, "tools/verificar_repo.py", "--autoprueba"],
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--estricto", action="store_true",
        help=(
            "Falla tambien si alguna autoprueba NO se ha podido comprobar "
            "(por ejemplo, por falta de un navegador). El CI lo usa: ahi "
            "todas tienen que comprobarse."
        ),
    )
    args = ap.parse_args()

    print("AUTOPRUEBAS DE LAS PUERTAS", flush=True)
    print("=" * 74, flush=True)
    fallos = 0
    no_verificadas: list[str] = []
    for nombre, comando in AUTOPRUEBAS:
        print(f"\n--- {nombre}", flush=True)
        resultado = subprocess.run(
            comando, cwd=str(RAIZ), check=False, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        if resultado.returncode == 3:
            # No se ha podido comprobar: NO es un verde. Se cuenta aparte
            # para que no se confunda con "pasa".
            no_verificadas.append(nombre)
            print(f"  NO VERIFICADA: {nombre}", flush=True)
            # OJO: este subprocess NO captura la salida (el hijo escribe
            # directamente en la consola), asi que ``stdout`` es None.
            for linea in (resultado.stdout or "").splitlines():
                print(f"    {linea}", flush=True)
        elif resultado.returncode != 0:
            fallos += 1
            print(f"  FALLO: {nombre} (codigo {resultado.returncode})", flush=True)
    print("\n" + "=" * 74, flush=True)
    if fallos:
        print(
            f"{fallos} autoprueba(s) en FALLO: alguna puerta ya no detecta lo que dice.",
            flush=True,
        )
        return 1
    if no_verificadas:
        print(
            f"{len(AUTOPRUEBAS) - len(no_verificadas)} autopruebas pasan y "
            f"{len(no_verificadas)} NO se han podido comprobar:",
            flush=True,
        )
        for nombre in no_verificadas:
            print(f"  - {nombre}", flush=True)
        if args.estricto:
            print("\nEn modo --estricto eso es un FALLO.", flush=True)
            return 1
        print("\nSin --estricto no es un fallo, pero no lo tomes por un verde.", flush=True)
        return 0
    print(
        f"Las {len(AUTOPRUEBAS)} autopruebas pasan: las puertas siguen detectando.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
