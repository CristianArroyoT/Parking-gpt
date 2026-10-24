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

#: Playwright sólo hace falta para manejar el navegador. La autoprueba del
#: detector de desbordes **también** lo necesita (evalúa el JS en un
#: Chromium real), pero el MÓDULO tiene que poder importarse sin él: la
#: meta-puerta de las puertas corre este script en entornos donde
#: playwright no está instalado (el job "backend" del CI corre las
#: autopruebas antes del ``pip install``), y reventar con un
#: ``ModuleNotFoundError`` en la importacion seria un fallo de puerta
#: disfrazado de problema de codigo.
try:
    from playwright.sync_api import Page, sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    HAY_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - depende del entorno
    HAY_PLAYWRIGHT = False

    class PlaywrightTimeout(Exception):  # type: ignore[no-redef]
        """Sustituto: sin playwright no hay navegador al que esperar."""

    Page = object  # type: ignore[assignment,misc]
    sync_playwright = None  # type: ignore[assignment]

#: Código de salida de la autoprueba cuando no se puede comprobar.
SIN_NAVEGADOR = 3

#: Servidor contra el que se corre la QA por defecto: el de DESARROLLO
#: (Vite con HMR). Con ``--base`` se puede correr contra cualquier otro
#: (por ejemplo, el bundle de produccion servido por nginx).
# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost'. En Windows,
# 'localhost' resuelve primero a IPv6 (::1) y el dev-server de Vite
# no escucha en IPv6: por ahi no contesta (timeout de 30 s) y la QA
# parece estar rota cuando todo esta bien.
BASE_POR_DEFECTO = "http://127.0.0.1:5173"

# (etiqueta, ruta, rol, nombre de fichero)
#
# OJO (2026-10-22): esta lista la vigila ``tools/verificar_cobertura_frontend.py``,
# que comprueba que **toda** ruta del router aparece aquí. Faltaban cinco
# pantallas (el dashboard de admin, la lista de parkings, la de costes y las
# dos de error) y nadie se enteraba de que no se revisaban.
PANTALLAS = [
    ("login", "/login", "ninguno", "login"),
    ("recuperar-sin-token", "/recuperar-contrasena", "ninguno", "recuperar-sin-token"),
    ("recuperar-con-token", "/recuperar-contrasena?token=abc123", "ninguno", "recuperar-con-token"),
    ("forbidden", "/forbidden", "ninguno", "forbidden"),
    ("no-encontrada", "/ruta-que-no-existe", "ninguno", "no-encontrada"),
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
    ("admin-dashboard", "/dashboard", "admin", "admin-dashboard"),
    ("admin-parkings", "/admin/parkings", "admin", "admin-parkings"),
    ("admin-costes", "/admin/costs", "admin", "admin-costes"),
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


def _sin_respuesta(red: list[str], req) -> None:
    """Anota una peticion que NO recibio respuesta.

    OJO: ``net::ERR_ABORTED`` **no es un fallo**. Es el navegador
    cancelando una peticion que la app ya no espera: al cambiar de
    pantalla antes de que termine el fetch, o al cerrar el stream SSE
    (``/parkings/{id}/events``), que esta abierto por diseno hasta que
    se navega. Los 13 abortos que aparecieron al anadir esta escucha
    eran todos eso.

    Los demas fallos (conexion rechazada, DNS, reset, timeout) **si** son
    fallos, y si que deben poner la puerta en rojo.
    """
    fallo = str(req.failure or "")
    if "ERR_ABORTED" in fallo:
        CANCELADAS.append(f"{req.method} {req.url}")
        return
    red.append(f"SIN RESPUESTA {req.method} {req.url} ({fallo})")


#: Peticiones canceladas por la app (cambio de pantalla, cierre del SSE).
#: No son fallos: se informan aparte para que se vea.
CANCELADAS: list[str] = []


def _inyectar_sesion(pagina, almacen, base: str) -> None:
    """Pasa un ``sessionStorage`` a una pagina nueva.

    Los tokens viven en ``sessionStorage`` (son por pestana: ver
    ``frontend/src/api/client.ts``), asi que una pestana nueva empieza sin
    sesion. Se copia **todo** el almacen (sin escribir ninguna clave a
    mano: si el nombre de la clave cambia, esta comprobacion lo sigue
    detectando).

    La copia se hace sobre una pagina ya cargada **del origen de la app**:
    en ``about:blank`` el navegador deniega el acceso al almacenamiento
    ("Access is denied for this document"). Y el ``sessionStorage``
    sobrevive a las navegaciones siguientes (es por pestana y origen), asi
    que los tokens siguen ahi al ir a la ruta que se comprueba.
    """
    pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=20000)
    pagina.evaluate(
        "(d) => { for (const [k, v] of Object.entries(d)) "
        "sessionStorage.setItem(k, v) }",
        almacen,
    )


