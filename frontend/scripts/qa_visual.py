"""QA visual de las pantallas de solidAPP con Chromium headless (Playwright).

Recorre las pantallas del frontend real (Vite en :5173) con las cuentas
**demo** del seed, y para cada una:

- hace una captura de pantalla,
- recoge los **errores de consola**,
- recoge las **peticiones de red que fallan** (4xx/5xx),
- y anota si la pantalla se queda en blanco o en carga infinita.

Sirve para lo que los tests no cubren: que la pantalla **se renderice**.

Uso:
    python qa_visual.py --salida D:\\tmp\\qa-solidapp
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:5173"

# (etiqueta, ruta, rol, nombre de fichero)
PANTALLAS = [
    ("login", "/login", "ninguno", "login"),
    ("recuperar-sin-token", "/recuperar-contrasena", "ninguno", "recuperar-sin-token"),
    ("recuperar-con-token", "/recuperar-contrasena?token=abc123", "ninguno", "recuperar-con-token"),
    ("gestor-dashboard", "/dashboard/gestor", "gestor", "gestor-dashboard"),
    ("gestor-movimientos", "/gestor/movimientos", "gestor", "gestor-movimientos"),
    ("gestor-alertas", "/gestor/alertas", "gestor", "gestor-alertas"),
    ("gestor-operadores", "/gestor/operadores", "gestor", "gestor-operadores"),
    ("gestor-mapa", "/mapa", "gestor", "gestor-mapa"),
    ("gestor-camaras", "/cameras", "gestor", "gestor-camaras"),
    ("operador-vivo", "/vivo", "gestor", "operador-vivo"),
    ("operador-alta", "/operador/alta-manual", "gestor", "operador-alta"),
    ("cliente-tickets", "/mis-tickets", "cliente", "cliente-tickets"),
    ("cliente-vehiculos", "/mis-vehiculos", "cliente", "cliente-vehiculos"),
    ("cliente-perfil", "/mi-perfil", "cliente", "cliente-perfil"),
    ("cliente-plan", "/mi-plan", "cliente", "cliente-plan"),
    ("cliente-plaza", "/mi-plaza", "cliente", "cliente-plaza"),
    ("cliente-pagos", "/pagos", "cliente", "cliente-pagos"),
    ("admin-planes", "/admin/planes", "admin", "admin-planes"),
    ("admin-usuarios", "/admin/users", "admin", "admin-usuarios"),
    ("admin-tarifas", "/admin/tariffs", "admin", "admin-tarifas"),
    ("admin-reportes", "/admin/reports", "admin", "admin-reportes"),
]

CUENTAS = {
    "admin": ("admin@solidapp.es", "admin12345"),
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
    "cliente": ("cliente.demo@solidapp.es", "cliente1234"),
}


@dataclass
class Resultado:
    etiqueta: str
    ruta: str
    url_final: str
    consola: list[str] = field(default_factory=list)
    red: list[str] = field(default_factory=list)
    texto: str = ""
    vacia: bool = False
    captura: str = ""


def _login(page: Page, email: str, password: str) -> bool:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", password)
    page.click("button[type=submit]")
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    except Exception:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="D:/tmp/qa-solidapp")
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    resultados: list[Resultado] = []
    errores_login: list[str] = []

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)

        # Las pantallas públicas (login, recuperación de contraseña) se
        # capturan en su propio contexto, SIN sesión: si se visitaran
        # después de iniciar sesión, el guard de ruta las redirigiría.
        contexto_publico = navegador.new_context(viewport={"width": 1440, "height": 900})
        pagina_publica = contexto_publico.new_page()
        for etiqueta, ruta, rol_needed, nombre in PANTALLAS:
            if rol_needed != "ninguno":
                continue
            consola: list[str] = []
            red: list[str] = []
            pagina_publica.on("console", lambda m: consola.append(f"{m.type}: {m.text}")
                              if m.type in ("error", "warning") else None)
            pagina_publica.on("response", lambda r: red.append(
                f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
            try:
                pagina_publica.goto(f"{BASE}{ruta}", wait_until="networkidle", timeout=25000)
            except Exception as exc:
                red.append(f"navegacion: {type(exc).__name__}: {exc}")
            pagina_publica.wait_for_timeout(700)
            texto = pagina_publica.inner_text("body")[:400].strip()
            vacia = len(texto) < 40
            captura = salida / f"{nombre}.png"
            try:
                pagina_publica.screenshot(path=str(captura), full_page=True)
            except Exception as exc:
                consola.append(f"captura: {type(exc).__name__}")
            resultados.append(
                Resultado(
                    etiqueta=etiqueta,
                    ruta=ruta,
                    url_final=pagina_publica.url,
                    consola=consola[:6],
                    red=red[:6],
                    texto=texto,
                    vacia=vacia,
                    captura=str(captura),
                )
            )
        contexto_publico.close()

        for rol in ("gestor", "cliente", "admin"):
            contexto = navegador.new_context(viewport={"width": 1440, "height": 900})
            pagina = contexto.new_page()
            email, password = CUENTAS[rol]
            if not _login(pagina, email, password):
                errores_login.append(f"{rol}: no se pudo iniciar sesión")
                contexto.close()
                continue

            for etiqueta, ruta, rol_needed, nombre in PANTALLAS:
                if rol_needed not in (rol, "ninguno"):
                    continue
                if rol_needed == "ninguno":
                    continue
                consola: list[str] = []
                red: list[str] = []
                pagina.on("console", lambda m: consola.append(f"{m.type}: {m.text}")
                          if m.type in ("error", "warning") else None)
                pagina.on("response", lambda r: red.append(
                    f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
                try:
                    pagina.goto(f"{BASE}{ruta}", wait_until="networkidle", timeout=25000)
                except Exception as exc:
                    red.append(f"navegacion: {type(exc).__name__}: {exc}")
                pagina.wait_for_timeout(700)
                texto = pagina.inner_text("body")[:400].strip()
                vacia = len(texto) < 40
                captura = salida / f"{nombre}.png"
                try:
                    pagina.screenshot(path=str(captura), full_page=True)
                except Exception as exc:
                    consola.append(f"captura: {type(exc).__name__}")
                resultados.append(
                    Resultado(
                        etiqueta=etiqueta,
                        ruta=ruta,
                        url_final=pagina.url,
                        consola=consola[:6],
                        red=red[:6],
                        texto=texto,
                        vacia=vacia,
                        captura=str(captura),
                    )
                )
                pagina.remove_listener("console", pagina.listeners("console")[-1]) if False else None
            contexto.close()
        navegador.close()

    informe = {
        "errores_login": errores_login,
        "pantallas": [r.__dict__ for r in resultados],
    }
    (salida / "informe.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'pantalla':<24} {'vacia':<6} consola/red")
    for r in resultados:
        marca = "SI" if r.vacia else "no"
        print(f"{r.etiqueta:<24} {marca:<6} {len(r.consola)}/{len(r.red)}")
        for c in r.consola:
            print(f"    consola: {c[:160]}")
        for n in r.red:
            print(f"    red    : {n[:160]}")
    if errores_login:
        print("ERRORES DE LOGIN:", errores_login)
    print(f"\nCapturas e informe en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
