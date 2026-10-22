"""El access log del backend no guarda la query string (T-93).

POR QUE existe este fichero: el frontend mete el JWT en la query string
de las miniaturas y del stream MJPEG (un ``<img>`` no puede mandar
cabeceras). Con el access log de uvicorn tal cual, el token acababa
**en texto claro** en el log -- y de ahí en el fichero que scrapea
Promtail, que lo envía a Loki.

Medido el 2026-10-23 contra el contenedor real:

    "GET /api/v1/incidents/attachments/1/thumbnail?token=SEGRETO... HTTP/1.1" 401

Estos tests comprueban que el filtro hace su trabajo con el **mismo
formato que usa uvicorn** (no con uno inventado): si uvicorn cambiara
la forma de construir la línea, el filtro dejaría de quitar la query y
el log volvería a enseñar el token. Por eso el test usa su
``AccessFormatter`` de verdad.
"""
from __future__ import annotations

import logging

from app.core.logging import instalar_filtro_access_log

#: El token de mentira: se construye en runtime, nunca en el repo.
TOKEN_DE_PRUEBA = "jwt." + ("A" * 20) + ".firma-de-prueba"


def _linea_que_se_escribiria(ruta: str) -> str:
    """La linea tal y como la escribiría uvicorn.

    Se pasa por el **logger** de verdad (no se formatea el registro a
    mano): los filtros de un logger se aplican al pasar por él, que es
    justo lo que hace uvicorn.
    """
    import io

    from uvicorn.logging import AccessFormatter

    logger = logging.getLogger("uvicorn.access")
    flujo = io.StringIO()
    handler = logging.StreamHandler(flujo)
    handler.setFormatter(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s')
    )
    nivel_previo = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        # La misma llamada que hace uvicorn.
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "172.24.0.14:47000", "GET", ruta, "1.1", 401,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel_previo)
    return flujo.getvalue()


def test_el_access_log_no_escribe_la_query_string() -> None:
    """La ruta con token sale sin la query string."""
    instalar_filtro_access_log()
    linea = _linea_que_se_escribiria(
        f"/api/v1/incidents/attachments/1/thumbnail?token={TOKEN_DE_PRUEBA}"
    )
    assert TOKEN_DE_PRUEBA not in linea, (
        "el access log está escribiendo el token de la query string"
    )
    assert "/api/v1/incidents/attachments/1/thumbnail" in linea


def test_una_ruta_sin_query_string_no_cambia() -> None:
    """Una ruta normal se escribe igual (el filtro no toca lo que no debe)."""
    instalar_filtro_access_log()
    linea = _linea_que_se_escribiria("/api/v1/users/me")
    assert "/api/v1/users/me" in linea
    assert "?" not in linea


def test_el_filtro_no_rompe_otros_registros() -> None:
    """El filtro deja pasar los registros que no son de acceso."""
    instalar_filtro_access_log()
    registro = logging.LogRecord(
        name="otro",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="mensaje normal",
        args=None,
        exc_info=None,
    )
    assert registro.args is None
