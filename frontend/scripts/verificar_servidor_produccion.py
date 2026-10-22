#!/usr/bin/env python3
"""Puerta: el servidor de producción del frontend cumple los requisitos del PWA.

POR QUÉ existe (T-56/T-57, 2026-10-22): hasta ahora el único servidor del
frontend era el de DESARROLLO (Vite con HMR), que no sirve el build. Se
creó la imagen de producción con nginx (``frontend/Dockerfile.prod``) y, con
ella, la puerta que comprueba los requisitos que el README (§ PWA) le exige
al servidor estático. Los requisitos son:

  1. El manifiesto se sirve como ``application/manifest+json``.
  2. El service worker se sirve SIN caché (``Cache-Control: no-store``): si el
     navegador lo cachea, sigue ejecutando la versión vieja.
  3. El ``index.html`` se sirve sin caché (``Cache-Control: no-cache``): si no,
     un despliegue nuevo no se ve.
  4. El bundle se sirve **como JavaScript**: con el ``content-type``
     equivocado el navegador no lo ejecuta y la app no arranca.
  5. Una ruta profunda devuelve el shell (fallback de la SPA).

Uso:
    python frontend/scripts/verificar_servidor_produccion.py --url http://127.0.0.1:8091
    python frontend/scripts/verificar_servidor_produccion.py --autoprueba

POR QUÉ es Python y no un script ``sh`` dentro del contenedor (T-57): una
puerta que no puede demostrar que detecta lo que dice detectar no es una
puerta. Con el script dentro del contenedor no había forma de comprobar que
fallaba: hacía falta el ``wget`` de busybox y no había ningún ``wget`` en el
host ni forma de inyectar un servidor de mentira. En Python la autoprueba
levanta un servidor HTTP escrito a mano que devuelve exactamente lo
contrario de lo exigido y comprueba que la puerta lo detecta.

Sólo se usa la biblioteca estándar: así la puerta se puede ejecutar en
cualquier job del CI sin instalar nada.
"""

from __future__ import annotations

import argparse
import http.server
import re
import sys
import threading
import urllib.error
import urllib.request

TIMEOUT_POR_DEFECTO = 10

# La ruta profunda con la que se comprueba el fallback de la SPA.
RUTA_PROFUNDA = "/mis-tickets"


def _normalizar_base(base: str) -> str:
    """Quita la barra final para poder concatenar rutas sin duplicarlas."""
    return base.rstrip("/")


def _cabecera(cabeceras: dict[str, str], nombre: str) -> str:
    """Devuelve una cabecera sin distinguir mayúsculas (HTTP no las distingue)."""
    for clave, valor in cabeceras.items():
        if clave.lower() == nombre.lower():
            return valor
    return ""


