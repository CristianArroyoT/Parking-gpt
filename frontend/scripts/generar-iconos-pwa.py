"""Genera los iconos PNG de la PWA de solidAPP (T-24).

Uso (desde la raíz del repo):

    python frontend/scripts/generar-iconos-pwa.py

Salida (en ``frontend/public/icons/``):

    icon-192.png              icono "any" 192x192 (esquinas redondeadas)
    icon-512.png              icono "any" 512x512 (esquinas redondeadas)
    icon-maskable-512.png     icono "maskable" 512x512 (fondo a sangre,
                              contenido dentro de la zona segura)
    apple-touch-icon-180.png  icono para iOS (cuadrado, sin transparencia)

Por qué un script y no los PNG a mano: los iconos tienen que regenerarse
cuando cambie el color de marca o la geometría del logotipo, y un PNG
editado a mano no deja rastro de cómo se hizo. Además, el SVG de
``frontend/public/icons/icon.svg`` es la fuente de verdad del diseño (el
mismo "P" y el mismo degradado), así que el script y el SVG no pueden
divergir: comparten la geometría descrita abajo.

Diseño (lienzo de 512x512, el mismo del SVG):

    - Fondo: degradado diagonal de #0f172a (park.marca) a #2563eb
      (park.acento), los dos colores de ``tailwind.config.js``.
    - "P" blanca centrada: asta de x=184..240, y=72..420 y un aro
      (media corona) de radio exterior 112 e interior 62 con centro en
      (240, 184).

Requiere Pillow (``pip install Pillow``).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# ── Parámetros del diseño ───────────────────────────────────────────────

LIENZO = 512
COLOR_MARCA = (15, 23, 42)      # #0f172a · slate-900 (park.marca)
COLOR_ACENTO = (37, 99, 235)    # #2563eb · blue-600  (park.acento)
COLOR_TINTA = (255, 255, 255)   # blanco

# Geometría de la "P" (lienzo 512x512).
CX, CY = 240, 184          # centro del aro
R_EXTERIOR, R_INTERIOR = 112, 62
ASTA_X0, ASTA_X1 = 184, 240
ASTA_Y0, ASTA_Y1 = 72, 420

# Supermuestreo: se dibuja a 4x y se reduce con LANCZOS para que los
# bordes salgan suaves (Pillow no antialasea los primitivos).
SUPER = 4

DESTINO = Path(__file__).resolve().parents[1] / "public" / "icons"


def _mascara_p(px: int) -> Image.Image:
    """Máscara (modo L) con la "P" de solidAPP, blanca sobre negro."""
    k = px / LIENZO
    mascara = Image.new("L", (px, px), 0)
    d = ImageDraw.Draw(mascara)

    # Aro exterior (disco completo)…
    d.ellipse(
        [
            (CX - R_EXTERIOR) * k,
            (CY - R_EXTERIOR) * k,
            (CX + R_EXTERIOR) * k,
            (CY + R_EXTERIOR) * k,
        ],
        fill=255,
    )
    # …menos el hueco interior…
    d.ellipse(
        [
            (CX - R_INTERIOR) * k,
            (CY - R_INTERIOR) * k,
            (CX + R_INTERIOR) * k,
            (CY + R_INTERIOR) * k,
        ],
        fill=0,
    )
    # …y menos su mitad izquierda (el aro es la media corona derecha).
    d.rectangle([0, 0, CX * k, px], fill=0)
    # El asta cierra la letra por la izquierda.
    d.rectangle([ASTA_X0 * k, ASTA_Y0 * k, ASTA_X1 * k, ASTA_Y1 * k], fill=255)
    return mascara


def _fondo(px: int, radio: int) -> Image.Image:
    """Degradado diagonal de marca, con esquinas redondeadas si ``radio``."""
    # El degradado se calcula a baja resolución y se amplía: es una rampa
    # suave, así que no se nota el reescalado.
    base = Image.new("RGB", (256, 256))
    d = ImageDraw.Draw(base)
    for i in range(256):
        t = i / 255.0
        color = tuple(
            int(COLOR_MARCA[k] + (COLOR_ACENTO[k] - COLOR_MARCA[k]) * t)
            for k in range(3)
        )
        d.line([(0, i), (255, i)], fill=color)

    fondo = base.resize((px, px), Image.LANCZOS).convert("RGBA")
    if radio > 0:
        mascara = Image.new("L", (px, px), 0)
        ImageDraw.Draw(mascara).rounded_rectangle(
            [0, 0, px - 1, px - 1], radius=int(radio * px / LIENZO), fill=255
        )
        fondo.putalpha(mascara)
    return fondo


def _componer(
    lado: int,
    *,
    escala_contenido: float,
    radio: int,
) -> Image.Image:
    """Compone fondo + "P" centrada en un lienzo ``lado`` x ``lado``."""
    px = lado * SUPER
    fondo = _fondo(px, radio)

    mascara = _mascara_p(px)
    # Recortamos al contenido real de la "P" para poder centrarla.
    caja = mascara.getbbox()
    assert caja is not None
    contenido = mascara.crop(caja)
    ancho, alto = contenido.size
    destino = int(px * escala_contenido)
    escala = min(destino / ancho, destino / alto)
    nuevo = (
        max(1, int(ancho * escala)),
        max(1, int(alto * escala)),
    )
    contenido = contenido.resize(nuevo, Image.LANCZOS)
    fondo.paste(
        Image.new("RGBA", nuevo, COLOR_TINTA),
        ((px - nuevo[0]) // 2, (px - nuevo[1]) // 2),
        contenido,
    )
    return fondo.resize((lado, lado), Image.LANCZOS)


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)

    iconos = {
        # "any": el SO puede recortar; esquinas redondeadas ya de fábrica.
        "icon-192.png": dict(lado=192, escala_contenido=0.86, radio=112),
        "icon-512.png": dict(lado=512, escala_contenido=0.86, radio=112),
        # "maskable": fondo a sangre, contenido dentro de la zona segura
        # (círculo central del 80 %). iOS no aplica máscara: cuadrado.
        "icon-maskable-512.png": dict(lado=512, escala_contenido=0.58, radio=0),
        "apple-touch-icon-180.png": dict(lado=180, escala_contenido=0.78, radio=0),
    }
    for nombre, kwargs in iconos.items():
        imagen = _componer(**kwargs)  # type: ignore[arg-type]
        ruta = DESTINO / nombre
        imagen.save(ruta, "PNG", optimize=True)
        print(f"{ruta} ({ruta.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
