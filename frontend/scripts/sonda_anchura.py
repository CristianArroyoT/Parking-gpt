"""Sonda: mide la cadena de anchuras de una pantalla a un ancho dado.

Se usa para localizar de dónde sale un desbordamiento horizontal: recorre
la cadena de ancestros del elemento mas ancho y dice, en cada escalon, su
``min-width`` calculado, su ``overflow-x`` y si es un contenedor flexible
o de rejilla. Sirve para no adivinar qué clase hay que tocar.

Uso: python frontend/scripts/sonda_anchura.py --ruta /gestor/operadores --ancho 414
"""
from __future__ import annotations

import argparse
import json

from playwright.sync_api import sync_playwright

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost' (el IPv6 ::1 no
# lo sirve el dev-server de Vite).
BASE = "http://127.0.0.1:5173"
CUENTAS = {
    "admin": ("admin@solidapp.es", "admin12345"),
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
    "cliente": ("cliente.demo@solidapp.es", "cliente1234"),
}

JS = """
() => {
  const padre = (el) => el.parentElement;
  // El elemento mas ancho que no sea un descendiente de un contenedor
  // con scroll propio.
  const ancho = (el) => el.getBoundingClientRect().width;
  const todos = Array.from(document.querySelectorAll('body *'));
  const anchos = todos.filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > window.innerWidth + 1 && r.height > 0;
  });
  if (!anchos.length) return {mensaje: 'nada que pase del ancho de la ventana'};
  const peor = anchos.sort((a, b) => ancho(b) - ancho(a))[0];
  const cadena = [];
  let el = peor;
  while (el && el !== document.documentElement) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    cadena.push({
      etiqueta: el.tagName.toLowerCase() +
        (typeof el.className === 'string' && el.className
          ? '.' + el.className.trim().split(/\\s+/).slice(0, 4).join('.') : ''),
      texto: (el.innerText || '').trim().split('\\n')[0].slice(0, 40),
      ancho: Math.round(r.width),
      minWidth: cs.minWidth,
      width: cs.width,
      overflowX: cs.overflowX,
      display: cs.display,
      minContent: cs.minContentWidth,
    });
    el = padre(el);
  }
  return {cadena};
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruta", default="/gestor/operadores")
    ap.add_argument("--rol", default="gestor", choices=list(CUENTAS))
    ap.add_argument("--ancho", type=int, default=414)
    args = ap.parse_args()

    email, password = CUENTAS[args.rol]
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(viewport={"width": args.ancho, "height": 900})
        pagina = contexto.new_page()
        pagina.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", email)
        pagina.fill("input[type=password]", password)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        pagina.goto(f"{BASE}{args.ruta}", wait_until="domcontentloaded", timeout=25000)
        pagina.wait_for_timeout(1500)
        resultado = pagina.evaluate(JS)
        navegador.close()

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
