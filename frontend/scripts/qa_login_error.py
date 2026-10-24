"""QA: un login cuyo perfil no se puede cargar falla CON MENSAJE y no deja tokens.

POR QUÉ ESTA QA (T-139, 2026-10-24)
--------------------------------------
``fetchMe()`` se tragaba cualquier error: un login cuyo ``/users/me``
devolvía un 500 (un fallo del servidor, no unas credenciales malas) decia
«Bienvenido», guardaba el token, dejaba el perfil vacío y el router
echaba al usuario al formulario **sin ningún error visible**.

Esta QA lo comprueba con un navegador de verdad, interceptando
``/users/me`` para que devuelva un 500:

1. se hace login;
2. tiene que aparecer un mensaje de error;
3. y **no** puede quedar ningún token en ``sessionStorage``.

Uso:
    python frontend/scripts/qa_login_error.py
    python frontend/scripts/qa_login_error.py --base http://localhost:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
import sys

BASE_POR_DEFECTO = "http://localhost:5173"
SIN_NAVEGADOR = 3
CUENTA = ("gestor.madrid@solidapp.es", "gestor1234")

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
            "SIN NAVEGADOR: no se puede comprobar el login con error "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    email, password = CUENTA
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        try:
            # El perfil no se puede cargar (un 500 del servidor).
            pagina.route(
                "**/api/v1/users/me",
                lambda ruta: ruta.fulfill(
                    status=500,
                    content_type="application/json",
                    body='{"detail":"fallo de prueba"}',
                ),
            )
            pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
            pagina.fill("input[type=email]", email)
            pagina.fill("input[type=password]", password)
            pagina.click("button[type=submit]")

            # El login tiene que fallar CON un mensaje.
            try:
                pagina.wait_for_selector("p.text-rose-600", timeout=15000)
                mensaje = pagina.inner_text("p.text-rose-600")
            except Exception:
                print(
                    "FALLO: el login fallo sin mostrar ningun error "
                    f"(la pagina dice: {pagina.inner_text('body')[:160]!r})"
                )
                return 1

            tokens = pagina.evaluate(
                """() => ({
                  access: sessionStorage.getItem('solidapp.access'),
                  refresh: sessionStorage.getItem('solidapp.refresh'),
                  email: sessionStorage.getItem('solidapp.email'),
                })"""
            )
            if tokens.get("access") or tokens.get("refresh"):
                print("FALLO: el login fallo pero dejo los tokens guardados")
                return 1

            print(f"OK: el login fallo con mensaje ({mensaje.strip()[:70]!r}) y sin tokens")
            return 0
        finally:
            navegador.close()


if __name__ == "__main__":
    sys.exit(main())