def _comprobar_modo_pwa(contexto, pagina, base: str) -> list[str]:
    """El modo PWA no puede quedarse "pegado" en el navegador (T-66).

    Antes, el flag ``?pwa=1`` se guardaba en ``localStorage`` para
    siempre: un admin que abria la app con el flag (o que instalaba la
    PWA de cliente) quedaba **encerrado** en las rutas de cliente para
    siempre en ese navegador, y la senal "recordada" tenia prioridad
    sobre la real (``display-mode: standalone``): no habia forma de
    volver al panel de admin.

    Se comprueba con el admin (que es quien queda encerrado):
      1. con ``?pwa=1``, una ruta de admin redirige a "Mis tickets";
      2. en OTRA pestana del mismo navegador (el ``localStorage`` se
         comparte entre pestanas) y sin el flag, la ruta de admin se
         respeta: el modo no se ha quedado pegado.

    Las dos comprobaciones van en paginas PROPIAS, con sus propios
    escuchadores: si contaminaran las listas de la QA, la puerta se
    pondria en rojo por ruido que no es de las pantallas.
    """
    fallos: list[str] = []
    almacen = pagina.evaluate(
        "() => Object.fromEntries(Object.entries(sessionStorage))"
    )

    # 1. Con el flag de la URL, el modo PWA esta activo.
    con_flag = contexto.new_page()
    try:
        _inyectar_sesion(con_flag, almacen, base)
        con_flag.goto(f"{base}/?pwa=1", wait_until="domcontentloaded", timeout=20000)
        con_flag.wait_for_timeout(1200)
        con_flag.goto(f"{base}/admin/users", wait_until="domcontentloaded", timeout=20000)
        con_flag.wait_for_timeout(1200)
        if "/mis-tickets" not in con_flag.url:
            fallos.append(
                "con ?pwa=1 la app deberia redirigir a 'Mis tickets' "
                f"(se quedo en {con_flag.url})"
            )
    except Exception as exc:  # noqa: BLE001
        fallos.append(f"no se pudo comprobar el modo PWA: {type(exc).__name__}: {exc}")
    finally:
        con_flag.close()

    # 2. En otra pestana, el flag no puede seguir frenando al admin.
    otra = contexto.new_page()
    try:
        _inyectar_sesion(otra, almacen, base)
        otra.goto(f"{base}/admin/users", wait_until="domcontentloaded", timeout=20000)
        otra.wait_for_timeout(1200)
        if "/login" in otra.url:
            fallos.append(
                "la comprobacion del modo PWA no tiene sesion: la pagina "
                f"redirigió a {otra.url}"
            )
        elif "/mis-tickets" in otra.url:
            fallos.append(
                "el modo PWA se ha quedado pegado en el navegador: en otra "
                f"pestana la ruta de admin redirige a {otra.url}"
            )
        else:
            print("  modo PWA: el flag no se queda pegado en el navegador")
    except Exception as exc:  # noqa: BLE001
        fallos.append(f"no se pudo comprobar el modo PWA: {type(exc).__name__}: {exc}")
    finally:
        otra.close()

    return fallos


def _evaluar(
    resultados: "list[Resultado]",
    errores_login: "list[str]",
    fallos_extra: "list[str] | None" = None,
) -> tuple[int, list[str]]:
    """El veredicto de la QA: ``(código de salida, motivos)``.

    Está **separado** para poder probarlo con casos de mentira (ver
    ``_autoprueba``): una puerta que no se puede ver fallar no es una
    puerta.

    OJO (2026-10-22): antes la QA **imprimía** los errores de red y de
    consola pero NO fallaba con ellos. Una pantalla cuyo fetch devolviera
    un 500 (o con un error de JavaScript) dejaba la puerta en verde: la
    puerta recogía la evidencia y no actuaba sobre ella.
    """
    motivos: list[str] = []
    desbordes = sum(len(r.desbordes) for r in resultados)
    red = sum(len(r.red) for r in resultados)
    # Solo los **errores** de consola rompen la puerta. Los *warnings* se
    # informan (que el ojo los vea) pero no la rompen: una puerta que
    # falla por ruido acaba apagada, y eso es peor que un aviso.
    consola = sum(
        1 for r in resultados for c in r.consola if c.startswith("error:")
    )
    if desbordes:
        motivos.append(f"{desbordes} contenido(s) recortado(s) sin desplazar")
    if red:
        motivos.append(f"{red} peticion(es) fallida(s) (4xx/5xx o sin respuesta)")
    if consola:
        motivos.append(f"{consola} error(es) de consola")
    if errores_login:
        motivos.append(f"{len(errores_login)} inicio(s) de sesión fallido(s)")
    for motivo in fallos_extra or []:
        motivos.append(motivo)
    return (1 if motivos else 0), motivos


