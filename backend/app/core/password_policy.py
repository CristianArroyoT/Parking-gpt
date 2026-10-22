"""Politica de contrasenas: el limite real de bcrypt (T-87).

POR QUE ESTE MODULO EXISTE: **bcrypt trunca en silencio a 72 bytes**.
Medido el 2026-10-23 contra el contenedor real:

    >>> bcrypt.verify("a" * 100 + "b", bcrypt.hash("a" * 100))
    True

O sea: dos contrasenas distintas que compartan los primeros 72 bytes son
**la misma contrasena** para el sistema. Los esquemas de la API permitian
hasta 128 caracteres, asi que un usuario podia fijar una clave de 128 y
seguir creyendo que el sufijo protegia algo: no protegia nada. Y al
verificar, una contrasena de mas de 72 bytes servia para entrar con
cualquier sufijo.

El limite vive aqui, en **un solo sitio** y medido en **bytes** (que es lo
que cuenta bcrypt: "a" son 1 byte, "\u00f1" son 2), no en caracteres.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator

LIMITE_BYTES_BCRYPT = 72


def comprobar_bytes_contrasena(valor: str) -> str:
    """Devuelve la contrasena si cabe en 72 bytes UTF-8; si no, la rechaza.

    El mensaje dice los bytes que lleva, porque el usuario cuenta
    caracteres y no bytes: una contrasena de 40 caracteres con tildes
    puede pesar mas de 72 bytes.
    """
    n = len(valor.encode("utf-8"))
    if n > LIMITE_BYTES_BCRYPT:
        raise ValueError(
            f"la contrasena no puede superar {LIMITE_BYTES_BCRYPT} bytes "
            f"(lleva {n}); bcrypt solo tiene en cuenta los primeros "
            f"{LIMITE_BYTES_BCRYPT}"
        )
    return valor


ContrasenaBcrypt = Annotated[str, AfterValidator(comprobar_bytes_contrasena)]
"""Tipo de contrasena que respeta el limite real de bcrypt (72 bytes)."""


__all__ = [
    "ContrasenaBcrypt",
    "LIMITE_BYTES_BCRYPT",
    "comprobar_bytes_contrasena",
]
