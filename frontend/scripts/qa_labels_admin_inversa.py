"""Prueba inversa del T-171 y del T-182: sin ``for``/``id``, los campos de
los formularios se anuncian SIN NOMBRE.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).

Se deshace el arreglo en un formulario cada vez (sucursales, tarifas,
cams, alta manual, vehiculos del cliente, modal de incidentes y el
``<select>`` de sucursal de la pantalla «En vivo») y se exige que la QA
falle por el motivo correcto en cada caso.

OJO (T-182): la QA vigila ahora las cuatro vistas que faltaban (cliente,
calibracion, operador), asi que la inversa tiene que comprobarlas tambien:
si la QA se queda en las de administracion, es una puerta ciega para las
otras.

Al final se vuelve a dejar el fichero como estaba y se corre la QA otra
vez: el verde tiene que volver (si no, el defecto se ha dejado puesto).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(r"D:\Parking")
SRC = RAIZ / "frontend" / "src"
COPIA = Path(r"D:\tmp\_copias_t171")
COPIA.mkdir(parents=True, exist_ok=True)

# (fichero, id del par etiqueta/campo, vista que tiene que señalar el fallo,
#  modo de la mutación)
#
# "par":  se quita el ``for="X"`` y el ``id="X"`` de la etiqueta y el campo.
# "aria": el control NO tiene etiqueta (es un ``<select>`` compacto): lo que
#         da el nombre es el ``aria-label``, y lo que se quita es eso.
MUTACIONES: list[tuple[str, str, str, str]] = [
    ("views/admin/ParkingsView.vue", "parking-codigo", "/admin/parkings", "par"),
    ("views/admin/TariffsView.vue", "tarifa-nombre", "/admin/tariffs", "par"),
    ("views/gestor/CamerasView.vue", "camara-rtsp", "/cameras", "par"),
    # T-182: las cuatro vistas nuevas.
    ("views/operador/ManualEntryView.vue", "alta-sucursal", "/operador/alta-manual", "par"),
    ("views/cliente/VehiclesView.vue", "veh-edicion-marca", "/mis-vehiculos", "par"),
    (
        "views/operador/IncidentModal.vue",
        "inc-plaza",
        "/vivo (modal de incidentes: averiada)",
        "par",
    ),
    # T-188 (2026-10-25): el ``<select>`` de sucursal de la pantalla «En vivo»
    # (1 control medido). Su nombre va en ``aria-label``, no en un par
    # for/id, asi que la mutacion quita el ``aria-label``.
    (
        "views/operador/LiveView.vue",
        'aria-label="Sucursal"',
        "/vivo (la página)",
        "aria",
    ),
]


def _calentar_frontend() -> None:
    """Fuerza a Vite a terminar la reoptimización de dependencias.

    Al arrancar, Vite reoptimiza las dependencias (escribe en
    node_modules/.vite) y el dev-server se reinicia otra vez: si la QA pide
    la página justo en ese momento, mide un bundle a medias o se queda
    esperando el <h1> hasta agotar el tiempo. Abriendo la pantalla de
    login en un navegador de verdad, ese trabajo se adelanta (medido: con
    la máquina saturada, sin calentar, la QA falló por un tiempo de espera
    agotado en una escena que no tenía nada que ver).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        time.sleep(20)
        return
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page()
            pagina.goto(
                "http://127.0.0.1:5173/login",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            pagina.wait_for_selector("input[type=email]", timeout=90000)
            navegador.close()
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: no se pudo calentar el frontend: {type(exc).__name__}: {exc}")


def reiniciar_frontend() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "frontend"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    fin = time.time() + 180
    while time.time() < fin:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5173/login", timeout=5) as r:
                if r.status == 200:
                    _calentar_frontend()
                    time.sleep(5)
                    return
        except Exception:
            time.sleep(3)
    print("AVISO: el frontend no respondio tras el reinicio.")


def correr_qa() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "frontend/scripts/qa_labels_admin.py"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fallos_de(salida: str) -> list[str]:
    return [linea for linea in salida.splitlines() if linea.startswith("FALLO")]


def main() -> int:
    fallo: str | None = None
    for relativo, id_campo, vista, modo in MUTACIONES:
        ruta = SRC / relativo
        original = ruta.read_text(encoding="utf-8")
        copia = COPIA / ruta.name
        shutil.copy2(ruta, copia)
        try:
            descripcion: str
            if modo == "aria":
                # El control no tiene etiqueta: su nombre va en el
                # ``aria-label``, y lo que se quita es eso.
                trozo = f" {id_campo}"
                if original.count(trozo) != 1:
                    fallo = (
                        f"ERROR: en {relativo} el {id_campo!r} aparece "
                        f"{original.count(trozo)} veces (se esperaba 1)."
                    )
                    print(fallo)
                    break
                texto = original.replace(trozo, "")
                descripcion = f"quitado el {id_campo}"
            else:
                con_for = f' for="{id_campo}"'
                con_id = f' id="{id_campo}"'
                if original.count(con_for) != 1 or original.count(con_id) != 1:
                    fallo = (
                        f"ERROR: en {relativo} el par {id_campo!r} aparece "
                        f"{original.count(con_for)} veces como for= y "
                        f"{original.count(con_id)} como id=."
                    )
                    print(fallo)
                    break
                texto = original.replace(con_for, "").replace(con_id, "")
                descripcion = f"quitado el for/id de {id_campo!r}"
            ruta.write_text(texto, encoding="utf-8", newline="")
            print(f"  {relativo}: {descripcion}")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            codigo, salida = correr_qa()
            print("\nSalida de la QA con el defecto (lineas de FALLO):")
            for linea in _fallos_de(salida):
                print("   ", linea)
            print(f"\ncodigo de salida: {codigo}")
            if codigo == 0:
                fallo = "*** FALLO: la QA pasa sin el arreglo: no demuestra nada."
                print(fallo)
                break
            if "SIN NOMBRE" not in salida:
                fallo = "*** AVISO: fallo por otro motivo: la prueba no vale."
                print(fallo)
                break
            # La QA tiene que senalar ESTA vista, no otra: si no, la puerta
            # podria estar fallando por el motivo equivocado.
            if f"FALLO ({vista})" not in salida:
                fallo = (
                    f"*** AVISO: la QA fallo por otra vista (se esperaba "
                    f"{vista!r}): la prueba no vale."
                )
                print(fallo)
                break
            print(f"OK: sin el arreglo, la QA falla por el motivo correcto ({vista}).")
        finally:
            shutil.copy2(copia, ruta)
            print(f"restaurado: frontend/src/{relativo}")

    # El frontend tiene que volver a servir el codigo restaurado, **tambien
    # si algo ha fallado**: si no, la app se queda sirviendo el defecto
    # puesto (el fallo mas caro de todos).
    print("\n  reiniciando el frontend (codigo restaurado)...")
    reiniciar_frontend()
    if fallo:
        return 1

    # El arbol tiene que volver a estar bien: se corre la QA otra vez (una
    # puerta que se queda en rojo no vale).
    codigo, salida = correr_qa()
    if codigo != 0:
        print("*** FALLO: con los ficheros restaurados la QA sigue en rojo:")
        for linea in _fallos_de(salida):
            print("   ", linea)
        return 1
    print("OK: con los ficheros restaurados, la QA vuelve a dar verde.")
    print(
        f"\nOK: la QA detecta el defecto en los {len(MUTACIONES)} formularios"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
