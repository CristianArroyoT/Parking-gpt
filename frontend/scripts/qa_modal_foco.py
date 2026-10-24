"""QA: el modal de cambio de contraseña gestiona el foco.

POR QUÉ ESTA QA (T-170, 2026-10-24)
-----------------------------------
El diálogo de "Cambiar contraseña" (``AppLayout.vue``) tenía
``aria-modal="true"`` pero no llevaba el foco: al abrirlo, el foco se
quedaba en el ``<body>``, el ``Tab`` recorría la página que estaba
DETRÁS del overlay y el ``Escape`` sólo cerraba por casualidad.

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo):
  - al abrir:  ``document.activeElement`` = ``BODY`` (fuera del dialogo)
  - tras 6 Tab: el foco habia pasado por la pagina de behind y habia
                vuelto al dialogo por casualidad (INPUT#pwd-confirm)
  - tras Escape: el dialogo se cerraba (por casualidad: el foco ya
                estaba dentro) y el foco se perdia en el ``BODY``

Esta QA lo comprueba con un navegador de verdad:

1. al abrir, el foco tiene que estar DENTRO del dialogo;
2. el ``Tab`` (y el ``Shift+Tab``) tienen que quedar atrapados dentro:
   el foco no puede salir a la pagina de behind;
3. el ``Escape`` tiene que cerrar el dialogo;
4. al cerrar, el foco tiene que volver a un elemento de la pagina (no
   se puede perder en el ``<body>``).

Uso:
    python frontend/scripts/qa_modal_foco.py
    python frontend/scripts/qa_modal_foco.py --base http://127.0.0.1:4173

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


FOCO_DENTRO = """() => {
  const d = document.querySelector('[role="dialog"]')
  const a = document.activeElement
  if (!d) return { hayDialogo: false }
  return {
    hayDialogo: true,
    dentro: !!(a && d.contains(a)),
    etiqueta: a ? a.tagName + (a.id ? '#' + a.id : '') : null,
  }
}"""


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
            "SIN NAVEGADOR: no se puede comprobar el foco del modal "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

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

            # Abrir el modal: desplegable del usuario -> "Cambiar contraseña".
            pagina.locator('[aria-haspopup="menu"]').first.click()
            pagina.get_by_role("menuitem", name="Cambiar contraseña").click()
            try:
                pagina.wait_for_selector('[role="dialog"]', timeout=10000)
            except Exception:
                print("FALLO: el modal de cambiar contrasena no se abrio")
                return 1

            # 1. El foco tiene que entrar en el dialogo.
            foco = pagina.evaluate(FOCO_DENTRO)
            if not foco.get("dentro"):
                print(
                    "FALLO: el modal no took el foco: al abrirlo el foco "
                    f"seguia en {foco.get('etiqueta')!r} (fuera del dialogo)"
                )
                return 1
            print(f"OK: al abrir, el foco esta dentro del dialogo ({foco['etiqueta']})")

            # 2. El Tab no puede salir del overlay.
            for numero in range(1, 9):
                pagina.keyboard.press("Tab")
                foco = pagina.evaluate(FOCO_DENTRO)
                if not foco.get("dentro"):
                    print(
                        f"FALLO: el Tab se salio del dialogo (pulsacion {numero}): "
                        f"el foco fue a {foco.get('etiqueta')!r}, a la pagina de "
                        "detras del overlay"
                    )
                    return 1
            for numero in range(1, 4):
                pagina.keyboard.press("Shift+Tab")
                foco = pagina.evaluate(FOCO_DENTRO)
                if not foco.get("dentro"):
                    print(
                        f"FALLO: el Shift+Tab se salio del dialogo (pulsacion "
                        f"{numero}): el foco fue a {foco.get('etiqueta')!r}"
                    )
                    return 1
            print("OK: el Tab y el Shift+Tab quedan atrapados dentro del dialogo")

            # 3. El Escape cierra el modal.
            pagina.keyboard.press("Escape")
            pagina.wait_for_timeout(500)
            if pagina.locator('[role="dialog"]').count():
                print("FALLO: el Escape no cerro el modal")
                return 1
            print("OK: el Escape cierra el modal")

            # 4. Al cerrar, el foco vuelve a la pagina (no se pierde).
            activo = pagina.evaluate(
                """() => {
                  const a = document.activeElement
                  if (!a) return { esBody: true, visible: false, etiqueta: null }
                  return {
                    esBody: a === document.body,
                    visible: a.getClientRects().length > 0,
                    etiqueta: a.tagName + (a.id ? '#' + a.id : ''),
                    tieneMenu: a.getAttribute('aria-haspopup') === 'menu',
                  }
                }"""
            )
            if activo.get("esBody") or not activo.get("visible"):
                print(
                    "FALLO: al cerrar el modal el foco se perdio en el <body> "
                    f"(activo: {activo.get('etiqueta')!r})"
                )
                return 1
            print(
                f"OK: al cerrar, el foco vuelve a la pagina "
                f"({activo.get('etiqueta')})"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            contexto.close()
            navegador.close()

    print("OK: el modal de cambiar contrasena gestiona el foco")
    return 0


if __name__ == "__main__":
    sys.exit(main())
