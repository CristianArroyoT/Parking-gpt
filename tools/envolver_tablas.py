"""Envuelve las tablas de las vistas en un contenedor desplazable.

POR QUÉ (2026-10-21): a 414 px (movil) la pagina entera se deslizaba
lateralmente en varias pantallas. La causa no era solo que la tabla no
cabe: es que un ``<table>`` no baja del ancho de su contenido, y dentro
de un contenedor con ``display: grid`` o ``flex`` el ancho minimo por
defecto (``min-width: auto``) impide que el envoltorio encoja.

El arreglo tiene dos partes y hacen falta las dos:

  1. Envolver la tabla en un ``div`` con ``overflow-x-auto`` (para que la
     tabla se pueda desplazar dentro de su tarjeta).
  2. Poner ``min-w-0`` en ese envoltorio (para que el contenedor grid o
     flex le permita encogerse por debajo del ancho de la tabla). Sin
     esto, el envoltorio sigue midiendo lo que mide la tabla y la
     pagina sigue desbordando.

Al envolver la tabla hay que cuidar dos detalles de Vue:

  * Si la tabla lleva ``v-if`` / ``v-else`` / ``v-else-if``, la directiva
    se muda al envoltorio. Si se deja en la tabla, Vue se queja de que
    no tiene un ``v-if`` o ``v-else`` anterior al que enlazarse
    (``v-else`` sin pareja) y la vista no compila.
  * ``min-w-max`` se añade DENTRO del atributo ``class`` de la tabla, no
    como un atributo suelto: ``<table class="w-full" min-w-max>`` no
    significa nada para el navegador.

Uso: python tools/envolver_tablas.py
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VISTAS = RAIZ / "frontend" / "src" / "views"

#: Bloque de tabla: desde la etiqueta de apertura hasta el </table>.
RE_TABLA = re.compile(
    r"^(?P<indent>[ ]*)<table(?P<attrs>[^>]*)>\n"
    r"(?P<cuerpo>.*?)"
    r"^(?P=indent)</table>\n",
    re.DOTALL | re.MULTILINE,
)

#: Envoltorio desplazable existente. Se admiten otros atributos antes de
#: ``class`` (``v-else``, ``v-if``...) porque hay varios en el codigo.
RE_ENVUELTO = re.compile(
    r'<div(?P<otros>[^>]*?)class="(?P<clase>overflow-x-auto[^"]*)"'
)

#: Directiva condicional de Vue sobre un elemento. ``v-else`` no lleva
#: valor, asi que el ``="..."`` es opcional.
RE_DIRECTIVA = re.compile(r'\s+v-(?:if|else-if|else)(?:="[^"]*")?')

#: Atributo ``class`` de un elemento.
RE_CLASS = re.compile(r'class="(?P<valor>[^"]*)"')


def _anadir_min_w0(m: re.Match) -> str:
    """Añade ``min-w-0`` al envoltorio desplazable si no lo tiene."""
    clase = m.group("clase")
    if "min-w-0" in clase:
        return m.group(0)
    return f'<div{m.group("otros")}class="{clase} min-w-0"'


def _preparar_attrs(attrs: str) -> tuple[str, str]:
    """Separa la directiva condicional y asegura ``min-w-max``.

    Devuelve (directiva, atributos). La directiva va vacía si la tabla
    no tenía ninguna.
    """
    directiva = ""
    m = RE_DIRECTIVA.search(attrs)
    if m:
        directiva = m.group(0).strip()
        attrs = attrs[: m.start()] + attrs[m.end():]

    mc = RE_CLASS.search(attrs)
    if mc:
        valor = mc.group("valor")
        if "min-w-max" not in valor:
            attrs = attrs[: mc.start("valor")] + f"{valor} min-w-max" + attrs[mc.end("valor"):]
    else:
        attrs = attrs.rstrip() + ' class="min-w-max"'
    return directiva, attrs


def _envolver(texto: str) -> tuple[str, int]:
    """Envuelve las tablas que no lo están ya. Devuelve (texto, n)."""
    n = 0

    def _sustituir(m: re.Match) -> str:
        nonlocal n
        indent = m.group("indent")
        cuerpo = m.group("cuerpo")
        # Si la tabla ya está dentro de un envoltorio desplazable, no
        # se toca (sólo se le añade el ``min-w-0`` de antes).
        previo = texto[: m.start()].rstrip().rsplit("\n", 1)[-1]
        if "overflow-x-auto" in previo:
            return m.group(0)
        n += 1
        directiva, attrs = _preparar_attrs(m.group("attrs"))
        cuerpo_ind = "\n".join(
            ("  " + linea) if linea.strip() else linea
            for linea in cuerpo.split("\n")
        )
        cond = f" {directiva}" if directiva else ""
        return (
            f'{indent}<div{cond} class="overflow-x-auto min-w-0">\n'
            f"{indent}  <table{attrs}>\n"
            f"{cuerpo_ind}"
            f"{indent}  </table>\n"
            f"{indent}</div>\n"
        )

    return RE_TABLA.sub(_sustituir, texto), n


def main() -> int:
    total = 0
    for fichero in sorted(VISTAS.rglob("*.vue")):
        texto = fichero.read_text(encoding="utf-8")
        # 1) Los envoltorios que ya existen necesitan ``min-w-0``.
        texto2 = RE_ENVUELTO.sub(_anadir_min_w0, texto)
        # 2) Las tablas sueltas se envuelven.
        texto3, n = _envolver(texto2)
        if texto3 != texto:
            fichero.write_text(texto3, encoding="utf-8")
            print(f"{fichero.name}: {n} tabla(s) envuelta(s)")
            total += n
    print(f"\n{total} tabla(s) envuelta(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
