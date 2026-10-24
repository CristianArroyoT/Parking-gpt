"""QA: los campos de los formularios de administración tienen nombre accesible.

POR QUÉ ESTA QA (T-171, 2026-10-24)
-----------------------------------
En los formularios de administración (sucursales, tarifas, usuarios,
planes, cams) y en el de cams, habia ``<label>`` sin ``for`` y sin
envolver el campo: el campo se anunciaba "sin nombre" (un lector de
pantalla no dice "Nombre" ni "Email", dice "campo de texto").

Medido el 2026-10-24 con un navegador de verdad (antes del arreglo),
contando los controles VISIBLES sin nombre accesible
(``el.labels.length === 0`` y sin ``aria-label``):

    /admin/parkings    6 campos (codigo, nombre, direccion, ciudad, lat, lng)
    /admin/tariffs     8 campos (sucursal, nombre, €/hora, €/fraccion, ...)
    /admin/users       5 campos (email, nombre, telefono, rol, contrasena)
    /admin/planes      5 campos (codigo, nombre, €/mes, descuento, vehiculos)
    /admin/costs       1 campo  (el <select> de filtro de sucursal)
    /admin/reports     1 campo  (el <select> de filtro de sucursal)
    /cameras           7 campos (filtro + los 6 del modal de alta)
                       ---
                       33 campos sin nombre

Esta QA los recorre TODOS con un navegador de verdad y exige que cada
control visible tenga un nombre accesible (una etiqueta asociada por
``for``, una etiqueta que lo envuelve, o un ``aria-label``).

OJO: si la pagina no llegara a pintarse, la comprobacion pasaria en
vacio (una puerta que no demuestra nada). Por eso la QA exige un
numero minimo de controles por vista.

Alcance: las vistas de administracion (``views/admin/*.vue``) y la de
camaras (``views/gestor/CamerasView.vue``), que es el alcance del
T-171. Las mismas carencias quedan en otras vistas (cliente,
operador, calibracion): se documentan aparte, no se comprueban aqui.

Uso:
    python frontend/scripts/qa_labels_admin.py
    python frontend/scripts/qa_labels_admin.py --base http://127.0.0.1:4173

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
CUENTA = ("admin@solidapp.es", "admin12345")

# (ruta, botones que hay que pulsar para abrir el formulario, minimo de
#  controles que tienen que aparecer: si no aparecen, la comprobacion
#  pasaria en vacio y no valeria como puerta).
VISTAS: list[tuple[str, list[str], int]] = [
    ("/admin/parkings", [], 7),
    ("/admin/tariffs", [], 8),
    ("/admin/users", [], 6),
    ("/admin/planes", ["Nueva suscripción"], 10),
    ("/admin/reports", [], 2),
    ("/admin/costs", ["Nuevo coste"], 3),
    ("/cameras", ["Añadir cámara"], 7),
]

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


CONTROLES = """() => {
  const out = []
  document.querySelectorAll('input, select, textarea').forEach((el) => {
    if (el.type === 'hidden') return
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) return
    const etiquetado = !!(el.labels && el.labels.length > 0)
    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')
    out.push({
      etiqueta: el.tagName,
      tipo: el.type || '',
      id: el.id || '',
      nombre: el.name || '',
      conNombre: etiquetado || !!aria,
      texto: etiquetado ? (el.labels[0].textContent || '').trim().slice(0, 40) : null,
    })
  })
  return out
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
            "SIN NAVEGADOR: no se puede comprobar los nombres de los campos "
            f"(falta playwright: {_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    email, password = CUENTA
    fallos: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        try:
            ok, motivo = _login(pagina, email, password, base)
            if not ok:
                print(f"FALLO: no se pudo iniciar sesion: {motivo}")
                return 1

            for ruta, botones, minimo in VISTAS:
                pagina.goto(f"{base}{ruta}", wait_until="domcontentloaded", timeout=30000)
                try:
                    pagina.wait_for_selector("h1", timeout=15000)
                except Exception:
                    print(f"FALLO: {ruta} no se pudo abrir")
                    return 1
                for boton in botones:
                    try:
                        pagina.get_by_role("button", name=boton).first.click(timeout=8000)
                        pagina.wait_for_timeout(600)
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"FALLO: {ruta}: no se pudo pulsar {boton!r}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        return 1
                # El componente es lazy: se espera a que se pinte.
                pagina.wait_for_timeout(2000)

                controles = pagina.evaluate(CONTROLES)
                if len(controles) < minimo:
                    print(
                        f"FALLO: {ruta}: solo se encontraron {len(controles)} "
                        f"controles (se esperaban al menos {minimo}): la "
                        "comprobacion pasaria en vacio y no valdria como puerta"
                    )
                    return 1
                sin_nombre = [c for c in controles if not c["conNombre"]]
                if sin_nombre:
                    detalle = ", ".join(
                        f"<{c['etiqueta'].lower()} id={c['id'] or '-'} "
                        f"tipo={c['tipo'] or '-'}>"
                        for c in sin_nombre
                    )
                    fallos.append(
                        f"FALLO ({ruta}): {len(sin_nombre)} de {len(controles)} "
                        f"campos se anuncian SIN NOMBRE: {detalle}"
                    )
                    print(fallos[-1])
                else:
                    print(f"OK ({ruta}): {len(controles)} controles, todos con nombre")
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            contexto.close()
            navegador.close()

    if fallos:
        print(f"\nFALLO: {len(fallos)} vista(s) con campos sin nombre accesible")
        return 1
    print("\nOK: todos los campos de administracion y de cams tienen nombre accesible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
