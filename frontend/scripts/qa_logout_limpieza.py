"""QA: al cerrar sesion, el toast se ve, la navegacion es del router y
el store de UI se limpia.

POR QUE ESTA QA (T-174, 2026-10-24)
-----------------------------------
El logout hacia tres cosas mal:

1. ``location.assign('/login')`` **recargaba la pagina**: el toast de
   «Sesion cerrada» se lo comia la recarga (no llegaba a verse) y la
   ruta iba escrita a mano (con un ``base`` distinto de '/', '/login'
   no es la ruta de la app);
2. el store de UI (``stores/ui.ts``) no se limpia: con la navegacion
   por router el store **sobrevive** al logout, asi que el sidebar
   movil abierto y los toasts de la sesion anterior se los encuentra
   el usuario siguiente en la misma pestaña;
3. por lo mismo, el toast no se veia: su contenedor vivia en el
   layout, que se desmonta al ir al login.

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo):
tras cerrar sesion, la pagina estaba en /login y no habia **ningun**
toast (0 elementos con el texto «Sesion cerrada»).

Esta QA lo comprueba con un navegador de verdad (movil, 414 px):

1. el toast «Sesion cerrada» tiene que verse en el login;
2. la pagina NO tiene que recargarse (se pone una marca en ``window``
   antes de cerrar sesion: si se recarga, la marca desaparece) ⇒ se
   usa el router, no una ruta absoluta;
3. el store de UI tiene que estar limpio: tras volver a iniciar
   sesion, el sidebar movil tiene que estar CERRADO (no puede quedar
   abierto de la sesion anterior).

OJO: el rate-limit del login es de 10 intentos por IP cada 5 min (50
en desarrollo) y esta QA hace 2 inicios de sesion.

Uso:
    python frontend/scripts/qa_logout_limpieza.py
    python frontend/scripts/qa_logout_limpieza.py --base http://127.0.0.1:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
import sys

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost' (ver AGENTS.md).
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
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


def _login(pagina, email: str, password: str, base: str, recargar: bool) -> tuple[bool, str]:
    """Inicia sesion.

    ``recargar`` decide si se navega con ``goto`` (recarga la pagina) o
    se rellena el formulario que YA esta en pantalla (navegacion del
    router, sin recargar). La comprobacion 3 (el store de UI limpio)
    necesita lo segundo: con una recarga, el store se crea de cero y
    la comprobacion pasaria en vacio.
    """
    try:
        if recargar:
            pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", email)
        pagina.fill("input[type=password]", password)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _sidebar_abierto(pagina) -> bool | None:
    """True si el sidebar movil esta abierto, False si esta cerrado."""
    clases = pagina.evaluate(
        """() => {
          const aside = document.querySelector('aside')
          return aside ? aside.className : null
        }"""
    )
    if clases is None:
        return None
    tokens = clases.split()
    if "translate-x-0" in tokens:
        return True
    if "-translate-x-full" in tokens:
        return False
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar el cierre de sesion "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    email, password = CUENTA
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # Movil: el sidebar se puede abrir (y es lo que queda sucio si
        # el store no se limpia).
        contexto = navegador.new_context(viewport={"width": 414, "height": 820})
        pagina = contexto.new_page()
        try:
            ok, motivo = _login(pagina, email, password, base, recargar=True)
            if not ok:
                print(f"FALLO: no se pudo iniciar sesion: {motivo}")
                return 1

            # Sidebar movil abierto: es el estado de UI que se queda
            # sucio si el store no se limpia al cerrar sesion.
            pagina.get_by_role("button", name="Abrir menú").click()
            pagina.wait_for_timeout(500)
            if _sidebar_abierto(pagina) is not True:
                print("FALLO: no se pudo abrir el sidebar movil (la QA no vale)")
                return 1

            pagina.locator('[aria-haspopup="menu"]').first.click()
            pagina.wait_for_timeout(300)

            # Marca en la pagina: si el logout recarga, desaparece.
            pagina.evaluate("() => { window.__qa_t174 = 'vivo' }")

            pagina.get_by_role("menuitem", name="Cerrar sesión").click()
            try:
                pagina.wait_for_url(lambda u: "/login" in u, timeout=15000)
            except Exception:
                print(
                    "FALLO: el cierre de sesion no llevo al login "
                    f"(la URL se quedo en {pagina.url})"
                )
                return 1
            pagina.wait_for_timeout(700)

            # 1. El toast tiene que verse.
            if pagina.get_by_text("Sesión cerrada").count() == 0:
                print(
                    "FALLO: el toast de 'Sesion cerrada' no se ve: la recarga "
                    "de la pagina (location.assign) se lo come"
                )
                return 1
            print("OK: el toast de 'Sesion cerrada' se ve en el login")

            # 2. La pagina NO tiene que haberse recargado.
            marca = pagina.evaluate("() => window.__qa_t174 || null")
            if marca != "vivo":
                print(
                    "FALLO: la pagina se recargo al cerrar sesion (la marca "
                    "window.__qa_t174 desaparecio): se sigue usando una ruta "
                    "absoluta (location.assign) en vez del router"
                )
                return 1
            print("OK: el cierre de sesion navega con el router (sin recargar)")

            # 3. El store de UI tiene que estar limpio: se vuelve a
            #    iniciar sesion SIN recargar (si se recargase, el store
            #    se crearia de cero y la comprobacion no valdria).
            ok, motivo = _login(pagina, email, password, base, recargar=False)
            if not ok:
                print(f"FALLO: no se pudo volver a iniciar sesion: {motivo}")
                return 1
            pagina.wait_for_timeout(1000)
            abierto = _sidebar_abierto(pagina)
            if abierto is None:
                print("FALLO: no se encontro el sidebar (la QA no vale)")
                return 1
            if abierto:
                print(
                    "FALLO: el store de UI no se limpio al cerrar sesion: el "
                    "sidebar movil sigue abierto en la sesion siguiente"
                )
                return 1
            print("OK: el store de UI se limpio (el sidebar no queda abierto)")
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            contexto.close()
            navegador.close()

    print("OK: el cierre de sesion se ve, no recarga y limpia el store de UI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