def _pedir(url: str, timeout: int = TIMEOUT_POR_DEFECTO) -> tuple[int, dict[str, str], bytes]:
    """Pide una URL y devuelve ``(estado, cabeceras, cuerpo)``.

    Un 4xx/5xx NO es una excepción: es un resultado, y la puerta tiene que
    poder decir "el servidor respondió 404" en vez de reventar.
    """
    peticion = urllib.request.Request(
        url, headers={"User-Agent": "verificar-servidor-produccion/1"}
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return (
                int(respuesta.status),
                dict(respuesta.headers.items()),
                respuesta.read(),
            )
    except urllib.error.HTTPError as error:
        return int(error.code), dict(error.headers.items()), error.read()


def comprobar_requisitos(base: str, timeout: int = TIMEOUT_POR_DEFECTO) -> list[tuple[str, bool, str]]:
    """Comprueba los 5 requisitos. Devuelve ``(nombre, ok, detalle)`` por requisito.

    Esta función es el ALGORITMO de la puerta. La autoprueba la llama contra
    un servidor de mentira: si la puerta no puede fallar, la autoprueba lo
    detecta.
    """
    base = _normalizar_base(base)
    resultados: list[tuple[str, bool, str]] = []

    # 1. El manifiesto, con su content-type.
    estado, cabeceras, _ = _pedir(f"{base}/manifest.webmanifest", timeout)
    ctype = _cabecera(cabeceras, "Content-Type")
    ok = estado == 200 and "application/manifest+json" in ctype.lower()
    resultados.append(
        (
            "el manifiesto se sirve como application/manifest+json",
            ok,
            f"estado {estado}, content-type '{ctype}'",
        )
    )

    # 2. El service worker, sin caché.
    estado, cabeceras, _ = _pedir(f"{base}/sw.js", timeout)
    cache = _cabecera(cabeceras, "Cache-Control")
    ok = estado == 200 and "no-store" in cache.lower()
    resultados.append(
        (
            "el service worker se sirve sin caché (no-store)",
            ok,
            f"estado {estado}, cache-control '{cache}'",
        )
    )

    # 3. El index.html, sin caché.
    estado, cabeceras, cuerpo = _pedir(f"{base}/index.html", timeout)
    cache = _cabecera(cabeceras, "Cache-Control")
    ok = estado == 200 and "no-cache" in cache.lower()
    resultados.append(
        (
            "el index.html se sirve sin caché (no-cache)",
            ok,
            f"estado {estado}, cache-control '{cache}'",
        )
    )

    # 4. El bundle, como JavaScript. Se descubre en el index.html (no se
    #    hardcodea el nombre: el hash del build cambia en cada construcción).
    html = cuerpo.decode("utf-8", "replace") if estado == 200 else ""
    encontrados = re.findall(r"/assets/index-[^\"'\s>]+\.js", html)
    if not encontrados:
        resultados.append(
            (
                "el bundle se sirve como JavaScript",
                False,
                "el index.html no referencia ningún /assets/index-*.js",
            )
        )
    else:
        activo = encontrados[0]
        estado_b, cabeceras_b, _ = _pedir(f"{base}{activo}", timeout)
        ctype_b = _cabecera(cabeceras_b, "Content-Type")
        ok = estado_b == 200 and "javascript" in ctype_b.lower()
        resultados.append(
            (
                f"el bundle ({activo}) se sirve como JavaScript",
                ok,
                f"estado {estado_b}, content-type '{ctype_b}'",
            )
        )

    # 5. El fallback de la SPA en una ruta profunda.
    estado, cabeceras, _ = _pedir(f"{base}{RUTA_PROFUNDA}", timeout)
    ctype = _cabecera(cabeceras, "Content-Type")
    ok = estado == 200 and "text/html" in ctype.lower()
    resultados.append(
        (
            "el fallback de la SPA sirve el shell en una ruta profunda",
            ok,
            f"estado {estado}, content-type '{ctype}'",
        )
    )

    return resultados


# ── Autoprueba ───────────────────────────────────────────────────────────
# El servidor de mentira está escrito A MANO a propósito: si saliera del
# mismo código que la configuración real de nginx, la puerta y el servidor
# podrían mentir a la vez y la autoprueba no demostraría nada (la trampa
# documentada en AGENTS.md: dos comprobaciones que comparten la fuente de
# verdad no se vigilan entre sí).

MANIFESTO = b'{"name":"mentira","start_url":"/"}'
INDEX_BUENO = (
    b'<html><head><link rel="manifest" href="/manifest.webmanifest"></head>'
    b'<body><div id="app"></div>'
    b'<script type="module" crossorigin src="/assets/index-abc123.js"></script>'
    b"</body></html>"
)


class _ServidorFalso(http.server.BaseHTTPRequestHandler):
    """Servidor de mentira escrito a mano: sirve lo contrario de lo exigido."""

    modo = "verdad"  # "verdad" (cumple) o "mentira" (incumple a propósito)

    def do_GET(self) -> None:  # noqa: N802 - el nombre lo impone la stdlib
        ruta = self.path.split("?")[0]
        honesto = self.modo == "verdad"

        if ruta == "/manifest.webmanifest":
            ctype = "application/manifest+json" if honesto else "text/plain"
            self._responder(200, ctype, MANIFESTO)
        elif ruta == "/sw.js":
            cache = "no-store" if honesto else "max-age=31536000, immutable"
            self._responder(200, "application/javascript", b"// sw", cache)
        elif ruta == "/index.html":
            cache = "no-cache" if honesto else "max-age=31536000, immutable"
            self._responder(200, "text/html", INDEX_BUENO, cache)
        elif ruta.startswith("/assets/"):
            ctype = "application/javascript" if honesto else "application/octet-stream"
            self._responder(200, ctype, b"console.log(1)")
        elif ruta == RUTA_PROFUNDA:
            if honesto:
                self._responder(200, "text/html", b"<html>shell</html>")
            else:
                self._responder(404, "text/plain", b"not found")
        else:
            self._responder(404, "text/plain", b"not found")

    def _responder(
        self, estado: int, ctype: str, cuerpo: bytes, cache: str | None = None
    ) -> None:
        self.send_response(estado)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(cuerpo)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args: object) -> None:
        """Silencia el log: la autoprueba no necesita ruido por consola."""


