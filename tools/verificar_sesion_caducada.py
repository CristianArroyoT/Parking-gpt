"""Comprueba que la sesion caducada **expulsa** al login.

POR QUE esta puerta
-------------------
El backend avisa de que la sesion esta muerta con el evento
``solidapp:sesion-caducada`` (T-110) y el store limpia el usuario. Pero el
**guard del router solo corre al navegar**: sin una redireccion, el operador
se queda en la pantalla con los tickets y las plazas ya descargados, y cada
peticion posterior devuelve 401 sin mensaje.

CASO REAL (T-140, 2026-10-24)
-----------------------------
El T-137 dio por **refutado** este defecto ("la app SI expulsa al login"), y
se revirtio el cambio del router. La verdad es que el arreglo vivia en el
arbol de trabajo, sin commitear: la QA paso CON el arreglo puesto y, al
revertirlo para hacer el commit, **nadie vuelvo a ejecutar la puerta**. La
puerta se quedo en rojo sin que nadie lo notara, y el defecto seguia ahi.

Medido despues, con un navegador de verdad:

    - el evento SI se dispara y los tokens SI se limpian;
    - pero la URL se quedaba en /mapa y el mapa seguia mostrando las plazas.

QUE COMPRUEBA
-------------
- **S1**: en algun fichero del frontend hay un listener de
  ``solidapp:sesion-caducada`` cuyo cuerpo **navega al login** (sin esto, el
  usuario se queda en la pantalla muerta).
- **S2**: el cliente HTTP emite el evento cuando el refresh falla, y **limpia
  los tokens antes** (si no, queda un token vivo sin perfil).
- **S3**: al recibir el evento, el usuario se limpia (sin esto, el guard
  deja pasar al operador aunque la sesion este muerta).

OJO (2026-10-24): la busqueda se hace sobre el codigo **sin comentarios**.
Buscar un patron en el texto cuenta tambien la prosa de los comentarios, y un
comentario que menciona ``router.replace({ name: 'login' })`` haria que un
router que NO expulsa pareciera cumplir (leccion del repo: en solidAPP una
puerta dio el visto bueno a un endpoint que no acotaba porque su docstring
mencionaba el helper correcto).

Uso
---
    python tools/verificar_sesion_caducada.py
    python tools/verificar_sesion_caducada.py --autoprueba
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "frontend" / "src"
CLIENTE = SRC / "api" / "client.ts"

EVENTO = "solidapp:sesion-caducada"

#: Un listener del evento: ``addEventListener('solidapp:sesion-caducada', ...)``.
RE_LISTENER = re.compile(
    r"""addEventListener\(\s*['"]""" + re.escape(EVENTO) + r"""['"]"""
)

#: La redireccion al login dentro del cuerpo del listener.
RE_NAVEGA_LOGIN = re.compile(
    r"""(?:replace|push)\s*\(\s*\{[^}]*?name\s*:\s*['"]login['"]""",
    re.S,
)
RE_NAVEGA_LOGIN_RUTA = re.compile(
    r"""(?:replace|push)\s*\(\s*['"]\/login['"]"""
)
RE_LIMPIA_USUARIO = re.compile(r"""user\.value\s*=\s*null""")
RE_LIMPIA_TOKENS = re.compile(r"""clearTokens\s*\(""")


def _sin_comentarios(texto: str) -> str:
    """Quita los comentarios de TypeScript/Vue sin tocar el resto.

    Implementa un mini-lexer con estados (codigo, linea, bloque, cadena,
    plantilla). Conserva los saltos de linea para que el informe siga siendo
    legible.
    """
    salida: list[str] = []
    i = 0
    n = len(texto)
    estado = "codigo"
    while i < n:
        c = texto[i]
        nxt = texto[i + 1] if i + 1 < n else ""
        if estado == "codigo":
            if c == "/" and nxt == "/":
                estado = "linea"
                salida.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                estado = "bloque"
                salida.append("  ")
                i += 2
                continue
            if c == "'":
                estado = "cadena1"
            elif c == '"':
                estado = "cadena2"
            elif c == "`":
                estado = "plantilla"
            salida.append(c)
            i += 1
            continue
        if estado == "linea":
            if c == "\n":
                estado = "codigo"
                salida.append(c)
            else:
                salida.append(" ")
            i += 1
            continue
        if estado == "bloque":
            if c == "*" and nxt == "/":
                estado = "codigo"
                salida.append("  ")
                i += 2
                continue
            salida.append("\n" if c == "\n" else " ")
            i += 1
            continue
        # Estados de cadena: se copia tal cual (incluye el escape).
        salida.append(c)
        if c == "\\" and i + 1 < n:
            salida.append(texto[i + 1])
            i += 2
            continue
        if (
            (estado == "cadena1" and c == "'")
            or (estado == "cadena2" and c == '"')
            or (estado == "plantilla" and c == "`")
        ):
            estado = "codigo"
        i += 1
    return "".join(salida)


def _bloque_del_listener(texto: str, inicio: int) -> str:
    """El cuerpo del listener que empieza en ``inicio`` (hasta su llave de cierre)."""
    nivel = 0
    i = inicio
    while i < len(texto):
        if texto[i] == "{":
            nivel += 1
        elif texto[i] == "}":
            nivel -= 1
            if nivel == 0:
                return texto[inicio : i + 1]
        i += 1
    return texto[inicio:]


def _listeners(texto: str) -> list[str]:
    """Los cuerpos de los listeners del evento, en el codigo sin comentarios."""
    limpio = _sin_comentarios(texto)
    return [
        _bloque_del_listener(limpio, m.start()) for m in RE_LISTENER.finditer(limpio)
    ]


def _ficheros_frontend(raiz: Path) -> list[Path]:
    """Todos los ``.ts`` y ``.vue`` del codigo del frontend."""
    return sorted(
        p
        for p in (raiz / "frontend" / "src").rglob("*")
        if p.suffix in (".ts", ".vue") and p.is_file()
    )


def verificar(raiz: Path) -> list[str]:
    """Los problemas que encuentra en el codigo del frontend."""
    problemas: list[str] = []
    ficheros = _ficheros_frontend(raiz)
    if not ficheros:
        return [f"no se encuentra el codigo del frontend en {raiz / 'frontend' / 'src'}"]

    # S1: algun listener navega al login.
    quien_navega: list[str] = []
    for fichero in ficheros:
        for bloque in _listeners(fichero.read_text(encoding="utf-8")):
            if RE_NAVEGA_LOGIN.search(bloque) or RE_NAVEGA_LOGIN_RUTA.search(bloque):
                quien_navega.append(fichero.name)
                break
    if not quien_navega:
        problemas.append(
            "ningun listener de 'solidapp:sesion-caducada' expulsa al login: "
            "el operador se queda en la pantalla muerta (el guard del router "
            "solo corre al navegar)"
        )

    # S3: el usuario se limpia al recibir el evento.
    quien_limpia: list[str] = []
    for fichero in ficheros:
        for bloque in _listeners(fichero.read_text(encoding="utf-8")):
            if RE_LIMPIA_USUARIO.search(bloque):
                quien_limpia.append(fichero.name)
                break
    if not quien_limpia:
        problemas.append(
            "el evento 'solidapp:sesion-caducada' no limpia el usuario en "
            "ningun sitio: el guard del router dejaria pasar al operador con "
            "la sesion muerta"
        )

    # S2: el cliente emite el evento, y limpia los tokens antes.
    cliente = raiz / "frontend" / "src" / "api" / "client.ts"
    if not cliente.exists():
        problemas.append("no se encuentra el cliente HTTP (frontend/src/api/client.ts)")
        return problemas
    texto = _sin_comentarios(cliente.read_text(encoding="utf-8"))
    if EVENTO not in texto or "dispatchEvent" not in texto:
        problemas.append(
            "el cliente HTTP no emite el evento 'solidapp:sesion-caducada': "
            "nadie se enteraria de que la sesion esta muerta"
        )
    else:
        limpiar = texto.find("clearTokens")
        emitir = texto.find("dispatchEvent")
        if limpiar < 0 or emitir < 0 or limpiar > emitir:
            problemas.append(
                "el cliente HTTP no limpia los tokens ANTES de emitir el evento: "
                "quedaria un token vivo sin perfil"
            )

    return problemas


# ── autoprueba: casos de mentira escritos a mano ────────────────────────

ROUTER_BUENO = """
import { router } from './router'
window.addEventListener('solidapp:sesion-caducada', () => {
  const actual = router.currentRoute.value
  if (actual.name === 'login') return
  void router.replace({ name: 'login', query: { redirect: actual.fullPath } })
})
"""

# El defecto REAL: el listener limpia el estado pero NO expulsa al login.
ROUTER_SIN_EXPULSAR = """
window.addEventListener('solidapp:sesion-caducada', () => {
  auth.user = null
})
"""

# El defecto del docstring: el codigo no expulsa, pero el comentario dice que si.
ROUTER_SOLO_EN_EL_COMENTARIO = """
// OJO: con el evento, el router hace router.replace({ name: 'login' })
window.addEventListener('solidapp:sesion-caducada', () => {
  auth.user = null
})
"""

ROUTER_QUE_NO_LIMPIA_EL_USUARIO = """
window.addEventListener('solidapp:sesion-caducada', () => {
  void router.replace({ name: 'login' })
})
"""

STORE_BUENO = """
window.addEventListener('solidapp:sesion-caducada', () => {
  user.value = null
  email.value = null
})
"""

#: El store que NO limpia el usuario (el router lo hace, pero el usuario
#: se queda cargado y el guard lo deja pasar).
STORE_SIN_LIMPIAR = """
window.addEventListener('solidapp:sesion-caducada', () => {
  email.value = null
})
"""

CLIENTE_BUENO = """
async function doRefresh() {
  try {
    return await renovar()
  } catch {
    clearTokens()
    window.dispatchEvent(new CustomEvent('solidapp:sesion-caducada'))
    return null
  }
}
"""

CLIENTE_SIN_LIMPIAR_TOKENS = """
async function doRefresh() {
  try {
    return await renovar()
  } catch {
    window.dispatchEvent(new CustomEvent('solidapp:sesion-caducada'))
    return null
  }
}
"""

CLIENTE_SIN_EVENTO = """
async function doRefresh() {
  try {
    return await renovar()
  } catch {
    clearTokens()
    return null
  }
}
"""


def _montar(raiz: Path, router: str, store: str, cliente: str) -> None:
    (raiz / "frontend" / "src" / "router").mkdir(parents=True, exist_ok=True)
    (raiz / "frontend" / "src" / "stores").mkdir(parents=True, exist_ok=True)
    (raiz / "frontend" / "src" / "api").mkdir(parents=True, exist_ok=True)
    (raiz / "frontend" / "src" / "router" / "index.ts").write_text(router, encoding="utf-8")
    (raiz / "frontend" / "src" / "stores" / "auth.ts").write_text(store, encoding="utf-8")
    (raiz / "frontend" / "src" / "api" / "client.ts").write_text(cliente, encoding="utf-8")


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira y callar con el bueno."""
    fallos = 0
    with tempfile.TemporaryDirectory(prefix="sesion_caducada_") as temporal:
        raiz = Path(temporal)

        casos = [
            (
                "el listener no expulsa al login",
                ROUTER_SIN_EXPULSAR,
                STORE_BUENO,
                CLIENTE_BUENO,
                "expulsa al login",
            ),
            (
                "el listener solo lo menciona en un comentario",
                ROUTER_SOLO_EN_EL_COMENTARIO,
                STORE_BUENO,
                CLIENTE_BUENO,
                "expulsa al login",
            ),
            (
                "el listener no limpia el usuario",
                ROUTER_QUE_NO_LIMPIA_EL_USUARIO,
                STORE_SIN_LIMPIAR,
                CLIENTE_BUENO,
                "no limpia el usuario",
            ),
            (
                "el cliente no emite el evento",
                ROUTER_BUENO,
                STORE_BUENO,
                CLIENTE_SIN_EVENTO,
                "no emite el evento",
            ),
            (
                "el cliente no limpia los tokens antes de emitir",
                ROUTER_BUENO,
                STORE_BUENO,
                CLIENTE_SIN_LIMPIAR_TOKENS,
                "no limpia los tokens",
            ),
        ]
        for nombre, router, store, cliente, esperado in casos:
            _montar(raiz, router, store, cliente)
            problemas = verificar(raiz)
            if any(esperado in p for p in problemas):
                print(f"  OK: {nombre} -> {[p for p in problemas if esperado in p][0][:100]}")
            else:
                print(f"  FALLO: {nombre} no lo detecta (problemas: {problemas})")
                fallos += 1

        # Y el caso correcto no tiene que dar problemas.
        _montar(raiz, ROUTER_BUENO, STORE_BUENO, CLIENTE_BUENO)
        problemas = verificar(raiz)
        if not problemas:
            print("  OK: el caso correcto no da problemas (la puerta no grita de mas)")
        else:
            print(f"  FALLO: el caso correcto dio {problemas}")
            fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta vigila la expulsion al login.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="comprueba que la puerta detecta los casos de mentira",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return _autoprueba()

    problemas = verificar(RAIZ)
    if problemas:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nOK: la sesion caducada expulsa al login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