def _autoprueba() -> int:
    """Comprueba que el detector de desbordes SIGUE detecting.

    Una puerta que no se puede ver fallar no es una puerta. Este
    detector es el que destapo los 26 desbordes del movil: si dejara de
    verlos, la QA pasara todas las pantallas y nadie se enterara.

    OJO: esta autoprueba necesita un navegador de verdad (el JS mide
    anchos de elementos, y eso sólo lo sabe un motor de layout). Si
    playwright no está instalado, **no se puede comprobar**: se devuelve
    el código 3 ("no verificado") en vez de un verde que no significa
    nada. La meta-puerta lo distingue del "pasa".
    """
    if not HAY_PLAYWRIGHT:
        print("NO VERIFICADO: falta playwright (y su Chromium).")
        print("  Se puede comprobar con:")
        print("    pip install playwright && python -m playwright install chromium")
        return SIN_NAVEGADOR

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

    # El veredicto: una peticion fallida o un error de consola tienen que
    # PONER la puerta en rojo (antes sólo se imprimian).
    codigo, motivos = _evaluar([], [])
    if codigo != 0:
        print(f"  FALLO: sin problemas el veredicto deberia ser 0 ({motivos})")
        fallos += 1
    else:
        print("  OK: sin problemas el veredicto es 0")

    caso_red = Resultado(
        etiqueta="x", ruta="/x", url_final="/x", red=["500 GET /api/v1/x"]
    )
    codigo, motivos = _evaluar([caso_red], [])
    if codigo != 1:
        print("  FALLO: una peticion fallida no pone la puerta en rojo")
        fallos += 1
    else:
        print("  OK: una peticion fallida pone la puerta en rojo")

    caso_consola = Resultado(
        etiqueta="x", ruta="/x", url_final="/x", consola=["error: TypeError"]
    )
    codigo, motivos = _evaluar([caso_consola], [])
    if codigo != 1:
        print("  FALLO: un error de consola no pone la puerta en rojo")
        fallos += 1
    else:
        print("  OK: un error de consola pone la puerta en rojo")

    codigo, motivos = _evaluar([], ["admin: no se pudo iniciar sesion"])
    if codigo != 1:
        print("  FALLO: un fallo de login no pone la puerta en rojo")
        fallos += 1
    else:
        print("  OK: un fallo de login pone la puerta en rojo")

    # Un AVISO de consola (no un error) informa pero no rompe la puerta:
    # una puerta que falla por ruido acaba apagada.
    caso_aviso = Resultado(
        etiqueta="x", ruta="/x", url_final="/x", consola=["warning: Vuedeprecated"]
    )
    codigo, motivos = _evaluar([caso_aviso], [])
    if codigo != 0:
        print("  FALLO: un aviso de consola no deberia romper la puerta")
        fallos += 1
    else:
        print("  OK: un aviso de consola no rompe la puerta")

    # Y una peticion SIN RESPUESTA (conexion rechazada) si rompe: no emite
    # "response", emite "requestfailed".
    caso_sin_respuesta = Resultado(
        etiqueta="x", ruta="/x", url_final="/x",
        red=["SIN RESPUESTA GET /api/v1/x (net::ERR_CONNECTION_REFUSED)"],
    )
    codigo, motivos = _evaluar([caso_sin_respuesta], [])
    if codigo != 1:
        print("  FALLO: una peticion sin respuesta no pone la puerta en rojo")
        fallos += 1
    else:
        print("  OK: una peticion sin respuesta pone la puerta en rojo")

    # Y una peticion CANCELADA (ERR_ABORTED) NO rompe la puerta: es el
    # navegador cancelando lo que la app ya no espera (cambio de
    # pantalla, cierre del SSE).
    canceladas_antes = len(CANCELADAS)

    class _ReqFalso:
        method = "GET"
        url = "/api/v1/parkings/11/events"
        failure = "net::ERR_ABORTED"

    lista: list[str] = []
    _sin_respuesta(lista, _ReqFalso())
    if lista:
        print("  FALLO: una peticion cancelada se ha contado como fallo")
        fallos += 1
    else:
        print("  OK: una peticion cancelada (ERR_ABORTED) no es un fallo")
    if len(CANCELADAS) != canceladas_antes + 1:
        print("  FALLO: la peticion cancelada no se ha registrado aparte")
        fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el detector de desbordes sigue viendo.")
    return 0


