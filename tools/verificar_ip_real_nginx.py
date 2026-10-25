"""Puerta: el nginx de producción deja ver la IP real del visitante.

POR QUÉ (T-183, 2026-10-25)
---------------------------
En una sucursal el tráfico es:

    navegador -> terminador de TLS -> nginx (contenedor) -> backend

nginx ve como cliente al **terminador de TLS**, no al visitante. Con
``proxy_set_header X-Forwarded-For $remote_addr`` (lo que puso el T-62
para que el cliente no inyectase su IP), el backend recibía **siempre** la
IP del terminador.

Medido con el nginx de producción delante de un upstream que devuelve las
cabeceras que recibe:

    peticion con X-Forwarded-For: 203.0.113.7 (el visitante)
      -> llega al backend: X-Forwarded-For: 172.17.0.1   (el terminador)

Y la consecuencia, con el backend de verdad detrás:

    login del cliente A (203.0.113.7): 200
    login del cliente B (198.51.100.9): 200
    rl:login:ip:172.17.0.1 = 2      <- UN solo bucket para dos personas

El bucket del rate-limit de login es **por IP**: todos los clientes de la
sucursal compartían uno. En producción el límite es de 10 intentos por IP
cada 5 minutos, así que el login número 11 de la sucursal recibía un
**429 para todo el mundo** (y se lo llevaba el último que lo intentó).

El arreglo es el módulo ``realip`` de nginx: con el terminador en la
lista de confianza, ``$remote_addr`` pasa a ser la IP real del visitante
y lo que se reenvía al backend es esa. Medido después del arreglo:

    rl:login:ip:203.0.113.7 = 1
    rl:login:ip:198.51.100.9 = 1      <- un bucket por cliente

Lo que exige esta puerta:

1. La plantilla de nginx configura ``real_ip_header X-Forwarded-For``,
   ``real_ip_recursive on`` y al menos un ``set_real_ip_from``.
2. Los rangos que confía nginx **cubren** los que confía el backend
   (``TRUSTED_PROXIES`` del compose de producción): si el backend no
   confía en el proxy que le habla, ignora el XFF y vuelve a ver la IP
   del proxy.
3. La plantilla sigue reenviando ``X-Forwarded-For $remote_addr`` (que,
   con ``realip``, ya es la del visitante).

Uso:
    python tools/verificar_ip_real_nginx.py
    python tools/verificar_ip_real_nginx.py --autoprueba
"""
from __future__ import annotations

import argparse
import ipaddress
import re
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

PLANTILLA_NGINX = RAIZ / "frontend" / "nginx" / "templates" / "default.conf.template"
COMPOSE_PROD = RAIZ / "docker-compose.prod.yml"

RE_SET_REAL_IP = re.compile(r"^\s*set_real_ip_from\s+([^;]+);", re.MULTILINE)
RE_REAL_IP_HEADER = re.compile(r"^\s*real_ip_header\s+([^;]+);", re.MULTILINE)
RE_REAL_IP_RECURSIVE = re.compile(r"^\s*real_ip_recursive\s+([^;]+);", re.MULTILINE)
RE_PROXY_XFF = re.compile(
    r"^\s*proxy_set_header\s+X-Forwarded-For\s+(\S+);", re.MULTILINE | re.IGNORECASE
)
RE_TRUSTED_PROXIES = re.compile(
    r"^\s*TRUSTED_PROXIES:\s*\$\{TRUSTED_PROXIES:-(.+?)\}\s*$", re.MULTILINE
)


def _redes(texto: str) -> list[ipaddress._BaseNetwork]:
    """Parsea los CIDR de una lista separada por comas."""
    salida: list[ipaddress._BaseNetwork] = []
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        try:
            salida.append(ipaddress.ip_network(trozo, strict=False))
        except ValueError:
            continue
    return salida


