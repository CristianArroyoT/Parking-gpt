"""Tests de ``get_real_ip``: la IP del cliente no puede ser elegida por el
atacante (T-62).

OJO (2026-10-22): antes se tomaba el **primer** elemento del
``X-Forwarded-For``, que es justo el que escribe el cliente. Un atacante
que mandara un XFF distinto en cada intento caía en un bucket distinto del
rate-limit de login (10 intentos / 5 min) y lo esquivaba. El **último**
elemento lo añade el proxy de confianza, que es el más cercano al backend:
no lo puede elegir el cliente.

Y si el proxy (nginx) no está en ``trusted_proxies``, el XFF se ignora
enteramente: un atacante no puede inyectar su IP si no pasa por un proxy en
el que confiamos.
"""
from __future__ import annotations

from starlette.requests import Request

from app.core.ip import get_real_ip

#: IP dentro de ``10.0.0.0/8`` (trusted_proxies por defecto) = el proxy.
IP_PROXY = "10.1.2.3"
#: IP de un cliente cualquiera.
IP_CLIENTE = "203.0.113.9"


def _request(client_host: str, xff: str | None = None) -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (client_host, 40000),
            "server": ("testserver", 80),
        }
    )


def test_sin_xff_devuelve_el_cliente() -> None:
    assert get_real_ip(_request(IP_PROXY)) == IP_PROXY


def test_xff_de_un_elemento_con_proxy_de_confianza() -> None:
    assert get_real_ip(_request(IP_PROXY, IP_CLIENTE)) == IP_CLIENTE


def test_xff_con_varios_elementos_usa_el_ultimo() -> None:
    """El último lo añade el proxy de confianza; el primero lo pone el
    cliente (y puede ser mentira)."""
    xff = f"198.51.100.7, {IP_CLIENTE}"
    assert get_real_ip(_request(IP_PROXY, xff)) == IP_CLIENTE


def test_el_atacante_no_puede_elegir_la_ip() -> None:
    """Si el cliente se inyecta su IP, el backend usa la del proxy."""
    xff = "198.51.100.7, 198.51.100.8, 198.51.100.9"
    assert get_real_ip(_request(IP_PROXY, xff)) == "198.51.100.9"


def test_el_xff_se_ignora_si_el_cliente_no_es_de_confianza() -> None:
    """Sin un proxy de confianza, el XFF no se traga: manda ``client.host``."""
    request = _request("198.51.100.50", "1.2.3.4")
    assert get_real_ip(request) == "198.51.100.50"


def test_un_xff_vacio_no_rompe() -> None:
    assert get_real_ip(_request(IP_PROXY, "   ")) == IP_PROXY
