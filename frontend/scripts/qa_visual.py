"""QA visual de las pantallas de solidAPP con Chromium headless (Playwright).

Recorre las pantallas del frontend real (Vite en :5173) con las cuentas
**demo** del seed, y para cada una:

- hace una captura de pantalla,
- recoge los **errores de consola**,
- recoge las **peticiones de red que fallan** (4xx/5xx),
- y anota si la pantalla se queda en blanco o en carga infinita.

Sirve para lo que los tests no cubren: que la pantalla **se renderice**.

Uso:
    python qa_visual.py --salida D:\\tmp\\qa-solidapp
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

BASE = "http://localhost:5173"

# (etiqueta, ruta, rol, nombre de fichero)
PANTALLAS = [
    ("login", "/login", "ninguno", "login"),
    ("recuperar-sin-token", "/recuperar-contrasena", "ninguno", "recuperar-sin-token"),
    ("recuperar-con-token", "/recuperar-contrasena?token=abc123", "ninguno", "recuperar-con-token"),
    ("gestor-dashboard", "/dashboard/gestor", "gestor", "gestor-dashboard"),
    ("gestor-movimientos", "/gestor/movimientos", "gestor", "gestor-movimientos"),
    ("gestor-alertas", "/gestor/alertas", "gestor", "gestor-alertas"),
    ("gestor-operadores", "/gestor/operadores", "gestor", "gestor-operadores"),
    ("gestor-mapa", "/mapa", "gestor", "gestor-mapa"),
    ("gestor-camaras", "/cameras", "gestor", "gestor-camaras"),
    ("operador-vivo", "/vivo", "gestor", "operador-vivo"),
    ("operador-alta", "/operador/alta-manual", "gestor", "operador-alta"),
    ("cliente-tickets", "/mis-tickets", "cliente", "cliente-tickets"),
    ("cliente-vehiculos", "/mis-vehiculos", "cliente", "cliente-vehiculos"),
    ("cliente-perfil", "/mi-perfil", "cliente", "cliente-perfil"),
    ("cliente-plan", "/mi-plan", "cliente", "cliente-plan"),
    ("cliente-plaza", "/mi-plaza", "cliente", "cliente-plaza"),
    ("cliente-pagos", "/pagos", "cliente", "cliente-pagos"),
    ("admin-planes", "/admin/planes", "admin", "admin-planes"),
    ("admin-usuarios", "/admin/users", "admin", "admin-usuarios"),
    ("admin-tarifas", "/admin/tariffs", "admin", "admin-tarifas"),
    ("admin-reportes", "/admin/reports", "admin", "admin-reportes"),
]

CUENTAS = {
    "admin": ("admin@solidapp.es", "admin12345"),
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
    "cliente": ("cliente.demo@solidapp.es", "cliente1234"),
}


@dataclass
class Resultado:
    etiqueta: str
    ruta: str
    url_final: str
    ancho: int = 0
    consola: list[str] = field(default_factory=list)
    red: list[str] = field(default_factory=list)
    texto: str = ""
    vacia: bool = False
    captura: str = ""
    desbordes: list[str] = field(default_factory=list)


#: JavaScript que detecta contenido que **no cabe** en su sitio.
#:
#: Dos casos, los dos fallos reales de maquetación:
#:
#: 1. **Recortado**: el contenido es más ancho que su caja y la caja lo
#:    recorta (``overflow-x: hidden/clip``) sin dejar desplazarlo. El
#:    usuario ve la columna a medias y no puede llegar al resto.
#: 2. **Desbordado**: el contenido es más ancho que su caja y nadie lo
#:    recorta ni lo deja desplazar: se sale de la tarjeta y lo tapa el
#:    panel de al lado (el caso de Operadores a 1232 px: la tabla se
#:    salía de su mitad de la rejilla y el badge "Activo" quedaba bajo
#:    el formulario de al lado).
#:
#: Se ignoran los elementos posicionados en absoluto o fijo (menús,
#: desplegables y tooltips: su desbordamiento es intencionado).
JS_DESBORDES = """
() => {
  const fuera = [];
  const etiqueta = (el) => {
    const t = (el.innerText || '').trim().split('\\n')[0].slice(0, 40);
    return el.tagName.toLowerCase() +
      (el.className && typeof el.className === 'string'
        ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.')
        : '') +
      (t ? ` [${t}]` : '');
  };
  const desplazable = (el) => {
    for (let a = el.parentElement; a; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  document.querySelectorAll('body *').forEach((el) => {
    if (el.scrollWidth <= el.clientWidth + 1 || el.clientWidth <= 0) return;
    const pos = getComputedStyle(el).position;
    if (pos === 'absolute' || pos === 'fixed') return;
    // Los controles de formulario (select, input, textarea) los recorta
    // el NAVEGADOR de forma nativa: el texto seleccionado se corta con
    // puntos suspensivos y el desplegable muestra el valor completo. No
    // es un defecto de maquetación, asi que no se reporta (si lo
    // estuviera, el detector acabaria marcando ruido y nadie lo miraria).
    if (el.matches('select, input, textarea')) return;
    const ox = getComputedStyle(el).overflowX;
    // Un contenedor con scroll propio es la SOLUCIÓN, no el defecto:
    // su contenido es más ancho a propósito y el usuario lo desplaza.
    if (ox === 'auto' || ox === 'scroll') return;
    if (desplazable(el)) return;
    const recortado = ox === 'hidden' || ox === 'clip';
    fuera.push(
      `${etiqueta(el)} (${el.scrollWidth}px en ${el.clientWidth}px)` +
      (recortado ? ' [recortado]' : ' [desbordado]')
    );
  });
  // La página entera con scroll horizontal también es un defecto de
  // maquetación: el usuario tiene que mover la ventana a los lados.
  const doc = document.documentElement;
  if (doc.scrollWidth > window.innerWidth + 1) {
    fuera.push(`documento con scroll horizontal (${doc.scrollWidth}px en ${window.innerWidth}px)`);
  }
  return fuera.slice(0, 6);
}
"""


def _desbordes(pagina: Page) -> list[str]:
    """Contenido que no cabe en su sitio (recortado o desbordado)."""
    try:
        return pagina.evaluate(JS_DESBORDES) or []
    except Exception as exc:  # noqa: BLE001 — la QA no debe abortar
        return [f"no se pudo evaluar el desbordamiento: {type(exc).__name__}"]


#: Páginas de mentira para probar el detector de desbordes.
#:
#: El detector es el que destapó los 26 desbordes del móvil, así que
#: tiene que quedar demostrado que sigue viendo. Cada página monta un
#: caso distinto del detector.
CASOS_DESBORDE: list[tuple[str, str, bool, str]] = [
    (
        "contenido recortado",
        "<div style='width:300px;overflow:hidden'><div style='width:900px'>ancho</div></div>",
        True,
        "[recortado]",
    ),
    (
        "contenido desbordado",
        "<div style='width:300px'><div style='width:900px'>ancho</div></div>",
        True,
        "[desbordado]",
    ),
    (
        "contenido con scroll propio (la solucion, no el defecto)",
        "<div style='width:300px;overflow-x:auto'><div style='width:900px'>ancho</div></div>",
        False,
        "",
    ),
    (
        "contenido que cabe",
        "<div style='width:300px'>cabe</div>",
        False,
        "",
    ),
    (
        "pagina con scroll horizontal",
        "<div style='width:900px'>ancho</div>",
        True,
        "documento con scroll horizontal",
    ),
]


def _autoprueba() -> int:
    """Comprueba que el detector de desbordes SIGUE detecting.

    Una puerta que no se puede ver fallar no es una puerta. Este
    detector es el que destapo los 26 desbordes del movil: si dejara de
    verlos, la QA pasara todas las pantallas y nadie se enterara.
    """
    fallos = 0
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(viewport={"width": 360, "height": 800})
        for nombre, html, debe_detectar, marca in CASOS_DESBORDE:
            pagina.set_content(f"<html><body>{html}</body></html>")
            pagina.wait_for_timeout(60)
            encontrados = pagina.evaluate(JS_DESBORDES) or []
            detectado = bool(encontrados)
            if detectado != debe_detectar:
                fallos += 1
                print(
                    f"  FALLO: {nombre} -> detectado={detectado} "
                    f"(se esperaba {debe_detectar})"
                )
                continue
            if marca and not any(marca in e for e in encontrados):
                fallos += 1
                print(f"  FALLO: {nombre} -> detectado pero sin la marca {marca!r}")
                continue
            print(f"  OK: {nombre} -> {'detectado' if detectado else 'limpio'}")
        navegador.close()

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el detector de desbordes sigue viendo.")
    return 0


def _visitar(pagina: Page, ruta: str) -> str | None:
    """Abre una ruta y espera a que se calle la red.

    Devuelve un aviso si la red no se quedó quieta a tiempo, o ``None``
    si todo fue bien.

    OJO: esperar a "networkidle" **falla siempre** en las pantallas con
    vídeo en directo (SSE) y con el mapa (teselas que se piden al
    desplazarse). No es un fallo de la pantalla: es tráfico de fondo
    perpetuo. Por eso el timeout se trata como aviso y no como error de
    red, que es como se confundía antes.
    """
    try:
        pagina.goto(f"{BASE}{ruta}", wait_until="networkidle", timeout=15000)
    except PlaywrightTimeout:
        return "la red no se quedo quieta (video en directo o teselas del mapa)"
    except Exception as exc:  # noqa: BLE001 — la QA no debe abortar
        return f"navegacion: {type(exc).__name__}: {exc}"
    return None


def _login(page: Page, email: str, password: str) -> tuple[bool, str]:
    """Inicia sesión. Devuelve ``(ok, motivo_del_fallo)``.

    Es importante que **no lance**: si el servidor de desarrollo acaba
    de arrancar y tarda en responder, un timeout en la navegación
    tumbaría la QA entera y no dejaría revisar ninguna pantalla.

    El motivo importa: sin él, un fallo de login se reportaba como
    "no se pudo iniciar sesión" y no se distinguía un 429 (límite de
    intentos) de un timeout. Con el motivo, el 429 se ve.

    OJO con el 429: ``POST /auth/login`` tiene un rate-limit de 10
    intentos por IP cada 5 minutos. Por eso la QA **inicia sesión una
    sola vez por rol** y luego barre los anchos cambiando el viewport
    de la misma página: 3 inicios de sesión en total, no 3 por ancho.
    """
    estados: list[int] = []

    def _capturar(respuesta) -> None:
        if "/auth/login" in respuesta.url:
            estados.append(respuesta.status)

    page.on("response", _capturar)
    try:
        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill("input[type=email]", email)
        page.fill("input[type=password]", password)
        page.click("button[type=submit]")
    except Exception as exc:  # noqa: BLE001 — la QA no debe abortar
        return False, f"{type(exc).__name__}: {exc}"
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    except Exception as exc:  # noqa: BLE001
        estado = f" (HTTP {estados[-1]})" if estados else ""
        if estados and estados[-1] == 429:
            return False, (
                "HTTP 429: límite de intentos de login (10 por IP cada 5 min). "
                "No es un fallo de la pantalla: espera a que pase la ventana."
            )
        return False, f"no salió del login{estado}: {type(exc).__name__}"
    return True, ""


def _recorrer(
    pagina: Page,
    destino: Path,
    ancho: int,
    rol_esperado: str,
    consola: list[str],
    red: list[str],
    resultados: list[Resultado],
    avisos: list[str],
) -> None:
    """Recorre las pantallas de un rol (o las públicas) en un ancho."""
    for etiqueta, ruta, rol_needed, nombre in PANTALLAS:
        if rol_esperado == "ninguno":
            if rol_needed != "ninguno":
                continue
        elif rol_needed != rol_esperado:
            continue
        consola.clear()
        red.clear()
        aviso = _visitar(pagina, ruta)
        if aviso:
            avisos.append(f"{etiqueta} @{ancho}px: {aviso}")
        pagina.wait_for_timeout(700)
        texto = pagina.inner_text("body")[:400].strip()
        vacia = len(texto) < 40
        captura = destino / f"{nombre}.png"
        try:
            pagina.screenshot(path=str(captura), full_page=True)
        except Exception as exc:  # noqa: BLE001
            consola.append(f"captura: {type(exc).__name__}")
        resultados.append(
            Resultado(
                etiqueta=etiqueta,
                ruta=ruta,
                url_final=pagina.url,
                ancho=ancho,
                consola=list(consola[:6]),
                red=list(red[:6]),
                texto=texto,
                vacia=vacia,
                captura=str(captura),
                desbordes=_desbordes(pagina),
            )
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="D:/tmp/qa-solidapp")
    ap.add_argument(
        "--autoprueba", action="store_true",
        help="Comprueba que el detector de desbordes sigue viendo (no necesita la app)",
    )
    ap.add_argument(
        "--ancho", type=int, default=1440,
        help=(
            "Ancho del viewport en px. 1440 es el ancho de referencia; "
            "1232 reproduce el panel lateral del navegador integrado, "
            "donde se encontró el recorte de la columna 'Estado'."
        ),
    )
    ap.add_argument(
        "--anchos", default="",
        help=(
            "Varios anchos separados por comas, p. ej. '414,768,1024,1232,1440'. "
            "En un solo proceso: se inicia sesión UNA vez por rol y se cambia "
            "el viewport para cada ancho (si no, el rate-limit de login "
            "bloquea la QA a partir del cuarto ancho)."
        ),
    )
    args = ap.parse_args()
    if args.autoprueba:
        return _autoprueba()

    if args.anchos:
        anchos = [int(a.strip()) for a in args.anchos.split(",") if a.strip()]
    else:
        anchos = [args.ancho]
    if not anchos:
        print("No hay ningún ancho que comprobar.")
        return 2

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    altura = 900

    resultados: list[Resultado] = []
    errores_login: list[str] = []
    avisos: list[str] = []
    inicios_de_sesion = 0

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)

        # Las pantallas públicas (login, recuperación de contraseña) se
        # capturan en su propio contexto, SIN sesión: si se visitaran
        # después de iniciar sesión, el guard de ruta las redirigiría.
        contexto_publico = navegador.new_context(
            viewport={"width": anchos[0], "height": altura}
        )
        pagina_publica = contexto_publico.new_page()
        consola_publica: list[str] = []
        red_publica: list[str] = []
        pagina_publica.on(
            "console",
            lambda m: consola_publica.append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning") else None,
        )
        pagina_publica.on(
            "response",
            lambda r: red_publica.append(f"{r.status} {r.request.method} {r.url}")
            if r.status >= 400 else None,
        )
        for ancho in anchos:
            pagina_publica.set_viewport_size({"width": ancho, "height": altura})
            destino = salida / str(ancho) if len(anchos) > 1 else salida
            destino.mkdir(parents=True, exist_ok=True)
            _recorrer(
                pagina_publica, destino, ancho, "ninguno",
                consola_publica, red_publica, resultados, avisos,
            )
        contexto_publico.close()

        for rol in ("gestor", "cliente", "admin"):
            contexto = navegador.new_context(
                viewport={"width": anchos[0], "height": altura}
            )
            pagina = contexto.new_page()
            consola: list[str] = []
            red: list[str] = []
            # Los manejadores se registran **una vez** por página: antes se
            # registraban en cada pantalla y se acumulaban (21 pantallas x
            # 5 anchos = 105 manejadores disparando a la vez).
            pagina.on(
                "console",
                lambda m: consola.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None,
            )
            pagina.on(
                "response",
                lambda r: red.append(f"{r.status} {r.request.method} {r.url}")
                if r.status >= 400 else None,
            )
            email, password = CUENTAS[rol]
            ok, motivo = _login(pagina, email, password)
            inicios_de_sesion += 1
            if not ok:
                errores_login.append(f"{rol}: no se pudo iniciar sesión ({motivo})")
                contexto.close()
                continue

            for ancho in anchos:
                pagina.set_viewport_size({"width": ancho, "height": altura})
                destino = salida / str(ancho) if len(anchos) > 1 else salida
                destino.mkdir(parents=True, exist_ok=True)
                _recorrer(
                    pagina, destino, ancho, rol, consola, red, resultados, avisos,
                )
            contexto.close()
        navegador.close()

    informe = {
        "anchos": anchos,
        "inicios_de_sesion": inicios_de_sesion,
        "errores_login": errores_login,
        "avisos": avisos,
        "pantallas": [r.__dict__ for r in resultados],
    }
    (salida / "informe.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'pantalla':<24} {'ancho':>6} {'vacia':<6} consola/red/desbordes")
    for r in resultados:
        marca = "SI" if r.vacia else "no"
        print(
            f"{r.etiqueta:<24} {r.ancho:>6} {marca:<6} "
            f"{len(r.consola)}/{len(r.red)}/{len(r.desbordes)}"
        )
        for c in r.consola:
            print(f"    consola: {c[:160]}")
        for n in r.red:
            print(f"    red    : {n[:160]}")
        for d in r.desbordes:
            print(f"    DESBORDE: {d[:160]}")
    if errores_login:
        print("ERRORES DE LOGIN:", errores_login)
    if avisos:
        print("\nAVISOS (no son fallos):")
        for a in avisos:
            print(f"    {a[:160]}")
    total_desbordes = sum(len(r.desbordes) for r in resultados)
    if total_desbordes:
        print(f"\nATENCION: {total_desbordes} contenido(s) recortado(s) sin desplazar")
    print(f"\nCapturas e informe en {salida}")
    print(
        f"{len(resultados)} capturas · {len(anchos)} ancho(s) · "
        f"{inicios_de_sesion} inicio(s) de sesión"
    )
    return 1 if (total_desbordes or errores_login) else 0


if __name__ == "__main__":
    raise SystemExit(main())
