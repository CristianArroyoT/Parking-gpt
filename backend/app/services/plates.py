"""¿Lo que ha leído el OCR es una matrícula o es otro texto?

POR QUÉ (2026-10-22): el OCR devuelve **texto**, no matrículas. Lee
cualquier cosa que haya en la imagen, y en el vídeo de una cámara hay
muchas cosas que **no** son matrículas: el timestamp quemado en la
esquina, el nombre de la marca, el cartel del parking, una matrícula de
propaganda...

Medido (2026-10-22) con el vídeo de QA del repo, que lleva el rótulo
``SOLIDAPP QA — CAM 01`` y el timestamp ``t=105.0s frame=2625``
**quemados en la imagen**: el OCR devolvió la matrícula
``"t=105.0sframe=2625"``. Se descartó sólo por medir 19 caracteres (el
límite del esquema), **por casualidad**: un rótulo corto ("CAM 01",
"HD 1080P") habría pasado el filtro y habría **creado un vehículo
fantasma** —la columna ``vehicles.plate`` es ``UNIQUE``— y, si la
geocerca estaba pintada encima, un ticket.

En un parking real esto no es hipotético: casi todas las cámaras
queman el timestamp y a veces la marca en la imagen.

La regla es **permisiva a propósito**: no se quiere rechazar una
matrícula legítima (diplomática, antigua o extranjera), sólo el texto
que no tiene forma de matrícula.
"""
from __future__ import annotations

import re

#: Formatos de matrícula que se aceptan, ya **normalizados** (mayúsculas
#: y sin separadores):
#:
#: - ``1234ABC``: formato español actual (4 dígitos + 3 letras).
#: - ``1234B`` / ``E1234A`` / ``M1234A``: antiguos, diplomáticas y
#:   consulares.
#: - ``ABC123``: formato alemán (3 letras + 3 dígitos), por si el
#:   parking tiene clientes de fuera.
#:
#: Lo que **no** entra: el texto quemado ("T1050SFRAME2625", "CAM01",
#: "SOLIDAPP"), porque no tiene forma de matrícula. El patrón está
#: **anclado** (usa ``^...$``), así que "T1050SFRAME" tampoco entra: los
#: cuatro dígitos de "1050" se consumen y luego sobran letras.
PATRON_MATRICULA = re.compile(
    r"^(?:[0-9]{4}[A-Z]{1,3}|[A-Z]{1,3}[0-9]{3,4}[A-Z]{0,2})$"
)


def normalizar_matricula(texto: str) -> str:
    """Mayúsculas y sólo alfanuméricos (igual que el alta manual)."""
    return "".join(ch for ch in texto.upper() if ch.isalnum())


def parece_matricula(texto: str) -> bool:
    """¿El texto leído por el OCR puede ser una matrícula?

    >>> parece_matricula("1234ABC")
    True
    >>> parece_matricula("E1234")
    True
    >>> parece_matricula("t=105.0sframe=2625")
    False
    >>> parece_matricula("CAM 01")
    False
    """
    return bool(PATRON_MATRICULA.match(normalizar_matricula(texto)))
