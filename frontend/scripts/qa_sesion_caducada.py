"""QA: cuando la sesión ya no se puede renovar, la app **expulsa al login**.

POR QUÉ ESTA QA (T-137, 2026-10-24)
------------------------------------
El backend avisa de que la sesión está muerta con el evento
``solidapp:sesion-caducada`` (T-110) y el store limpia el usuario. Pero el
guard del router **sólo corre al navegar**: el operador se quedaba en
la pantalla con los tickets y las cámaras ya descargados, y cada
petición posterior devolvía 401 sin mensaje (justo lo que el T-110
quería cerrar y quedó a medias en el frontend).

Esta QA lo comprueba **de extremo a extremo**, con un navegador de
verdad y **sin recargar** (recargar dispararía el guard, que ya manda a
/login, y el defecto no se vería):

1. se inicia sesión como gestor y se abre el mapa (que tiene datos);
2. se **mata** la sesión desde el navegador (``POST /auth/logout`` con el
   refresh actual ⇒ el backend lo blacklistea);
3. se pulsa **«Refrescar»** (una petición de la app, sin navegar): el
   401 dispara el interceptor, el refresh falla y se emite el evento;
4. la URL **tiene que acabar en** ``/login`` y los tokens tienen que
   estar borrados.

Uso:
    python frontend/scripts/qa_sesion_caducada.py
    python frontend/scripts/qa_sesion_caducada.py --base http://localhost:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar
(sin navegador o sin servidor).
"""

from __future__ import annotations

import argparse
import sys

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost'. En Windows,
# 'localhost' resuelve primero a IPv6 (::1) y el dev-server de Vite
# no escucha en IPv6: por ahi no contesta (timeout de 30 s) y la QA
# parece estar rota cuando todo esta bien.
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
CUENTAS = {
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
}
SIN_NAVEGADOR = 3

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    PlaywrightTimeout = TimeoutError  # type: ignore[assignment,misc]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


def _login(page, email: str, password: str, base: str) -> tuple[bool, str]:
    """Inicia sesión. No lanza: un fallo debe ser un resultado, no un error."""
    try:
        page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill("input[type=email]", email)
        page.fill("input[type=password]", password)
        page.click("button[type=submit]")
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _matar_la_sesion(page) -> bool:
    """Blacklistea el refresh actual: la sesión ya no se puede renovar."""
    return bool(
        page.evaluate(
            """async () => {
              const access = sessionStorage.getItem('solidapp.access')
              const refresh = sessionStorage.getItem('solidapp.refresh')
              if (!access || !refresh) return false
              const r = await fetch('/api/v1/auth/logout', {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: 'Bearer ' + access,
                },
                body: JSON.stringify({ refresh_token: refresh }),
              })
              return r.ok
            }"""
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar la sesion caducada "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    email, password = CUENTAS["gestor"]
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        try:
            ok, motivo = _login(pagina, email, password, base)
            if not ok:
                print(f"FALLO: no se pudo iniciar sesion: {motivo}")
                return 1

            # El mapa del gestor: tiene datos y un boton «Refrescar».
            # OJO: no se espera a "networkidle": el mapa tiene un SSE
            # abierto, asi que la red nunca se queda quieta (timeout).
            try:
                pagina.goto(f"{base}/mapa", wait_until="domcontentloaded", timeout=30000)
                pagina.get_by_role("button", name="Refrescar").first.wait_for(timeout=15000)
            except Exception as exc:  # noqa: BLE001
                print(f"FALLO: no se pudo abrir el mapa: {type(exc).__name__}: {exc}")
                return 1
            if "/login" in pagina.url:
                print("FALLO: la sesion no arranco (sigue en /login)")
                return 1

            if not _matar_la_sesion(pagina):
                print(
                    "FALLO: no se pudo invalidar la sesion "
                    "(falta el token o el backend no respondio)"
                )
                return 1

            # UNA peticion de la app, **sin navegar**: el 401 dispara el
            # interceptor, que renueva (y falla) y avisa con el evento.
            try:
                boton = pagina.get_by_role("button", name="Refrescar").first
                try:
                    boton.click(timeout=15000)
                except Exception as exc:  # noqa: BLE001
                    # T-180 (2026-10-24): el LiveView re-pinta el boton en
                    # cada ronda de polling, asi que el nodo puede detachmentarse
                    # entre la busqueda y el clic; con la maquina saturada los
                    # reintentos de Playwright se agotan. Se pulsa por
                    # JavaScript (mismo manejador): lo que se comprueba
                    # despues (que la URL acabe en /login) no cambia.
                    print(
                        "  (el boton se ha despegado; se pulsa por JavaScript: "
                        f"{type(exc).__name__})"
                    )
                    boton.evaluate("el => el.click()")
            except Exception as exc:  # noqa: BLE001
                print(f"FALLO: no se pudo pulsar Refrescar: {type(exc).__name__}: {exc}")
                return 1

            try:
                pagina.wait_for_url(lambda u: "/login" in u, timeout=15000)
            except PlaywrightTimeout:
                print(
                    "FALLO: la sesion caducada NO expulso al login "
                    f"(la URL se quedo en {pagina.url})"
                )
                return 1
            except Exception as exc:  # noqa: BLE001
                print(f"FALLO: {type(exc).__name__}: {exc}")
                return 1

            tokens = pagina.evaluate(
                """() => ({
                  access: sessionStorage.getItem('solidapp.access'),
                  refresh: sessionStorage.getItem('solidapp.refresh'),
                })"""
            )
            if tokens.get("access") or tokens.get("refresh"):
                print("FALLO: los tokens siguen en la sessionStorage")
                return 1

            print(
                "OK: la sesion caducada expulsa al login y borra los tokens "
                f"(URL: {pagina.url})"
            )
            return 0
        finally:
            navegador.close()


if __name__ == "__main__":
    sys.exit(main())