def _visitar(pagina: Page, ruta: str, base: str) -> str | None:
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
        pagina.goto(f"{base}{ruta}", wait_until="networkidle", timeout=15000)
    except PlaywrightTimeout:
        return "la red no se quedo quieta (video en directo o teselas del mapa)"
    except Exception as exc:  # noqa: BLE001 — la QA no debe abortar
        return f"navegacion: {type(exc).__name__}: {exc}"
    return None


def _login(page: Page, email: str, password: str, base: str) -> tuple[bool, str]:
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
        page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
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
    base: str = BASE_POR_DEFECTO,
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
        aviso = _visitar(pagina, ruta, base)
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
    ap.add_argument(
        "--base",
        default=BASE_POR_DEFECTO,
        help=(
            "Servidor contra el que se corre la QA. Por defecto, el de "
            "desarrollo (Vite con HMR). Para probar el bundle de produccion: "
            "--base http://127.0.0.1:8091 (con la imagen de nginx levantada)."
        ),
    )
    args = ap.parse_args()
    if args.autoprueba:
        return _autoprueba()
    if not HAY_PLAYWRIGHT:
        print("FALTA playwright: la QA visual necesita el navegador.")
        print("  pip install playwright && python -m playwright install chromium")
        return SIN_NAVEGADOR

    if args.anchos:
        anchos = [int(a.strip()) for a in args.anchos.split(",") if a.strip()]
    else:
        anchos = [args.ancho]
    if not anchos:
        print("No hay ningún ancho que comprobar.")
        return 2

    base = args.base.rstrip("/")
    if base != BASE_POR_DEFECTO:
        print(f"QA contra {base} (no es el servidor de desarrollo)")

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    altura = 900

    resultados: list[Resultado] = []
    errores_login: list[str] = []
    # T-66: fallos de la comprobacion del modo PWA (que no debe quedar
    # pegado en el navegador).
    fallos_modo_pwa: list[str] = []
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
        pagina_publica.on(
            "requestfailed",
            lambda req: _sin_respuesta(red_publica, req),
        )
        for ancho in anchos:
            pagina_publica.set_viewport_size({"width": ancho, "height": altura})
            destino = salida / str(ancho) if len(anchos) > 1 else salida
            destino.mkdir(parents=True, exist_ok=True)
            _recorrer(
                pagina_publica, destino, ancho, "ninguno",
                consola_publica, red_publica, resultados, avisos, base,
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
            # registraban en cada pantalla y se acumulaban (26 pantallas x
            # 5 anchos = 130 manejadores disparando a la vez).
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
            # Una peticion que NO recibe respuesta (conexion rechazada, DNS,
            # abortada) no emite "response": emite "requestfailed". Sin
            # esta escucha, ese fallo era invisible para la puerta.
            pagina.on(
                "requestfailed",
                lambda req: _sin_respuesta(red, req),
            )
            email, password = CUENTAS[rol]
            ok, motivo = _login(pagina, email, password, base)
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
                    base,
                )
            if rol == "admin":
                # T-66: el modo PWA no puede quedar pegado en el navegador.
                fallos_modo_pwa += _comprobar_modo_pwa(contexto, pagina, base)
            contexto.close()
        navegador.close()

    informe = {
        "base": base,
        "anchos": anchos,
        "inicios_de_sesion": inicios_de_sesion,
        "canceladas": list(CANCELADAS),
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
    total_red = sum(len(r.red) for r in resultados)
    total_consola = sum(len(r.consola) for r in resultados)
    if total_desbordes:
        print(f"\nATENCION: {total_desbordes} contenido(s) recortado(s) sin desplazar")
    if total_red:
        print(f"\nATENCION: {total_red} peticion(es) fallida(s) (4xx/5xx)")
    if total_consola:
        print(f"\nATENCION: {total_consola} error(es) de consola")
    print(f"\nCapturas e informe en {salida}")
    print(
        f"{len(resultados)} capturas · {len(anchos)} ancho(s) · "
        f"{inicios_de_sesion} inicio(s) de sesión · "
        f"{total_red} peticion(es) fallida(s) · {total_consola} error(es) de consola · "
        f"{len(CANCELADAS)} peticion(es) cancelada(s) (no son fallos)"
    )
    # OJO (2026-10-22): antes la QA **imprimia** los errores de red y de
    # consola pero NO fallaba con ellos: una pantalla cuyo fetch devolviera
    # un 500 (o con un error de JavaScript) dejaba la puerta en verde. La
    # puerta recogía la evidencia y no actuaba sobre ella, que es
    # justamente lo que hace que una puerta deje de ser una puerta.
    codigo, motivos = _evaluar(resultados, errores_login, fallos_modo_pwa)
    for motivo in motivos:
        print(f"  FALLO: {motivo}")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
