"""QA: un gestor sin sucursales ve un mensaje, no «Cargando…» para siempre.

POR QUÉ ESTA QA (T-138, 2026-10-24)
--------------------------------------
En ``MovementsView`` y ``AlertsView`` la carga tiene un ``return``
temprano cuando no hay sucursal seleccionada, y ese ``return`` no bajaba
el flag ``loading``: un gestor **sin sucursales** (o con la carga de
sucursales fallida) se quedaba mirando «Cargando…» para siempre, sin
ninguna pista de que faltara una sucursal.

Esta QA lo comprueba con un navegador de verdad:

1. el admin crea un gestor **sin membresías**;
2. se entra con ese gestor;
3. en «movimientos» y en «alertas» **no** puede quedar «Cargando…»:
   tiene que verse un mensaje que explique que no hay sucursal.

Uso:
    python frontend/scripts/qa_gestor_sin_sucursal.py
    python frontend/scripts/qa_gestor_sin_sucursal.py --base http://localhost:4173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE_POR_DEFECTO = "http://localhost:5173"
API = "/api/v1"
SIN_NAVEGADOR = 3
ADMIN = ("admin@solidapp.es", "admin12345")

try:
    from playwright.sync_api import sync_playwright

    HAY_PLAYWRIGHT = True
except ImportError as _error:  # pragma: no cover - entorno sin playwright
    sync_playwright = None  # type: ignore[assignment]
    HAY_PLAYWRIGHT = False
    _MOTIVO_IMPORT = str(_error)
else:
    _MOTIVO_IMPORT = ""


def _api(
    base: str, method: str, path: str, token: str | None = None, body: dict | None = None
) -> tuple[int, str]:
    url = f"{base}{API}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def _login(base: str, email: str, password: str) -> str | None:
    codigo, cuerpo = _api(base, "POST", "/auth/login", body={"email": email, "password": password})
    if codigo != 200:
        print(f"  login {email} -> [{codigo}] {cuerpo[:120]}")
        return None
    return json.loads(cuerpo)["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not HAY_PLAYWRIGHT:
        print(
            "SIN NAVEGADOR: no se puede comprobar (_MOTIVO: "
            f"{_MOTIVO_IMPORT})"
        )
        return SIN_NAVEGADOR

    # 1) Un gestor SIN membresías, con un correo único.
    admin = _login(base, *ADMIN)
    if not admin:
        print("FALLO: no se pudo iniciar sesion como admin")
        return 1
    correo = f"gestor-sin-sucursal-{uuid.uuid4().hex[:8]}@solidapp.es"
    codigo, cuerpo = _api(
        base,
        "POST",
        "/users",
        token=admin,
        body={
            "email": correo,
            "full_name": "Gestor Sin Sucursal",
            "role": "gestor",
            "password": "GestorSinSucursal1",
        },
    )
    if codigo != 201:
        print(f"FALLO: no se pudo crear el gestor sin sucursales -> [{codigo}] {cuerpo[:200]}")
        return 1
    usuario_id = json.loads(cuerpo)["id"]

    try:
        # 2) Entrar con ese gestor.
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page()
            try:
                pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
                pagina.fill("input[type=email]", correo)
                pagina.fill("input[type=password]", "GestorSinSucursal1")
                pagina.click("button[type=submit]")
                pagina.wait_for_url(lambda u: "/login" not in u, timeout=15000)

                fallos: list[str] = []
                for etiqueta, ruta in (
                    ("movimientos", "/gestor/movimientos"),
                    ("alertas", "/gestor/alertas"),
                ):
                    try:
                        pagina.goto(
                            f"{base}{ruta}", wait_until="domcontentloaded", timeout=30000
                        )
                        pagina.wait_for_timeout(1500)
                        texto = pagina.inner_text("body")
                    except Exception as exc:  # noqa: BLE001
                        # El entorno puede ir lento: se reporta como
                        # fallo de la comprobacion, no como excepcion.
                        fallos.append(
                            f"{etiqueta}: no se pudo cargar la pantalla "
                            f"({type(exc).__name__}: {exc})"
                        )
                        continue
                    if "Cargando…" in texto:
                        fallos.append(f"{etiqueta}: sigue en «Cargando…»")
                    elif "No tienes ninguna sucursal asignada" not in texto:
                        fallos.append(
                            f"{etiqueta}: no explica que no hay ninguna "
                            f"sucursal asignada (texto: {texto[:120]!r})"
                        )
                    elif "No hay movimientos" in texto or "No hay alertas" in texto:
                        fallos.append(
                            f"{etiqueta}: además afirma que no hay datos, "
                            f"que es falso (lo que no hay es la sucursal)"
                        )
                    else:
                        print(f"  OK {etiqueta}: {texto.strip()[:90]!r}")

                if fallos:
                    print("\nFALLO:")
                    for fallo in fallos:
                        print(f"  - {fallo}")
                    return 1
                print("OK: el gestor sin sucursales ve un mensaje (no «Cargando…»).")
                return 0
            finally:
                navegador.close()
    finally:
        # Limpieza: el usuario de prueba no se queda en la base.
        codigo, _cuerpo = _api(base, "DELETE", f"/users/{usuario_id}", token=admin)
        print(f"  (usuario de prueba borrado: [{codigo}])")


if __name__ == "__main__":
    sys.exit(main())
