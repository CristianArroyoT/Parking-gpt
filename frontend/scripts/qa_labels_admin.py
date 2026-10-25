"""QA: los campos de los formularios tienen nombre accesible.

POR QUÉ ESTA QA (T-171, 2026-10-24; ampliada en T-182)
-------------------------------------------------------
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
    /admin/plans       5 campos (codigo, nombre, €/mes, descuento, vehiculos)
    /admin/costs       1 campo  (el <select> de filtro de sucursal)
    /admin/reports     1 campo  (el <select> de filtro de sucursal)
    /cameras           7 campos (filtro + los 6 del modal de alta)
                       ---
                       33 campos sin nombre

T-182 (2026-10-24) amplía el alcance a las CUATRO vistas que quedaban
fuera, y a los controles que no tenían etiqueta en absoluto (no sólo los
``<label>`` sin ``for``). Medido el 2026-10-24, ANTES del arreglo:

    /mis-vehiculos                 3 campos (el formulario de edicion:
                                       marca, modelo, color)
    /calibrate (geocerca nueva)    3 campos (plaza, umbral, direccion)
    /calibrate (geocerca el.)      2 campos (umbral, direccion)
    /operador/alta-manual          6 campos (sucursal, camara, plaza y los
                                       tres que NO tenian etiqueta: los dos
                                       de la matricula y las notas)
    /vivo (modal: averiada)        4 campos (plaza, motivo, fotos, notas)
    /vivo (modal: robo)            5 campos (plaza, motivo, matricula,
                                       fotos, notas)
                                    ---
                                    23 controles sin nombre

T-188 (2026-10-25): el ``<select>`` de sucursal de la PANTALLA "En vivo" (LiveView)
ya tiene nombre accesible (``aria-label="Sucursal"``: se midió sin él en el
T-182) y la QA lo vigila en la escena "/vivo (la página)". Antes este aviso
era cierto y el arreglo lo aplicó el T-182: el texto se había quedado
desactualizado y daba por cerrado algo que ya no lo estaba.

Esta QA los recorre TODOS con un navegador de verdad y exige que cada
control visible tenga un nombre accesible (una etiqueta asociada por
``for``, una etiqueta que lo envuelve, o un ``aria-label``).

OJO: si la pagina no llegara a pintarse, la comprobacion pasaria en
vacio (una puerta que no demuestra nada). Por eso la QA exige un
numero minimo de controles por escena.

OJO: cada escena entra con la cuenta que le toca (el cliente ve "sus
vehiculos", el gestor calibra y el operador da de alta). Cada cuenta
usa su propio contexto de Playwright, porque el ``sessionStorage`` (donde
va el correo) se hereda dentro del mismo contexto.

Uso:
    python frontend/scripts/qa_labels_admin.py
    python frontend/scripts/qa_labels_admin.py --base http://127.0.0.1:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

# La consola de Windows es cp1252: si el texto trae un caracter que no
# cabe, se sustituye en vez de reventar la QA al final.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost' (ver AGENTS.md).
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
SIN_NAVEGADOR = 3

# Las cuentas demo del seed (tools/verificar_cuentas_demo.py lo vigila).
CUENTAS: dict[str, tuple[str, str]] = {
    "admin": ("admin@solidapp.es", "admin12345"),
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
    "operador": ("operador.madrid@solidapp.es", "oper12345"),
    "cliente": ("cliente.demo@solidapp.es", "cliente1234"),
}

# Matricula del vehiculo de prueba del cliente (el backend no tiene DELETE
# para vehiculos, asi que la QA reutiliza el que ya hay en vez de crear
# uno nuevo en cada corrida).
MATRICULA_QA = "1820QAT"

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


CONTROLES = """(ambito) => {
  const raiz = ambito ? document.querySelector(ambito) : document
  if (!raiz) return null
  const out = []
  raiz.querySelectorAll('input, select, textarea').forEach((el) => {
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


# ── Preparaciones (lo que hay que hacer antes de medir) ────────────────────

def _arrastrar(pagina) -> None:
    """Arrastra sobre el lienzo de la cámara: abre el formulario de la
    geocerca nueva (si no, el panel lateral no tiene ningún campo)."""
    svg = pagina.locator('svg[viewBox="0 0 960 540"]').first
    caja = svg.bounding_box()
    if not caja:
        raise RuntimeError("no se encontro el lienzo de la camara")
    x = caja["x"] + caja["width"] * 0.3
    y = caja["y"] + caja["height"] * 0.3
    pagina.mouse.move(x, y)
    pagina.mouse.down()
    pagina.mouse.move(x + 120, y + 90, steps=8)
    pagina.mouse.up()
    pagina.wait_for_timeout(1200)


def _ir_a_una_camara(pagina, base: str) -> None:
    """Abre la calibración de la primera cámara de la sucursal (el id va en
    la ruta: no se escribe a mano, que se quedaría viejo)."""
    pagina.goto(f"{base}/cameras", wait_until="domcontentloaded", timeout=30000)
    pagina.wait_for_selector("h1", timeout=30000)
    pagina.wait_for_timeout(2500)
    pagina.get_by_role("link", name="Calibrar").first.click(timeout=30000)
    pagina.wait_for_url(lambda u: "/calibrate/" in u, timeout=30000)
    # Se espera al boton "Ver en vivo", que solo existe en la calibracion:
    # esperando el <h1> se podria medir todavia la pantalla de camaras (el
    # h1 de la lista de camaras sigue en el DOM un instante).
    pagina.get_by_role("button", name="Ver en vivo").wait_for(timeout=30000)
    pagina.wait_for_timeout(2500)


def _crear_geocerca(pagina) -> None:
    """Crea una geocerca (flujo real de la pantalla)."""
    pagina.get_by_role("button", name="Crear").click(timeout=15000)
    pagina.wait_for_timeout(400)
    _arrastrar(pagina)
    guardar = pagina.get_by_role("button", name="Guardar geocerca")
    if not guardar.is_enabled():
        raise RuntimeError("no hay plaza libre para la geocerca de prueba")
    guardar.click(timeout=15000)
    pagina.wait_for_timeout(2000)


def _borrar_geocerca(pagina) -> None:
    """Borra la geocerca que creó la QA (confirmación nativa)."""
    pagina.on("dialog", lambda d: d.accept())
    pagina.get_by_role("button", name="Eliminar geocerca").click(timeout=15000)
    pagina.wait_for_timeout(2000)


class Escena:
    """Una comprobación: qué pantalla, con qué cuenta y qué hay que mirar.

    ``minimo`` es el número de controles que tienen que aparecer: si la
    pantalla no se pintara, la comprobación pasaría en vacío y no valdría
    como puerta.
    """

    def __init__(
        self,
        nombre: str,
        cuenta: str,
        ruta: str,
        minimo: int,
        botones: tuple[str, ...] = (),
        ambito: str | None = None,
        preparar: Callable[..., None] | None = None,
        limpiar: Callable[..., None] | None = None,
    ) -> None:
        self.nombre = nombre
        self.cuenta = cuenta
        self.ruta = ruta
        self.minimo = minimo
        self.botones = botones
        self.ambito = ambito
        self.preparar = preparar
        self.limpiar = limpiar


def prep_vehiculos(pagina, base: str, estado: dict) -> None:
    """Abre el formulario de edición y el de vínculo: son los dos que tienen
    campos que sólo existen al pulsarlos."""
    pagina.wait_for_selector("h1", timeout=30000)
    pagina.wait_for_timeout(1500)
    if not pagina.get_by_role("button", name="Editar").count():
        # El cliente demo no tiene vehículos: se crea uno por el flujo real
        # (no hay DELETE para vehículos, así que no se puede borrar después:
        # las siguientes corridas reutilizan el que ya está).
        pagina.fill("#veh-matricula", MATRICULA_QA)
        pagina.get_by_role("button", name="Añadir", exact=True).click(timeout=15000)
        pagina.wait_for_timeout(2500)
    editar = pagina.get_by_role("button", name="Editar")
    if not editar.count():
        raise RuntimeError(
            "el cliente no tiene ningun vehiculo: no se puede medir el "
            "formulario de edicion"
        )
    editar.first.click(timeout=15000)
    pagina.wait_for_timeout(700)
    vincular = pagina.get_by_role("button", name="Vincular persona")
    if not vincular.count():
        raise RuntimeError("no se pudo abrir el formulario de vinculo")
    vincular.first.click(timeout=15000)
    pagina.wait_for_timeout(700)


def prep_calibrate_nueva(pagina, base: str, estado: dict) -> None:
    """El panel de la geocerca nueva (plaza, umbral y dirección)."""
    _ir_a_una_camara(pagina, base)
    _arrastrar(pagina)
    if not pagina.get_by_text("Plaza a asignar").count():
        raise RuntimeError("el arrastre no abrio el formulario de la geocerca")


def prep_calibrate_seleccionada(pagina, base: str, estado: dict) -> None:
    """El panel de la geocerca seleccionada (umbral y dirección).

    Si la cámara no tiene ninguna geocerca, se crea una para poder medir el
    panel y se borra al final (si no, ese panel no saldría nunca y el
    comité no vigilaría esos dos campos)."""
    _ir_a_una_camara(pagina, base)
    pagina.get_by_role("button", name="Seleccionar").click(timeout=15000)
    pagina.wait_for_timeout(600)
    items = pagina.locator("aside ul li")
    if not items.count():
        _crear_geocerca(pagina)
        estado["creada"] = True
        pagina.get_by_role("button", name="Seleccionar").click(timeout=15000)
        pagina.wait_for_timeout(600)
        items = pagina.locator("aside ul li")
        if not items.count():
            raise RuntimeError("no se pudo crear una geocerca para medirla")
    items.first.click(timeout=15000)
    pagina.wait_for_timeout(900)


def limpiar_calibrate_seleccionada(pagina, estado: dict) -> None:
    """Borra la geocerca que creó la QA (sólo si la creó ella)."""
    if not estado.get("creada"):
        return
    _borrar_geocerca(pagina)


def prep_modal_robo(pagina, base: str, estado: dict) -> None:
    """Abre el modal de incidentes en la pestaña de robo (la de averiada es
    la que sale por defecto)."""
    pagina.get_by_role("button", name="Marcar plaza como averiada").first.click(timeout=15000)
    pagina.wait_for_timeout(1200)
    pagina.locator('[role="dialog"]').get_by_role("button", name="Robo").first.click(
        timeout=30000
    )
    pagina.wait_for_timeout(900)


ESCENAS: list[Escena] = [
    # ── las de administración (T-171) ──────────────────────────────────
    Escena("/admin/parkings", "admin", "/admin/parkings", 7),
    Escena("/admin/tariffs", "admin", "/admin/tariffs", 8),
    Escena("/admin/users", "admin", "/admin/users", 6),
    Escena("/admin/planes", "admin", "/admin/planes", 10, botones=("Nueva suscripción",)),
    Escena("/admin/reports", "admin", "/admin/reports", 2),
    Escena("/admin/costs", "admin", "/admin/costs", 3, botones=("Nuevo coste",)),
    Escena("/cameras", "admin", "/cameras", 7, botones=("Añadir cámara",)),
    # ── las cuatro vistas nuevas (T-182) ───────────────────────────────
    Escena(
        "/mis-vehiculos",
        "cliente",
        "/mis-vehiculos",
        9,
        preparar=prep_vehiculos,
    ),
    Escena(
        "/calibrate (geocerca nueva)",
        "gestor",
        "/cameras",
        3,
        preparar=prep_calibrate_nueva,
    ),
    Escena(
        "/calibrate (geocerca seleccionada)",
        "gestor",
        "/cameras",
        2,
        preparar=prep_calibrate_seleccionada,
        limpiar=limpiar_calibrate_seleccionada,
    ),
    Escena(
        "/operador/alta-manual",
        "operador",
        "/operador/alta-manual",
        9,
    ),
    Escena(
        "/vivo (la página)",
        "operador",
        "/vivo",
        1,
    ),
    Escena(
        "/vivo (modal de incidentes: averiada)",
        "operador",
        "/vivo",
        4,
        botones=("Marcar plaza como averiada",),
        ambito='[role="dialog"]',
    ),
    Escena(
        "/vivo (modal de incidentes: robo)",
        "operador",
        "/vivo",
        5,
        preparar=prep_modal_robo,
        ambito='[role="dialog"]',
    ),
]


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

    fallos: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # Una sesion (contexto) por cuenta: el sessionStorage se hereda
        # dentro del mismo contexto, y cada rol ve pantallas distintas.
        sesiones: dict[str, tuple[object, object]] = {}
        try:
            for escena in ESCENAS:
                if escena.cuenta not in sesiones:
                    contexto = navegador.new_context()
                    pagina = contexto.new_page()
                    email, password = CUENTAS[escena.cuenta]
                    ok, motivo = _login(pagina, email, password, base)
                    if not ok:
                        print(
                            f"FALLO: no se pudo iniciar sesion como "
                            f"{escena.cuenta}: {motivo}"
                        )
                        return 1
                    sesiones[escena.cuenta] = (contexto, pagina)
                contexto, pagina = sesiones[escena.cuenta]

                estado: dict = {}
                try:
                    pagina.goto(f"{base}{escena.ruta}", wait_until="domcontentloaded", timeout=30000)
                    try:
                        pagina.wait_for_selector("h1", timeout=30000)
                    except Exception:
                        print(f"FALLO: {escena.nombre} no se pudo abrir")
                        return 1
                    for boton in escena.botones:
                        try:
                            pagina.get_by_role("button", name=boton).first.click(timeout=8000)
                            pagina.wait_for_timeout(600)
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"FALLO: {escena.nombre}: no se pudo pulsar {boton!r}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                            return 1
                    # El componente es lazy: se espera a que se pinte.
                    pagina.wait_for_timeout(2000)

                    if escena.preparar:
                        escena.preparar(pagina, base, estado)

                    controles = pagina.evaluate(CONTROLES, escena.ambito)
                    if controles is None:
                        print(
                            f"FALLO: {escena.nombre}: no se encontro el ambito "
                            f"{escena.ambito!r}: la comprobacion pasaria en vacio"
                        )
                        return 1
                    if len(controles) < escena.minimo:
                        print(
                            f"FALLO: {escena.nombre}: solo se encontraron "
                            f"{len(controles)} controles (se esperaban al menos "
                            f"{escena.minimo}): la comprobacion pasaria en vacio "
                            "y no valdria como puerta"
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
                            f"FALLO ({escena.nombre}): {len(sin_nombre)} de "
                            f"{len(controles)} campos se anuncian SIN NOMBRE: {detalle}"
                        )
                        print(fallos[-1])
                    else:
                        print(
                            f"OK ({escena.nombre}): {len(controles)} controles, "
                            "todos con nombre"
                        )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"FALLO: {escena.nombre}: {type(exc).__name__}: {exc}"
                    )
                    return 1
                finally:
                    if escena.limpiar:
                        try:
                            escena.limpiar(pagina, estado)
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"AVISO: {escena.nombre}: no se pudo limpiar lo "
                                f"que creó la QA: {type(exc).__name__}: {exc}"
                            )
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {type(exc).__name__}: {exc}")
            return 1
        finally:
            for contexto, _ in sesiones.values():
                contexto.close()
            navegador.close()

    if fallos:
        print(f"\nFALLO: {len(fallos)} escena(s) con campos sin nombre accesible")
        return 1
    print(
        "\nOK: todos los campos de administracion, de cams y de las cuatro "
        "vistas nuevas tienen nombre accesible"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