def leer_plantilla(ruta: Path) -> dict[str, object]:
    """Saca de la plantilla de nginx lo que esta puerta vigila."""
    texto = ruta.read_text(encoding="utf-8")
    return {
        "set_real_ip_from": [
            m.group(1).strip() for m in RE_SET_REAL_IP.finditer(texto)
        ],
        "real_ip_header": [
            m.group(1).strip() for m in RE_REAL_IP_HEADER.finditer(texto)
        ],
        "real_ip_recursive": [
            m.group(1).strip() for m in RE_REAL_IP_RECURSIVE.finditer(texto)
        ],
        "proxy_xff": [m.group(1).strip() for m in RE_PROXY_XFF.finditer(texto)],
    }


def leer_trusted_proxies(ruta: Path) -> list[str]:
    """Saca los CIDR por defecto de ``TRUSTED_PROXIES`` en el compose."""
    texto = ruta.read_text(encoding="utf-8")
    m = RE_TRUSTED_PROXIES.search(texto)
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def _cubre(rango: ipaddress._BaseNetwork, red: ipaddress._BaseNetwork) -> bool:
    """¿El rango de nginx contiene el del backend (o es el mismo)?"""
    if rango.version != red.version:
        return False
    return rango == red or rango.supernet_of(red)


def comparar(plantilla: dict[str, object], proxies_backend: list[str]) -> list[str]:
    """Los problemas encontrados (vacío si todo está bien)."""
    problemas: list[str] = []

    if not plantilla["set_real_ip_from"]:
        problemas.append(
            "la plantilla de nginx no tiene `set_real_ip_from`: sin el modulo "
            "`realip`, nginx ve la IP del terminador de TLS y la reenvia al "
            "backend. Todos los clientes de la sucursal comparten un unico "
            "bucket del rate-limit de login (medido: `rl:login:ip:172.17.0.1 "
            "= 2` con dos clientes distintos)"
        )
    cabeceras = [h.lower() for h in plantilla["real_ip_header"]]  # type: ignore[union-attr]
    if "x-forwarded-for" not in cabeceras:
        problemas.append(
            "la plantilla de nginx no tiene `real_ip_header X-Forwarded-For`: "
            "sin eso, el modulo `realip` no sabe de que cabecera sacar la IP "
            "real del visitante"
        )
    recursivo = [r.lower() for r in plantilla["real_ip_recursive"]]  # type: ignore[union-attr]
    if "on" not in recursivo:
        problemas.append(
            "la plantilla de nginx no tiene `real_ip_recursive on`: sin eso, "
            "se coge el primer elemento del XFF, que puede inyectar el "
            "cliente (el T-62)"
        )
    if "$remote_addr" not in plantilla["proxy_xff"]:  # type: ignore[operator]
        problemas.append(
            "la plantilla de nginx no reenvia `X-Forwarded-For $remote_addr`: "
            "con `realip` puesto, `$remote_addr` es la IP real del visitante "
            "y es lo que tiene que llegar al backend"
        )

    # Los rangos que Trusta nginx deben CUBRIR los del backend.
    rangos_nginx = _redes(", ".join(plantilla["set_real_ip_from"]))  # type: ignore[arg-type]
    for cidr in proxies_backend:
        try:
            red = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            problemas.append(f"`TRUSTED_PROXIES` del compose no es un CIDR: {cidr}")
            continue
        if not any(_cubre(r, red) for r in rangos_nginx):
            problemas.append(
                f"el backend confía en {cidr} (TRUSTED_PROXIES) pero nginx no "
                f"confia en ningun rango que lo cubra (set_real_ip_from: "
                f"{', '.join(plantilla['set_real_ip_from']) or 'ninguno'}): el "
                "backend ignoraria el XFF y volveria a ver la IP del proxy"
            )
    return problemas


# ── El modo «--medir»: la comprobación de verdad ─────────────────────────
#
# El modo estático dice «la plantilla tiene el módulo realip». Este dice
# «con esa plantilla, el upstream recibe la IP del visitante». Lo segundo
# es lo que importa; lo primero es sólo una forma barata de mirar el
# fichero.

