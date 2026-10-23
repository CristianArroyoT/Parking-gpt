"""Normalizacion de correos (T-99).

POR QUE EXISTE: un correo **no distingue** mayusculas de minusculas (en
la practica ningun proveedor de correo las distingue), pero el codigo
comparaba el texto **tal como se escribia**.

Medido el 2026-10-23 contra la API real en marcha: un usuario creado
como ``Gestor.Mixto@solidapp.es`` se logueaba con ese correo exacto
(200) y **no** con ``gestor.mixto@solidapp.es`` (401). Y
``ADMIN@solidapp.es`` tampoco entraba. O sea: el mismo correo Depending
de como lo escribas, y un usuario que teclea en mayusculas se queda
fuera sin entender por que.

La forma canonica es una sola: **sin espacios y en minusculas**. Se
aplica en los dos sitios: al **guardar** (para que no entren dos cuentas
que solo se diferencien en como estan escritas) y al **comparar** (para
que las cuentas que ya estan guardadas en mayusculas sigan entrando).
"""

from __future__ import annotations


def normalizar_email(email: str) -> str:
    """Devuelve el email en su forma canonica: sin espacios y en minusculas."""
    return email.strip().lower()


__all__ = ["normalizar_email"]
