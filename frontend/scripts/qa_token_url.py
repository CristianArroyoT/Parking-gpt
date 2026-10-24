"""QA: el token de recuperación de contraseña no se queda en la URL.

POR QUÉ ESTA QA (T-172, 2026-10-24)
----------------------------------
El enlace de recuperación llega por correo con el token en la query
(``/recuperar-contrasena?token=...``). Al cambiar la contraseña, el
token **se quedaba en la barra de direcciones**: ahí queda en el
historial del navegador, en el referrer de la siguiente página y en
cualquier «copiar enlace» que haga el usuario.

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo):
tras cambiar la contraseña, ``window.location.search`` seguía siendo
``?token=TOKEN_DE_PRUEBA_T172``.

Esta QA lo comprueba con un navegador de verdad:

1. se abre el enlace con un token;
2. se cambia la contraseña (el POST se intercepta: el token es de un
   solo uso y no se quiere gastar uno de verdad);
3. la pantalla de «Contraseña actualizada» tiene que aparecer (el
   arreglo no puede romper el flujo);
4. la URL tiene que quedar **sin token**.

Uso:
    python frontend/scripts/qa_token_url.py
    python frontend/scripts/qa_token_url.py --base http://127.0.0.1:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
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
TOKEN = "TOKEN_DE_PRUEBA_T172"

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar la limpieza de la URL "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        try:
            # El POST se intercepta: el token es de un solo uso y no
            # hace falta gastarlo de verdad para medir esto.
            pagina.route(
                "**/api/v1/auth/reset-password",
                lambda ruta: ruta.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"detail":"Contrasena actualizada"}',
                ),
            )
            pagina.goto(
                f"{base}/recuperar-contrasena?token={TOKEN}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            pagina.fill("#new-password", "NuevaClaveQA123")
            pagina.fill("#confirm-password", "NuevaClaveQA123")
            pagina.click("button[type=submit]")

            # El flujo tiene que seguir funcionando: la pantalla de
            # «Contraseña actualizada» (no vale con borrar la URL).
            try:
                pagina.get_by_text("Contraseña actualizada").first.wait_for(timeout=15000)
            except Exception:
                print(
                    "FALLO: el cambio de contrasena no llego a 'Contraseña "
                    "actualizada' (la pagina dice: "
                    f"{pagina.inner_text('body')[:160]!r})"
                )
                return 1

            pagina.wait_for_timeout(800)
            url = pagina.url
            busqueda = pagina.evaluate("() => window.location.search")
            if "token" in busqueda.lower() or TOKEN in url:
                print(
                    "FALLO: el token de recuperacion se queda en la URL: "
                    f"la barra de direcciones dice {url!r}"
                )
                return 1
            print(f"OK: el token ya no esta en la URL ({url})")
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            contexto.close()
            navegador.close()

    print("OK: el token de recuperacion se borra de la URL al cambiar la contrasena")
    return 0


if __name__ == "__main__":
    sys.exit(main())