#: La IP del visitante simulado (rango de documentación, RFC 5737).
IP_VISITANTE = "203.0.113.7"


def medir(plantilla: Path) -> tuple[bool, str]:
    """Levanta el nginx con la plantilla y comprueba qué IP ve el upstream.

    Devuelve ``(ok, detalle)``. ``ok`` es True cuando el upstream recibe
    la IP del visitante (o sea: la del ``X-Forwarded-For`` de la petición,
    no la del proxy).
    """
    import json
    import socket
    import subprocess
    import threading
    import time
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    recibidas: list[dict[str, str]] = []

    class _Upstream(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            recibidas.append({k.lower(): v for k, v in self.headers.items()})
            cuerpo = json.dumps(recibidas[-1]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *_args) -> None:
            pass

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto_upstream = int(s.getsockname()[1])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto_nginx = int(s.getsockname()[1])

    servidor = HTTPServer(("0.0.0.0", puerto_upstream), _Upstream)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    nombre = "verificar-ip-real-nginx"
    subprocess.run(["docker", "rm", "-f", nombre], capture_output=True, text=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", nombre,
            "-p", f"127.0.0.1:{puerto_nginx}:80",
            # OJO (T-184-bis, 2026-10-25): `host.docker.internal` es de
            # Docker Desktop; en Linux hay que mapearlo al gateway del
            # bridge (Docker 20.10+). Sin esto, el CI (ubuntu) no
            # llega al upstream y la autoprueba medida falla.
            "--add-host", "host.docker.internal:host-gateway",
            "-e", f"API_UPSTREAM=http://host.docker.internal:{puerto_upstream}",
            "-v", f"{plantilla}:/etc/nginx/templates/default.conf.template:ro",
            "nginx:1.27-alpine",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto_nginx}/healthz", timeout=2
                ).read()
                break
            except Exception:
                time.sleep(0.5)
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{puerto_nginx}/api/v1/health",
            headers={"X-Forwarded-For": IP_VISITANTE},
        )
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", "replace")
        cabeceras = json.loads(cuerpo)
        xff = cabeceras.get("x-forwarded-for", "")
        if xff == IP_VISITANTE:
            return True, f"el upstream ha recibido la IP del visitante ({xff})"
        return False, (
            f"el upstream ha recibido {xff or '(nada)'} en vez de la IP del "
            f"visitante ({IP_VISITANTE}): la peticion sale de un proxy y "
            "nginx no esta usando el modulo realip"
        )
    finally:
        subprocess.run(["docker", "rm", "-f", nombre], capture_output=True, text=True)
        servidor.shutdown()


def autoprueba() -> int:
    """Comprueba que la puerta puede fallar (casos de mentira a mano)."""
    print("Autoprueba de la puerta de la IP real:")
    fallos = 0

    casos = [
        (
            "sin el modulo realip (la plantilla de antes del T-183)",
            """
server {
    listen 80;
    proxy_set_header X-Forwarded-For $remote_addr;
}
""",
            ["172.16.0.0/12", "10.0.0.0/8"],
            False,
        ),
        (
            "realip sin real_ip_recursive",
            """
server {
    listen 80;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 10.0.0.0/8;
    real_ip_header X-Forwarded-For;
    proxy_set_header X-Forwarded-For $remote_addr;
}
""",
            ["172.16.0.0/12", "10.0.0.0/8"],
            False,
        ),
        (
            "realip con un rango que no cubre el del backend",
            """
server {
    listen 80;
    set_real_ip_from 192.168.0.0/16;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
    proxy_set_header X-Forwarded-For $remote_addr;
}
""",
            ["172.16.0.0/12", "10.0.0.0/8"],
            False,
        ),
        (
            "realip completo y con los rangos del backend",
            """
server {
    listen 80;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 10.0.0.0/8;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
    proxy_set_header X-Forwarded-For $remote_addr;
}
""",
            ["172.16.0.0/12", "10.0.0.0/8"],
            True,
        ),
    ]

    with tempfile.TemporaryDirectory(prefix="t183_") as temporal:
        base = Path(temporal)
        for nombre, plantilla, proxies, debe_pasar in casos:
            ruta = base / "default.conf.template"
            ruta.write_text(plantilla, encoding="utf-8")
            problemas = comparar(leer_plantilla(ruta), proxies)
            paso = not problemas
            if paso != debe_pasar:
                fallos += 1
                print(f"  FALLO {nombre}: la puerta {'paso' if paso else 'fallo'}")
                for p in problemas:
                    print(f"          {p}")
            else:
                print(f"  OK {nombre}: la puerta {'falla' if not paso else 'pasa'}")

    if fallos:
        print(f"\nAutoprueba FALLIDA: {fallos} caso(s)")
        return 1
    print("\nAutoprueba correcta: la puerta sabe fallar.")
    return 0


