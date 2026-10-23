"""Comprueba que el service worker NO cachea la API.

POR QUÉ esta puerta
-------------------
La PWA cachea el *shell* (HTML, JS, CSS, iconos) para arrancar sin red.
La API **no** se cachea nunca, y eso está escrito en
``frontend/public/sw.js`` (la exclusión de ``/api/`` está antes de
cualquier ``event.respondWith``).

El problema: **nadie lo vigilaba**. Ni una puerta, ni la QA de la PWA
(que contaba las entradas de la caché pero no miraba *cuáles* eran).
Es decir: si alguien añadía una regla de cacheo para ``/api/``, el repo
se quedaría en verde mientras la caché del navegador guardase tickets,
matrículas y fotos de incidentes... y se los serviría a otro usuario del
mismo dispositivo (dato personal, LOPDGDD).

Esta puerta mira el **código** (rápida, va en el CI) y la QA de la PWA
mira el **comportamiento** (navegador de verdad, en el stack de QA). Las
dos juntas: si una de las dos dejara de ver, la otra lo pilla.

QUÉ COMPRUEBA
-------------
- **S1**: la exclusión de ``/api/`` está en el handler ``fetch`` **antes**
  del primer ``event.respondWith`` (si no, la API se cachearía).
- **S2**: el prefijo de la API es el **mismo** en los tres sitios que lo
  nombran: el cliente HTTP (``client.ts``), el service worker
  (``sw.js``) y nginx. Si divergen, la exclusión se rompe **en silencio**.
- **S3**: el service worker no precachea nada bajo ``/api/`` (la lista
  del shell).

Uso
---
    python tools/verificar_cache_service_worker.py
    python tools/verificar_cache_service_worker.py --autoprueba
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
SW_POR_DEFECTO = RAIZ / "frontend" / "public" / "sw.js"
CLIENT_POR_DEFECTO = RAIZ / "frontend" / "src" / "api" / "client.ts"
NGINX_POR_DEFECTO = RAIZ / "frontend" / "nginx" / "templates" / "default.conf.template"

#: Prefijo con el que la API se sirve. Los tres ficheros tienen que
#: nombrarlo igual: si no, la exclusión del service worker deja de
#: aplicarse sin que nadie se entere.
PREFIJO_API = "/api/"


def _prefijo_del_cliente(texto: str) -> str | None:
    """El ``baseURL`` del cliente HTTP (``/api/v1``)."""
    encontrado = re.search(r"""baseURL\s*=\s*['"]([^'"]+)['"]""", texto)
    return encontrado.group(1) if encontrado else None


def _prefijos_del_sw(texto: str) -> list[str]:
    """Todos los prefijos que el service worker excluye de la caché.

    OJO: hay más de uno (``esEstatico`` mira ``/assets/``). El de la API
    es el que tiene que estar; por eso se mira la lista entera y no el
    primer ``startsWith`` del fichero.
    """
    return re.findall(
        r"""pathname\.startsWith\(\s*['"]([^'"]+)['"]\s*\)""", texto
    )


def _prefijo_de_nginx(texto: str) -> str | None:
    """El ``location ^~ /api/`` de nginx."""
    encontrado = re.search(r"""location\s+\^~\s+(\S+?)\s*\{""", texto)
    return encontrado.group(1) if encontrado else None


def _indice_de_la_exclusion(texto: str) -> int | None:
    """Donde está la exclusión de la API dentro del ``sw.js``."""
    for numero, linea in enumerate(texto.splitlines()):
        if "startsWith" in linea and PREFIJO_API in linea:
            return numero
    return None


def _indice_del_primer_respond_with(texto: str) -> int | None:
    """Donde empieza el service worker a responder por su cuenta."""
    for numero, linea in enumerate(texto.splitlines()):
        if "event.respondWith" in linea:
            return numero
    return None


def _precachea_la_api(texto: str) -> list[str]:
    """Rutas de la lista del shell (``SHELL``) que caen bajo ``/api/``.

    Sólo se mira el array ``SHELL``: buscar en todo el fichero cogía
    también la propia exclusión de la API (que es una cadena entre
    comillas) y las rutas de los assets.
    """
    bloque = re.search(r"""const\s+SHELL\s*=\s*\[(.*?)\];""", texto, re.S)
    if not bloque:
        return []
    return [
        coincidencia
        for coincidencia in re.findall(r"""['"](/[^'"]*)['"]""", bloque.group(1))
        if coincidencia.startswith(PREFIJO_API)
    ]


def verificar(sw: Path, cliente: Path, nginx: Path) -> list[str]:
    """Los problemas que encuentra en los tres ficheros."""
    problemas: list[str] = []
    texto_sw = sw.read_text(encoding="utf-8")
    texto_cliente = cliente.read_text(encoding="utf-8")
    texto_nginx = nginx.read_text(encoding="utf-8")

    # S1: la exclusión va antes de responder por la cuenta.
    exclusion = _indice_de_la_exclusion(texto_sw)
    respond = _indice_del_primer_respond_with(texto_sw)
    if exclusion is None:
        problemas.append(
            f"{sw.name}: no hay ninguna exclusión de `{PREFIJO_API}` en el "
            f"service worker: la API se cachearía (dato personal)"
        )
    elif respond is not None and exclusion > respond:
        problemas.append(
            f"{sw.name}: la exclusión de `{PREFIJO_API}` (línea {exclusion + 1}) "
            f"está DESPUÉS del primer `event.respondWith` (línea {respond + 1}): "
            f"la API se cachearía"
        )
    if respond is None:
        problemas.append(
            f"{sw.name}: no hay ningún `event.respondWith`: el service worker "
            f"no cachea nada, pero tampoco se puede comprobar la política"
        )

    # S2: los tres prefijos tienen que coincidir.
    prefijo_cliente = _prefijo_del_cliente(texto_cliente)
    prefijo_nginx = _prefijo_de_nginx(texto_nginx)
    prefijos_sw = _prefijos_del_sw(texto_sw)

    if prefijo_cliente is None:
        problemas.append("el cliente HTTP (client.ts): no se encuentra el baseURL")
    if prefijo_nginx is None:
        problemas.append("nginx (default.conf.template): no se encuentra el location de la API")
    if not prefijos_sw:
        problemas.append(
            "el service worker (sw.js): no excluye ningún prefijo de la caché"
        )
    if prefijo_nginx and prefijo_nginx not in prefijos_sw:
        problemas.append(
            f"el service worker (sw.js) no excluye `{prefijo_nginx}` (que es lo "
            f"que sirve nginx): la API se cachearía. Exclusiones del SW: {prefijos_sw}"
        )
    if prefijo_cliente and prefijo_nginx and not prefijo_cliente.startswith(prefijo_nginx):
        problemas.append(
            f"el cliente HTTP usa `{prefijo_cliente}` y nginx sirve `{prefijo_nginx}`: "
            f"el prefijo del service worker dejaría de aplicarse en silencio"
        )

    # S3: la lista del shell no puede traer la API.
    for ruta in _precachea_la_api(texto_sw):
        problemas.append(
            f"{sw.name}: la lista de precache incluye `{ruta}` (la API no se "
            f"precachea nunca)"
        )

    return problemas


# ── autoprueba: casos de mentira escritos a mano ────────────────────────

SW_BUENO = """
const SHELL = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) {
    return;
  }
  if (url.origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req));
    return;
  }
});
"""

SW_MENTIRA = """
const SHELL = ['/', '/index.html'];

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req));
    return;
  }
  // La exclusion de la API ha quedado DESPUES: todo se cachea.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(caches.match(req));
    return;
  }
});
"""

SW_PRECACHEA_LA_API = """
const SHELL = ['/', '/index.html', '/api/v1/users/me'];

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request));
});
"""

CLIENT_BUENO = """
const baseURL = '/api/v1';
export default { baseURL };
"""

CLIENT_MENTIRA = """
const baseURL = '/v1';
export default { baseURL };
"""

NGINX_BUENO = """
location ^~ /api/ {
  proxy_pass http://backend:8000;
}
"""


def _montar(raiz: Path, sw: str, cliente: str, nginx: str) -> tuple[Path, Path, Path]:
    (raiz / "frontend" / "public").mkdir(parents=True, exist_ok=True)
    (raiz / "frontend" / "src" / "api").mkdir(parents=True, exist_ok=True)
    (raiz / "frontend" / "nginx" / "templates").mkdir(parents=True, exist_ok=True)
    sw_path = raiz / "frontend" / "public" / "sw.js"
    cliente_path = raiz / "frontend" / "src" / "api" / "client.ts"
    nginx_path = raiz / "frontend" / "nginx" / "templates" / "default.conf.template"
    sw_path.write_text(sw, encoding="utf-8")
    cliente_path.write_text(cliente, encoding="utf-8")
    nginx_path.write_text(nginx, encoding="utf-8")
    return sw_path, cliente_path, nginx_path


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira y callar con el bueno."""
    fallos = 0
    with tempfile.TemporaryDirectory(prefix="cache_sw_") as temporal:
        raiz = Path(temporal)

        casos = [
            (
                "el service worker cachea la API (exclusion despues)",
                SW_MENTIRA,
                CLIENT_BUENO,
                NGINX_BUENO,
            ),
            (
                "la lista de precache trae la API",
                SW_PRECACHEA_LA_API,
                CLIENT_BUENO,
                NGINX_BUENO,
            ),
            (
                "el cliente HTTP y el service worker usan prefijos distintos",
                SW_BUENO,
                CLIENT_MENTIRA,
                NGINX_BUENO,
            ),
        ]
        for nombre, sw, cliente, nginx in casos:
            sw_p, cli_p, ng_p = _montar(raiz, sw, cliente, nginx)
            problemas = verificar(sw_p, cli_p, ng_p)
            if problemas:
                print(f"  OK: {nombre} -> {problemas[0][:110]}")
            else:
                print(f"  FALLO: {nombre} no lo detecta")
                fallos += 1

        # Y el caso bueno no tiene que dar problemas.
        sw_p, cli_p, ng_p = _montar(raiz, SW_BUENO, CLIENT_BUENO, NGINX_BUENO)
        problemas = verificar(sw_p, cli_p, ng_p)
        if not problemas:
            print("  OK: el caso correcto no da problemas (la puerta no grita de más)")
        else:
            print(f"  FALLO: el caso correcto dio {problemas}")
            fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta vigila la caché del service worker.")
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

    problemas = verificar(SW_POR_DEFECTO, CLIENT_POR_DEFECTO, NGINX_POR_DEFECTO)
    if problemas:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nOK: el service worker no cachea la API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
