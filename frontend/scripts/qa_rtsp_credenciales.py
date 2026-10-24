"""QA: la URL RTSP (que puede llevar credenciales) no se pinta en el DOM.

POR QUÉ ESTA QA (T-173, 2026-10-24)
-----------------------------------
La tabla de cams (``views/gestor/CamerasView.vue``) pintaba la URL
RTSP tal cual. Esa URL puede llevar usuario y CONTRASENA
(``rtsp://usuario:clave@host:puerto/stream``), y el backend la devuelve
entera: la contrasena se quedaba en el DOM, donde la lee cualquiera que
abra las herramientas de desarrollo o el «ver codigo fuente» del
navegador.

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo):
con una camara de prueba cuya URL era
``rtsp://usuarioQA:claveSecretaT173@cam.example.invalid:554/stream1``,
la pagina contenia la contrasena y la URL entera.

Esta QA lo comprueba con un navegador de verdad:

1. se intercepta el listado de cams con una URL que lleva credenciales;
2. la pagina NO puede contener la contrasena (ni en el texto, ni en un
   atributo: se mira el HTML entero);
3. y la fila tiene que verse (no vale con que no se pinte nada): la
   URL se muestra ENMASCARADA.

Uso:
    python frontend/scripts/qa_rtsp_credenciales.py
    python frontend/scripts/qa_rtsp_credenciales.py --base http://127.0.0.1:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
import json
import sys

# La consola de Windows es cp1252: si el texto trae un caracter que no
# cabe, se sustituye en vez de reventar la QA al final.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost' (ver AGENTS.md).
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
SIN_NAVEGADOR = 3
CUENTA = ("gestor.madrid@solidapp.es", "gestor1234")
CONTRASENA = "claveSecretaT173"
URL_RTSP = f"rtsp://usuarioQA:{CONTRASENA}@cam.example.invalid:554/stream1"

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


def _login(pagina, email: str, password: str, base: str) -> tuple[bool, str]:
    """Inicia sesión. No lanza: un fallo debe ser un resultado, no un error."""
    try:
        pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", email)
        pagina.fill("input[type=password]", password)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar la URL RTSP "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    camara = {
        "id": 999,
        "parking_id": 1,
        "code": "CAM-QA-T173",
        "name": "Camara de prueba T173",
        "rtsp_url": URL_RTSP,
        "lane_hint": "entry",
        "fps": 10,
        "is_active": True,
        "kind": "gate",
    }

    email, password = CUENTA
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        try:
            ok, motivo = _login(pagina, email, password, base)
            if not ok:
                print(f"FALLO: no se pudo iniciar sesion: {motivo}")
                return 1

            # El listado de cams se intercepta con una URL que lleva
            # credenciales: es lo que devuelve el backend.
            pagina.route(
                "**/api/v1/parkings/*/cameras",
                lambda ruta: ruta.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([camara]),
                ),
            )
            pagina.goto(f"{base}/cameras", wait_until="domcontentloaded", timeout=30000)
            try:
                pagina.get_by_text("CAM-QA-T173").first.wait_for(timeout=15000)
            except Exception:
                print(
                    "FALLO: la camara de prueba no se pinto (la pagina dice: "
                    f"{pagina.inner_text('body')[:160]!r})"
                )
                return 1

            # 1. La contrasena no puede estar en el DOM (ni en un texto,
            #    ni en un atributo): se mira el HTML entero.
            html = pagina.content()
            if CONTRASENA in html:
                indice = html.find(CONTRASENA)
                print(
                    "FALLO: la contrasena de la URL RTSP esta en el DOM: "
                    f"...{html[max(0, indice - 60):indice + 40]!r}..."
                )
                return 1
            print("OK: la contrasena de la URL RTSP no esta en el DOM")

            # 2. La fila tiene que verse: la URL se muestra enmascarada.
            celda = pagina.evaluate(
                """() => {
                  const tds = Array.from(document.querySelectorAll('td'))
                  const td = tds.find((t) => (t.textContent || '').includes('rtsp://'))
                  return td ? (td.textContent || '').trim() : null
                }"""
            )
            if celda is None:
                print(
                    "FALLO: no se encontro la celda con la URL RTSP "
                    "(la fila no se pinto?)"
                )
                return 1
            if "cam.example.invalid" not in celda:
                print(
                    "FALLO: la URL RTSP no se muestra (celda vacia o sin host): "
                    f"{celda!r}"
                )
                return 1
            if "••••" not in celda:
                print(
                    "FALLO: la URL RTSP se muestra sin enmascarar: "
                    f"la celda dice {celda!r}"
                )
                return 1
            print(f"OK: la URL RTSP se muestra enmascarada ({celda})")
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            contexto.close()
            navegador.close()

    print("OK: la URL RTSP no deja la contrasena en el DOM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
