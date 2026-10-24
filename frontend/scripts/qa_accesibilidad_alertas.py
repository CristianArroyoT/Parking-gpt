"""QA: los errores de formulario se ANUNCAN (role="alert").

POR QUÉ ESTA QA (T-169, 2026-10-24)
----------------------------------
``role="alert"`` faltaba en varias vistas. El texto del error se
**veía**, pero un lector de pantalla no lo anuncia: el usuario con
Talkback o NVDA se queda sin saber que el login ha fallado hasta que
navega por la página.

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo):
ninguno de los seis sitios de esta QA tenía ``[role="alert"]``:

  1. login                    (LoginView)
  2. reset de contraseña      (cliente/ResetPasswordView)
  3. alta manual              (operador/ManualEntryView)
  4. detalle de un ticket     (cliente/TicketsView)
  5. modal de incidente       (operador/IncidentModal)
  6. vista en vivo de la calibración (gestor/CalibrateView)

OJO: el login falso cuenta para el rate-limit del backend (10 por IP
cada 5 min en producción; 50 en desarrollo).

Si algún caso no se puede comprobar (falta el dato de demo que
necesita), la QA lo dice y devuelve 3 («no comprobado»): un verde
sobre una comprobación que no se ha hecho no vale.

Uso:
    python frontend/scripts/qa_accesibilidad_alertas.py
    python frontend/scripts/qa_accesibilidad_alertas.py --base http://127.0.0.1:4173

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

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost'. En Windows,
# 'localhost' resuelve primero a IPv6 (::1) y el dev-server de Vite
# no escucha en IPv6: por ahi no contesta (timeout de 30 s) y la QA
# parece estar rota cuando todo esta bien.
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
SIN_NAVEGADOR = 3
CUENTA_CLIENTE = ("cliente.demo@solidapp.es", "cliente1234")
CUENTA_OPERADOR = ("operador.madrid@solidapp.es", "oper12345")
CUENTA_GESTOR = ("gestor.madrid@solidapp.es", "gestor1234")

OK = "OK"
FALLO = "FALLO"
NO_COMPROBABLE = "NO_COMPROBABLE"

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


def textos_de_alertas(pagina) -> list[str]:
    """Textos de las regiones vivas ``[role="alert"]`` de la página."""
    return pagina.evaluate(
        """() => Array.from(document.querySelectorAll('[role="alert"]'))
                    .map((el) => (el.textContent || '').trim())
                    .filter((t) => t.length > 0)"""
    )


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


def _comprobar_alerta(pagina, donde: str, esperado: str) -> str | None:
    """Devuelve None si el error se anuncia, o el motivo del fallo."""
    alertas = textos_de_alertas(pagina)
    for texto in alertas:
        if esperado.casefold() in texto.casefold():
            return None
    if alertas:
        return (
            f"FALLO ({donde}): el error se ve pero NO se anuncia: hay "
            f"{len(alertas)} region(es) [role=alert] y ninguna dice "
            f"{esperado!r} (dicen: {alertas!r})"
        )
    return (
        f"FALLO ({donde}): el error no se anuncia: la pagina no tiene "
        f"ningun [role=\"alert\"] (0 regiones vivas)"
    )


def _esperar_texto(pagina, texto: str, timeout: int = 15000) -> bool:
    try:
        pagina.get_by_text(texto).first.wait_for(timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── Caso 1: el login ──────────────────────────────────────────────────
def caso_login(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", "noexiste@solidapp.es")
        pagina.fill("input[type=password]", "esta-no-es-la-clave")
        pagina.click("button[type=submit]")
        pagina.wait_for_selector("p.text-rose-600", timeout=15000)
        motivo = _comprobar_alerta(pagina, "login", "inválid")
        if motivo:
            return FALLO, motivo
        return OK, "el error del login se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (login): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


# ── Caso 2: el reset de contraseña ───────────────────────────────────
def caso_reset(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        pagina.goto(
            f"{base}/recuperar-contrasena?token=QA-T169",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        pagina.fill("#new-password", "ClaveDePrueba123")
        pagina.fill("#confirm-password", "OtraClaveDePrueba456")
        pagina.click("button[type=submit]")
        pagina.wait_for_selector("p.text-rose-600", timeout=15000)
        motivo = _comprobar_alerta(pagina, "reset de contrasena", "no coinciden")
        if motivo:
            return FALLO, motivo
        return OK, "el error del reset de contrasena se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (reset de contrasena): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


# ── Casos 3 y 5: el alta manual y el modal de incidente (operador) ─────
def caso_alta_manual(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        ok, motivo = _login(pagina, *CUENTA_OPERADOR, base)
        if not ok:
            return FALLO, f"FALLO (alta manual): no se pudo iniciar sesion: {motivo}"
        # El backend devuelve un error: la vista lo pinta y tiene que
        # anunciarlo.
        pagina.route(
            "**/api/v1/tickets/manual",
            lambda ruta: ruta.fulfill(
                status=409,
                content_type="application/json",
                body='{"detail":"Prueba QA T-169"}',
            ),
        )
        pagina.goto(
            f"{base}/operador/alta-manual", wait_until="domcontentloaded", timeout=30000
        )
        pagina.wait_for_selector('input[inputmode="numeric"]', timeout=15000)
        pagina.fill('input[inputmode="numeric"]', "1234")
        pagina.fill('input[maxlength="3"]', "ABC")
        pagina.click('button[type="submit"]')
        pagina.wait_for_selector("p.text-rose-800", timeout=15000)
        motivo = _comprobar_alerta(pagina, "alta manual", "QA T-169")
        if motivo:
            return FALLO, motivo
        return OK, "el error del alta manual se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (alta manual): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


def caso_incidente(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        ok, motivo = _login(pagina, *CUENTA_OPERADOR, base)
        if not ok:
            return FALLO, f"FALLO (incidente): no se pudo iniciar sesion: {motivo}"
        pagina.route(
            "**/api/v1/incidents/parkings/*",
            lambda ruta: ruta.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail":"Prueba QA T-169 incidente"}',
            ),
        )
        pagina.goto(f"{base}/vivo", wait_until="domcontentloaded", timeout=30000)
        try:
            pagina.get_by_role("button", name="Marcar plaza como averiada").first.click(
                timeout=15000
            )
        except Exception as exc:  # noqa: BLE001
            return (
                NO_COMPROBABLE,
                f"no se pudo abrir el modal de incidente: {type(exc).__name__}: {exc}",
            )
        pagina.wait_for_timeout(600)
        # Si hay plazas, se elige la primera (si no, el propio formulario
        # avisa y el error sale igualmente, pero con otro texto).
        select_espacio = pagina.locator("select").first
        if select_espacio.count():
            try:
                opciones = select_espacio.locator("option")
                if opciones.count() > 1:
                    select_espacio.select_option(index=1)
            except Exception:  # noqa: BLE001
                pass
        pagina.get_by_role("button", name="Registrar incidente").first.click(timeout=15000)
        if not _esperar_texto(pagina, "QA T-169 incidente"):
            return FALLO, "FALLO (incidente): el backend no devolvio el error esperado"
        motivo = _comprobar_alerta(pagina, "incidente", "QA T-169 incidente")
        if motivo:
            return FALLO, motivo
        return OK, "el error del modal de incidente se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (incidente): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


# ── Caso 4: el detalle de un ticket (cliente) ─────────────────────────
def caso_ticket(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        ok, motivo = _login(pagina, *CUENTA_CLIENTE, base)
        if not ok:
            return FALLO, f"FALLO (ticket): no se pudo iniciar sesion: {motivo}"
        pagina.goto(f"{base}/mis-tickets", wait_until="domcontentloaded", timeout=30000)
        try:
            pagina.wait_for_selector("li, tbody tr", timeout=15000)
        except Exception:
            return (
                NO_COMPROBABLE,
                "el cliente de la demo no tiene tickets: no se puede comprobar",
            )
        pagina.route(
            "**/api/v1/tickets/*",
            lambda ruta: ruta.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail":"Prueba QA T-169 ticket"}',
            ),
        )
        pagina.locator("li, tbody tr").first.click()
        if not _esperar_texto(pagina, "QA T-169 ticket"):
            return FALLO, "FALLO (ticket): el detalle no devolvio el error esperado"
        motivo = _comprobar_alerta(pagina, "ticket", "QA T-169 ticket")
        if motivo:
            return FALLO, motivo
        return OK, "el error del detalle del ticket se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (ticket): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


# ── Caso 6: la vista en vivo de la calibración (gestor) ───────────────
def caso_calibracion(navegador, base: str) -> tuple[str, str]:
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    try:
        ok, motivo = _login(pagina, *CUENTA_GESTOR, base)
        if not ok:
            return FALLO, f"FALLO (calibracion): no se pudo iniciar sesion: {motivo}"
        # Se busca una camara real de la demo (la ruta de calibracion la
        # necesita en la URL).
        ids = pagina.evaluate(
            """async () => {
              const tok = sessionStorage.getItem('solidapp.access')
              const h = { Authorization: 'Bearer ' + tok }
              const p = await (await fetch('/api/v1/parkings', { headers: h })).json()
              if (!Array.isArray(p) || !p.length) return null
              const c = await (await fetch('/api/v1/parkings/' + p[0].id + '/cameras', { headers: h })).json()
              if (!Array.isArray(c) || !c.length) return null
              return { parking: p[0].id, camera: c[0].id }
            }"""
        )
        if not ids:
            return (
                NO_COMPROBABLE,
                "la demo no tiene sucursales con camaras: no se puede comprobar",
            )
        # El stream MJPEG falla: el <img> dispara su evento de error.
        pagina.route(
            "**/api/v1/parkings/*/cameras/*/live*",
            lambda ruta: ruta.fulfill(status=404, content_type="text/plain", body="sin stream"),
        )
        pagina.goto(
            f"{base}/calibrate/{ids['parking']}/{ids['camera']}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        try:
            pagina.get_by_role("button", name="Ver en vivo").first.click(timeout=15000)
        except Exception as exc:  # noqa: BLE001
            return (
                NO_COMPROBABLE,
                f"no se pudo abrir la vista en vivo: {type(exc).__name__}: {exc}",
            )
        if not _esperar_texto(pagina, "No se pudo conectar al stream"):
            return FALLO, "FALLO (calibracion): el stream no dio el error esperado"
        motivo = _comprobar_alerta(
            pagina, "calibracion", "No se pudo conectar al stream"
        )
        if motivo:
            return FALLO, motivo
        return OK, "el error de la vista en vivo se anuncia con role=alert"
    except Exception as exc:  # noqa: BLE001
        return FALLO, f"FALLO (calibracion): {type(exc).__name__}: {exc}"
    finally:
        contexto.close()


CASOS = [
    ("login", caso_login),
    ("reset de contrasena", caso_reset),
    ("alta manual", caso_alta_manual),
    ("ticket", caso_ticket),
    ("incidente", caso_incidente),
    ("calibracion", caso_calibracion),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar el anuncio de errores "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    fallos = 0
    sin_comprobar = 0
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            for nombre, caso in CASOS:
                estado, mensaje = caso(navegador, base)
                if estado == OK:
                    print(f"OK ({nombre}): {mensaje}")
                elif estado == NO_COMPROBABLE:
                    sin_comprobar += 1
                    print(f"NO COMPROBADO ({nombre}): {mensaje}")
                else:
                    fallos += 1
                    print(mensaje)
        finally:
            navegador.close()

    if fallos:
        print(f"\nFALLO: {fallos} de {len(CASOS)} errores de formulario no se anuncian")
        return 1
    if sin_comprobar:
        print(
            f"\nNO COMPROBADO: {sin_comprobar} de {len(CASOS)} casos no se "
            "pudieron comprobar (falta el dato de demo): no es un verde"
        )
        return SIN_NAVEGADOR
    print(f"\nOK: los {len(CASOS)} errores de formulario se anuncian (role=alert)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
