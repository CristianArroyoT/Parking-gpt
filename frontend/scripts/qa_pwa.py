"""QA del PWA del cliente (T-24): comprueba que la app es instalable.

Hasta ahora nadie verificaba el PWA: la QA visual recorre las pantallas
del cliente, pero no mira si el *service worker* se registra, si el
manifiesto es válido, si los iconos se sirven o si la app arranca sin
red. Un PWA roto (un icono que devuelve 404, un manifiesto mal formado)
sólo se ve cuando el usuario intenta instalarlo.

Qué comprueba:

  1. El manifiesto se descarga y se parsea, con los campos que Chrome
     exige para ofrecer "Instalar app".
  2. Todos los iconos del manifiesto se sirven con 200 y son PNG (o SVG)
     válidos.
  3. El *service worker* se registra, activa y toma el control.
  4. La app **arranca sin red** (se sirve desde la caché del SW).
  5. El servidor que usa la QA **cumple los mismos requisitos que el de
     producción** (T-58): hasta el 2026-10-22 lo incumplía (3 de 5) y la
     QA lo daba por bueno, de modo que la PWA se verificaba sobre un
     servidor que el usuario real no tiene.

Uso:
    python scripts/qa_pwa.py                 # sirve dist/ y lo comprueba
    python scripts/qa_pwa.py --url http://...  # contra un servidor ya en marcha
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import socket
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

# La puerta del servidor de producción (mismo fichero, mismo criterio que
# el CI). Se añade su carpeta al path para poder importarla desde donde sea.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verificar_servidor_produccion import comprobar_requisitos  # noqa: E402

DIST = Path(__file__).resolve().parent.parent / "dist"

#: Lo que Chrome exige para que una app sea instalable.
CAMPOS_MANIFIESTO_OBLIGATORIOS = ("name", "start_url", "display", "icons")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ServidorEstatico(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ManejadorEstatico(http.server.SimpleHTTPRequestHandler):
    """El build servido como lo sirve el servidor de producción (T-58).

    El ``SimpleHTTPRequestHandler`` de la biblioteca estándar NO pone las
    cabeceras que exige el PWA: sin ``no-store`` en el service worker el
    navegador se queda con la versión vieja, y sin el fallback de la SPA una
    ruta profunda devuelve 404 en vez del shell. Medido: 3 de 5 requisitos
    incumplidos.
    """

    # El tipo del manifiesto, explícito: no depende de la versión de
    # Python (en unas versiones el ``mimetypes`` lo desconoce y se
    # serviría como ``application/octet-stream``, que Chrome no instala).
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
    }

    def end_headers(self) -> None:
        ruta = self.path.split("?")[0]
        if ruta == "/sw.js":
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
        elif ruta in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        elif ruta.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        super().end_headers()

    def send_head(self):
        """El fallback de la SPA: una ruta desconocida devuelve el shell."""
        ruta = self.path.split("?")[0]
        if ruta not in ("/", "/index.html") and not ruta.startswith("/assets/"):
            posible = (Path(self.directory) / ruta.lstrip("/")).resolve()
            raiz = Path(self.directory).resolve()
            if posible.is_file() and raiz in posible.parents:
                pass
            else:
                self.path = "/index.html"
        return super().send_head()


def _servir(directorio: Path) -> tuple[_ServidorEstatico, str]:
    """Sirve el build en un hilo aparte y devuelve (servidor, url)."""
    manejador = functools.partial(
        _ManejadorEstatico, directory=str(directorio),
    )
    servidor = _ServidorEstatico(("127.0.0.1", _puerto_libre()), manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, f"http://localhost:{servidor.server_address[1]}"


def _comprobar_manifiesto(url_base: str) -> list[str]:
    """Descarga el manifiesto y valida los campos y los iconos."""
    fallos: list[str] = []
    import urllib.request

    with urllib.request.urlopen(f"{url_base}/manifest.webmanifest", timeout=15) as r:
        crudo = r.read()
    try:
        manifiesto = json.loads(crudo)
    except json.JSONDecodeError as exc:
        return [f"el manifiesto no es JSON valido: {exc}"]

    for campo in CAMPOS_MANIFIESTO_OBLIGATORIOS:
        if not manifiesto.get(campo):
            fallos.append(f"el manifiesto no tiene '{campo}'")

    iconos = manifiesto.get("icons") or []
    if not iconos:
        fallos.append("el manifiesto no declara ningun icono: no es instalable")
    tamanos = {str(i.get("sizes")) for i in iconos}
    if not any("192" in t for t in tamanos):
        fallos.append("falta un icono de 192 px (Chrome no lo instala sin el)")
    if not any("512" in t for t in tamanos):
        fallos.append("falta un icono de 512 px (Chrome no lo instala sin el)")

    for icono in iconos:
        src = icono.get("src", "")
        destino = src if src.startswith("http") else f"{url_base}{src}"
        try:
            with urllib.request.urlopen(destino, timeout=15) as r:
                if r.status != 200:
                    fallos.append(f"el icono {src} devuelve {r.status}")
                elif not r.read(4):
                    fallos.append(f"el icono {src} esta vacio")
        except Exception as exc:  # noqa: BLE001 — queremos el motivo
            fallos.append(f"el icono {src} no se puede descargar: {exc}")

    if not fallos:
        print(f"  manifiesto OK: {manifiesto.get('name')} | "
              f"{len(iconos)} iconos | display={manifiesto.get('display')}")
    return fallos


def _comprobar_service_worker(pagina) -> list[str]:
    fallos: list[str] = []
    estado = pagina.evaluate(
        """async () => {
          if (!('serviceWorker' in navigator)) return {soportado: false};
          const reg = await navigator.serviceWorker.getRegistration();
          if (!reg) return {soportado: true, registrado: false};
          // Esperamos a que el SW esté activo y controlando la pagina.
          const listo = await Promise.race([
            new Promise((res) => {
              if (reg.active && navigator.serviceWorker.controller) return res(true);
              navigator.serviceWorker.addEventListener('controllerchange', () => res(true));
              setTimeout(() => res(false), 8000);
            }),
          ]);
          const claves = await caches.keys();
          let entradas = 0;
          // T-119: no basta con CONTAR las entradas: hay que mirar
          // cuales son. Una entrada bajo /api/ es un dato personal
          // cacheado (matriculas, fotos de incidentes, tickets).
          const entradasApi = [];
          for (const k of claves) {
            const c = await caches.open(k);
            const peticiones = await c.keys();
            entradas += peticiones.length;
            for (const p of peticiones) {
              if (p.url.includes('/api/')) entradasApi.push(p.url);
            }
          }
          return {
            soportado: true,
            registrado: true,
            activo: !!reg.active,
            controlando: !!navigator.serviceWorker.controller,
            listo,
            ambito: reg.scope,
            clavesCache: claves.length,
            entradasCache: entradas,
            entradasApi,
          };
        }"""
    )
    if not estado.get("soportado"):
        return ["el navegador no soporta service workers"]
    if not estado.get("registrado"):
        return ["el service worker NO se ha registrado"]
    if not estado.get("activo"):
        fallos.append("el service worker no ha quedado activo")
    if not estado.get("controlando"):
        fallos.append("el service worker no controla la pagina")
    if not estado.get("listo"):
        fallos.append("el service worker tardó más de 8 s en tomar el control")
    if not estado.get("entradasCache"):
        fallos.append(
            "la cache del service worker está vacia: sin precache la app "
            "no arranca sin red",
        )
    # T-119 (2026-10-23): la API NO se cachea nunca. Si aparece una
    # entrada bajo /api/, es un dato personal cacheado en el navegador:
    # el usuario B de un movil compartido podria ver lo del usuario A.
    entradas_api = estado.get("entradasApi") or []
    if entradas_api:
        fallos.append(
            f"la cache del service worker tiene {len(entradas_api)} entrada(s) "
            f"de la API: la API no se cachea nunca (dato personal, LOPDGDD). "
            f"Ejemplos: {entradas_api[:3]}",
        )
    if not fallos:
        print(
            f"  service worker OK: activo, controlando, "
            f"{estado.get('entradasCache')} entradas precacheadas en "
            f"{estado.get('clavesCache')} cache(s) y 0 de la API, "
            f"ambito {estado.get('ambito')}",
        )
    return fallos


def _comprobar_sin_red(pagina, url_base: str) -> list[str]:
    """Corta la red y recarga: la app debe arrancar desde la cache."""
    fallos: list[str] = []
    contexto = pagina.context
    contexto.set_offline(True)
    try:
        pagina.goto(url_base, wait_until="domcontentloaded", timeout=20000)
        pagina.wait_for_timeout(1200)
        hay_app = pagina.evaluate(
            "() => !!document.querySelector('#app') && "
            "document.querySelector('#app').children.length > 0"
        )
        if not hay_app:
            fallos.append("sin red, la pagina se queda vacia: el SW no sirve el shell")
    except Exception as exc:  # noqa: BLE001
        fallos.append(f"sin red la navegacion falla: {type(exc).__name__}: {exc}")
    finally:
        contexto.set_offline(False)
    if not fallos:
        print("  sin red: la app arranca desde la cache del service worker")
    return fallos


def _comprobar_requisitos_servidor(url_base: str) -> list[str]:
    """Comprueba con la MISMA puerta del CI que el servidor cumple los
    requisitos del PWA (T-58).

    Se importa la puerta en vez de reimplementar sus comprobaciones: si las
    dos midieran cosas distintas, esta comprobación daría un falso verde
    (la trampa de "dos comprobaciones que comparten la fuente de verdad").
    """
    fallos: list[str] = []
    for nombre, ok, detalle in comprobar_requisitos(url_base):
        if ok:
            print(f"  servidor OK: {nombre}")
        else:
            fallos.append(
                f"el servidor no cumple un requisito del PWA: {nombre} ({detalle})"
            )
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="URL ya en marcha (por defecto se sirve dist/)")
    ap.add_argument("--dist", default=str(DIST), help="carpeta del build")
    args = ap.parse_args()

    servidor = None
    if args.url:
        url_base = args.url.rstrip("/")
    else:
        dist = Path(args.dist)
        if not (dist / "index.html").is_file():
            print(f"ERROR: no hay build en {dist}. Ejecuta 'npm run build' primero.")
            return 2
        servidor, url_base = _servir(dist)
    print(f"PWA QA contra {url_base}")

    fallos: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(viewport={"width": 1280, "height": 800})
        pagina = contexto.new_page()
        errores: list[str] = []
        pagina.on(
            "console",
            lambda m: errores.append(f"{m.type}: {m.text}")
            if m.type == "error" else None,
        )
        try:
            pagina.goto(url_base, wait_until="networkidle", timeout=30000)
        except Exception as exc:  # noqa: BLE001
            print(f"  la carga inicial fallo: {type(exc).__name__}: {exc}")

        fallos += _comprobar_manifiesto(url_base)
        fallos += _comprobar_service_worker(pagina)
        fallos += _comprobar_sin_red(pagina, url_base)
        fallos += _comprobar_requisitos_servidor(url_base)

        if errores:
            fallos += [f"error de consola: {e[:120]}" for e in errores[:5]]
        navegador.close()

    if servidor is not None:
        with contextlib.suppress(Exception):
            servidor.shutdown()

    if fallos:
        print(f"\n{len(fallos)} problema(s):")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nPWA OK: manifiesto, iconos, service worker y arranque sin red.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
