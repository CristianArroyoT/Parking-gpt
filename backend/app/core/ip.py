"""Helper para extraer la IP real del cliente, parseando ``X-Forwarded-For``.

Sprint Fase 3C (2026-07-01). Usado por:

- ``app.core.middleware.AuditMiddleware``: para que
  ``request.state.audit["ip"]`` refleje la IP del cliente real (no del
  proxy Nginx/Traefik/Cloudflare).
- ``app.api.v1.auth.login_json``: para alimentar el bucket
  ``rl:login:ip:{ip}`` del ``LoginRateLimiter``.

Reglas:

1. Sin ``X-Forwarded-For`` → ``request.client.host`` (sin cambios).
2. Con XFF y ``client.host`` en ``settings.trusted_proxies_list`` (CIDR) →
   **último** elemento de XFF.
3. Con XFF pero ``client.host`` NO trusted → ``request.client.host``
   (defensa contra spoofing: un atacante no puede inyectar XFF si
   no pasa por un proxy en el que confiamos).

OJO (2026-10-22, T-62): antes se tomaba el **primer** elemento. Ese es el
que escribe el cliente (un atacante puede mandar ``X-Forwarded-For: 1.2.3.4``
y quedarse con la IP que quiera), mientras que el **último** lo anade el
proxy de confianza, que es el mas cercano al backend. Con el primero, un
atacante que rotaba un XFF distinto en cada intento esquivaba el
rate-limit de login (cada intento caia en un bucket distinto). El nginx de
produccion ademas ahora SOBREESCRIBE el XFF con ``$remote_addr``, de modo
que llega una sola IP.
"""
from __future__ import annotations

import ipaddress

from fastapi import Request

from app.core.config import get_settings


def get_real_ip(request: Request) -> str:
    """Devuelve la IP del cliente real, parseando XFF si aplica."""
    client_host = request.client.host if request.client else "unknown"
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return client_host

    try:
        client_ip = ipaddress.ip_address(client_host)
    except ValueError:
        # ``client.host`` no es una IP válida (e.g. socket unix en tests).
        return client_host

    settings = get_settings()
    for cidr in settings.trusted_proxies_list:
        try:
            if client_ip in ipaddress.ip_network(cidr, strict=False):
                # El ULTIMO elemento es el que anade el proxy de confianza
                # (T-62): el cliente no puede elegirlo.
                for elemento in reversed(xff.split(",")):
                    elemento = elemento.strip()
                    if elemento:
                        return elemento
        except ValueError:
            continue
    return client_host