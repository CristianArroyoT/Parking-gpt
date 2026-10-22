"""El JWT solo se firma y se acepta con HS256 (T-89).

POR QUE existe este fichero: ``python-jose`` 3.5.0 tiene un aviso
abierto **sin version arreglada** (GHSA-3qf3-8w2g-rqmx /
CVE-2026-85394): al inicializar una clave HMAC acepta una clave publica
DER sin armadura PEM, y **si no se restringen los algoritmos**, un
atacante con la clave publica del servicio puede falsificar un token
HS256.

En este despliegue el caso es imposible, y estos tests son la prueba
que acompaña a la excepcion escrita en ``tools/dependencias_aceptadas.json``
(una excepcion sin prueba no es una excepcion):

1. la configuracion **rechaza** cualquier algoritmo que no sea HS256
   (el codigo vulnerable no se puede ni activar por error de despliegue);
2. al decodificar se restringen los algoritmos: un token firmado con
   HS512 no vale, y uno con ``alg: none`` tampoco.

La excepcion es "no alcanzable", no "da igual": por eso estos tests
existen y por eso se quedan en el repo.
"""
from __future__ import annotations

import base64
import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, decode_token


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _token_craftado(cabecera: dict, payload: dict, firma: str = "") -> str:
    """Token JWT montado a mano (para probar algoritmos que no queremos usar)."""
    return (
        f"{_b64(json.dumps(cabecera).encode())}."
        f"{_b64(json.dumps(payload).encode())}."
        f"{firma}"
    )


def test_el_algoritmo_por_defecto_es_hs256() -> None:
    """El algoritmo configurado es HS256 (clave compartida)."""
    assert get_settings().jwt_algorithm.strip().upper() == "HS256"


def test_la_configuracion_rechaza_otro_algoritmo() -> None:
    """``JWT_ALGORITHM`` distinto de HS256 hace que la app NO levante.

    Fail-fast: mejor un error claro al arrancar que firmar tokens con
    un algoritmo que nadie ha auditado (o que exige una clave
    asimetrica que este despliegue no tiene).
    """
    with pytest.raises(ValidationError) as exc:
        Settings(JWT_ALGORITHM="RS256")
    assert "HS256" in str(exc.value)


def test_un_token_con_alg_none_no_sirve() -> None:
    """Un token con ``alg: none`` (sin firma) se rechaza."""
    token = _token_craftado(
        {"alg": "none", "typ": "JWT"},
        {"sub": "1", "type": "access", "jti": "x"},
    )
    with pytest.raises(ValueError, match="Token inválido o expirado"):
        decode_token(token)


def test_un_token_firmado_con_otro_algoritmo_no_sirve() -> None:
    """Un token firmado con HS512 no vale: solo se acepta HS256."""
    from jose import jwt

    token = jwt.encode(
        {"sub": "1", "type": "access", "jti": "x"},
        get_settings().jwt_secret,
        algorithm="HS512",
    )
    with pytest.raises(ValueError, match="Token inválido o expirado"):
        decode_token(token)


def test_un_token_firmado_con_otra_clave_no_sirve() -> None:
    """Un token firmado con otra clave se rechaza (evidentemente)."""
    from jose import jwt

    token = jwt.encode(
        {"sub": "1", "type": "access", "jti": "x"},
        "otra-clave-que-no-es-la-del-servicio",
        algorithm="HS256",
    )
    with pytest.raises(ValueError, match="Token inválido o expirado"):
        decode_token(token)


def test_un_token_firmado_bien_sirve() -> None:
    """El camino normal sigue funcionando (el arreglo no rompe el login)."""
    token = create_access_token(1, extra={"role": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "1"
    assert payload["role"] == "admin"
