"""QA del T-165 (2026-10-24): el destino del login se valida.

QUE COMPRUEBA
-------------
El ``redirect`` de la query del login se pasa a ``router.push()``. El
valor lo pone quien construya el enlace, asi que tiene que **validarse**:

- ``?redirect=//ejemplo.com`` (protocolo-relativo) y
  ``?redirect=https://ejemplo.com`` (URL absoluta) dejaban al usuario en
  una ruta **que no existe** (medido: ``http://127.0.0.1:5173//ejemplo.com``);
  OJO: **no** es una redireccion abierta (vue-router 4 los trata como rutas
  del propio host), pero el destino tiene que ser una ruta interna de
  verdad.
- ``?redirect=/a&redirect=/b`` llega como **array**: el cast ``as string``
  no lo convertia, el ``push`` fallaba y su rechazo se quedaba **sin
  gestionar** (el login habia funcionado, pero el usuario se quedaba en
  el formulario de login, con la sesion iniciada y sin ver el mensaje de
  bienvenida; el siguiente intento chocaba con el rate-limit).

DESPUES DEL LOGIN, la URL debe ser una ruta interna de la aplicacion, no
debe contener el valor malicioso, y el usuario **no** debe quedarse en el
formulario de login.

OJO (rate-limit): ``POST /auth/login`` admite 10 intentos por IP cada 5
minutos (y cuenta tambien los exitosos), asi que esta QA hace **solo dos
logins** y va en un contexto nuevo por caso (asi no hereda la sesion de
otro caso).
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
CUENTA = ("gestor.madrid@solidapp.es", "gestor1234")

#: (query del redirect, texto que no puede aparecer en la URL final)
CASOS = (
    ("//example.com", "example.com"),
    ("/mapa&redirect=/otro", ",otro"),
)


def main() -> int:
    fallos = 0
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for redirect, prohibido in CASOS:
            # Contexto nuevo: sessionStorage separado (si no, el login del
            # caso anterior deja tokens y este entra ya autenticado).
            contexto = navegador.new_context()
            pagina = contexto.new_page()
            pagina.goto(
                f"{BASE}/login?redirect={redirect}", wait_until="domcontentloaded"
            )
            pagina.fill("input[type=email]", CUENTA[0])
            pagina.fill("input[type=password]", CUENTA[1])
            pagina.click("button[type=submit]")
            pagina.wait_for_timeout(3500)
            final = pagina.url
            print(f"  redirect={redirect!r} -> {final}")

            if not final.startswith(BASE + "/"):
                print("    *** FALLO: ha salido de la aplicacion")
                fallos += 1
            elif prohibido in final:
                print(f"    *** FALLO: la URL contiene el valor malicioso ({prohibido!r})")
                fallos += 1
            elif "/login" in final:
                print("    *** FALLO: se ha quedado en el formulario de login")
                fallos += 1
            contexto.close()
        navegador.close()

    if fallos:
        print(f"\n{fallos} caso(s) mal: el destino del login no se valida (T-165)")
        return 1
    print("\nOK: el destino del login se valida (T-165)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