def autoprueba_medida() -> int:
    """Mide con la plantilla buena y con una copia a la que se le quita
    el módulo realip: la medición tiene que fallar en el segundo caso."""
    import tempfile

    print("Autoprueba (medida) de la puerta de la IP real:")
    fallos = 0

    texto = PLANTILLA_NGINX.read_text(encoding="utf-8")
    sin_realip = "\n".join(
        linea
        for linea in texto.splitlines()
        if not linea.strip().startswith(
            ("set_real_ip_from", "real_ip_header", "real_ip_recursive")
        )
    )

    with tempfile.TemporaryDirectory(prefix="t183_medida_") as temporal:
        base = Path(temporal)
        casos = [
            ("la plantilla del repo", texto, True),
            ("una copia sin el modulo realip", sin_realip, False),
        ]
        for nombre, contenido, debe_pasar in casos:
            ruta = base / "default.conf.template"
            ruta.write_text(contenido, encoding="utf-8")
            try:
                ok, detalle = medir(ruta)
            except Exception as exc:  # noqa: BLE001
                fallos += 1
                print(f"  FALLO {nombre}: la medicion no se pudo hacer: {exc}")
                continue
            if ok != debe_pasar:
                fallos += 1
                print(f"  FALLO {nombre}: la medicion {'pasa' if ok else 'falla'}")
                print(f"          {detalle}")
            else:
                print(f"  OK {nombre}: {detalle}")

    if fallos:
        print(f"\nAutoprueba (medida) FALLIDA: {fallos} caso(s)")
        return 1
    print("\nAutoprueba (medida) correcta.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que la puerta puede fallar (casos de mentira a mano).",
    )
    parser.add_argument(
        "--medir",
        action="store_true",
        help=(
            "Mide de verdad: levanta el nginx de produccion con la plantilla "
            "y comprueba que el upstream recibe la IP del visitante."
        ),
    )
    parser.add_argument(
        "--autoprueba-medida",
        action="store_true",
        help=(
            "Autoprueba MEDIDA (necesita Docker): con una copia de la "
            "plantilla sin el modulo realip, la medicion tiene que fallar. "
            "No va en el CI: en Linux `host.docker.internal` no existe "
            "(esta es la de Docker Desktop)."
        ),
    )
    args = parser.parse_args()

    if args.autoprueba:
        return autoprueba()
    if args.autoprueba_medida:
        return autoprueba_medida()
    if args.medir:
        ok, detalle = medir(PLANTILLA_NGINX)
        if not ok:
            print(f"FALLO: {detalle}")
            return 1
        print(f"OK: {detalle}")
        return 0

    plantilla = leer_plantilla(PLANTILLA_NGINX)
    proxies = leer_trusted_proxies(COMPOSE_PROD)
    problemas = comparar(plantilla, proxies)
    if problemas:
        print("FALLO: el nginx de produccion no deja ver la IP real:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print(
        "OK: el nginx de produccion deja ver la IP real del visitante "
        f"(set_real_ip_from: {', '.join(plantilla['set_real_ip_from'])}; "
        f"TRUSTED_PROXIES del backend: {', '.join(proxies)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
