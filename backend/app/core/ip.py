"""Helper para extraer la IP real del cliente, parseando ``X-Forwarded-For``.

Sprint Fase 3C (2026-07-01). Usado por:

- ``app.core.middleware.AuditMiddleware``: para que
  ``request.state.audit["ip"]`` refleje la IP del cliente real (no del
  proxy Nginx/Traefik/Cloudflare).
- ``app.api.v1.auth.login_json``: para alimentar el bucket
  ``rl:login:ip:{ip}`` del ``LoginRateLimiter``.

Reglas:

1. Sin ``X-Forwarded-For`` → ``request.client.host`` (sin cambios).
2. Con XFF y ``client.host`` en ``settings.trusted_proxies`` (CIDR) →
   primer elemento de XFF (cliente real en cadena estándar).
3. Con XFF pero ``client.host`` NO trusted → ``request.client.host``
   (defensa contra spoofing: un atacante no puede inyectar XFF si
   no pasa por un proxy en el que confiamos).
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
    for cidr in settings.trusted_proxies or ():
        try:
            if client_ip in ipaddress.ip_network(cidr, strict=False):
                return xff.split(",")[0].strip()
        except ValueError:
            continue
    return client_host