def _arrancar(modo: str) -> tuple[str, http.server.ThreadingHTTPServer]:
    """Levanta el servidor falso en un hilo y devuelve ``(url_base, servidor)``."""
    clase = type(f"_Servidor{modo}", (_ServidorFalso,), {"modo": modo})
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), clase)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    host, puerto = servidor.server_address[0], servidor.server_address[1]
    return f"http://{host}:{puerto}", servidor


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (y que no falla siempre).

    Dos casos:
      1. Un servidor que cumple los requisitos -> la puerta pasa.
      2. Un servidor que incumple TODOS -> la puerta los detecta todos.

    El caso 2 es el que importa: sin él, esta puerta sería una línea de
    texto que dice "OK".
    """
    print("Autoprueba de la puerta del servidor de produccion:")

    fallos = 0

    url_ok, servidor_ok = _arrancar("verdad")
    try:
        resultados = comprobar_requisitos(url_ok)
    finally:
        servidor_ok.shutdown()
        servidor_ok.server_close()

    cumplidos = [r for r in resultados if r[1]]
    if len(cumplidos) == len(resultados):
        print(f"  OK    con un servidor correcto la puerta pasa ({len(resultados)}/{len(resultados)})")
    else:
        fallos += 1
        print(f"  FALLO con un servidor correcto la puerta falla ({len(cumplidos)}/{len(resultados)})")
        for nombre, _, detalle in resultados:
            print(f"          {nombre}: {detalle}")

    url_malo, servidor_malo = _arrancar("mentira")
    try:
        resultados = comprobar_requisitos(url_malo)
    finally:
        servidor_malo.shutdown()
        servidor_malo.server_close()

    detectados = [r for r in resultados if not r[1]]
    if len(detectados) == len(resultados):
        print(
            f"  OK    con un servidor roto la puerta detecta los {len(detectados)} requisitos"
        )
    else:
        fallos += 1
        print(
            f"  FALLO con un servidor roto la puerta sólo detecta "
            f"{len(detectados)}/{len(resultados)} requisitos"
        )
        for nombre, _, detalle in resultados:
            print(f"          {nombre}: {detalle}")

    if fallos:
        print(f"AUTOPRUEBA FALLIDA ({fallos} problema(s))")
        return 1
    print("AUTOPRUEBA CORRECTA: la puerta puede fallar y puede pasar")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba los requisitos del PWA en el servidor de producción."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8091",
        help="URL base del servidor de producción (por defecto el puerto local del CI)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT_POR_DEFECTO,
        help="Segundos de espera por petición",
    )
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (servidor de mentira escrito a mano)",
    )
    args = parser.parse_args(argv)

    if args.autoprueba:
        return autoprueba()

    base = _normalizar_base(args.url)
    print(f"Requisitos del servidor de produccion ({base}):")
    try:
        resultados = comprobar_requisitos(base, args.timeout)
    except OSError as error:
        # Ni siquiera se pudo hablar con el servidor: eso NO es "requisito
        # cumplido", es un fallo de la puerta.
        print(f"  FALLO  no se pudo hablar con el servidor: {error}")
        return 1

    fallidos = 0
    for nombre, ok, detalle in resultados:
        if ok:
            print(f"  OK    {nombre}")
        else:
            fallidos += 1
            print(f"  FALLO {nombre}: {detalle}")

    if fallidos:
        print(f"FALLAN {fallidos} requisito(s) del servidor de produccion.")
        return 1
    print(f"El servidor de produccion cumple los {len(resultados)} requisitos del PWA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
