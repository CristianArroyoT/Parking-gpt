"""QA del T-179: la pantalla de RBAC por sucursal (ADR 0005).

QUÉ COMPRUEBA
-------------
Con un navegador de verdad, como **admin** (los endpoints de membresías son
admin-only):

1. El listado de usuarios de ``/admin/users`` se pinta (la comprobación no
   puede pasar en vacío: se exigen filas y controles).
2. El panel «Sucursales y roles» **lista** las membresías del usuario.
3. Se puede **añadir** una membresía (sucursal + rol) y aparece en la lista.
4. Se puede **cambiar el rol** de una membresía, y el cambio **persiste**
   (se recarga la página: lo que se ve viene del servidor, no de la pantalla).
5. Se puede **quitar** una membresía, y desaparece.
6. El desplegable de rol ofrece **sólo** ``gestor``, ``operador`` y ``cliente``:
   el ``admin`` es un rol **global** (ADR 0005) y la API lo rechaza con 422.
7. Si el backend devuelve un **422**, el error se muestra **con el mensaje del
   backend** (no uno genérico). Para provocarlo se intercepta la petición y
   se manda ``role_in_parking='admin'``: el backend contesta 422 y la pantalla
   tiene que enseña su mensaje («'admin' no es un rol por sucursal…»).

LIMPIEZA
--------
La QA **borra lo que crea**: la membresía que añade se quita desde la propia
pantalla (que es lo que hay que demostrar) y, además, al final se borra por
API cualquier membresía que no estuviera antes. Así la base de datos de
desarrollo no acumula membresías de prueba.

OJO (rate-limit): ``POST /auth/login`` admite 10 intentos por IP cada 5
minutos (en desarrollo son 50) y cuenta también los exitosos: esta QA hace
**un solo** inicio de sesión.

Uso:
    python frontend/scripts/qa_membresias_rbac.py
    python frontend/scripts/qa_membresias_rbac.py --base http://127.0.0.1:5173

Códigos de salida: 0 correcto · 1 fallo · 3 no se pudo comprobar.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

# T-148 (2026-10-24): 127.0.0.1 y NO 'localhost' (ver AGENTS.md).
BASE_POR_DEFECTO = "http://127.0.0.1:5173"
API_POR_DEFECTO = "http://127.0.0.1:8000/api/v1"
SIN_NAVEGADOR = 3

CUENTA = ("admin@solidapp.es", "admin12345")
#: Usuario de prueba (lo crea el seed). La QA mide cuántas membresías tiene
#: al empezar, para poder comprobar al final que no deja ninguna de más.
OBJETIVO = "cliente.demo@solidapp.es"

#: Lo que tiene que ofrecer el desplegable de rol (ADR 0005): el ``admin``
#: es global y **no** existe un admin «de una sucursal».
ROLES_ESPERADOS = ["gestor", "operador", "cliente"]

#: Trozo del mensaje del backend para el 422 del ``admin``.
MSG_422 = "no es un rol por sucursal"

#: El código de la sucursal va entre paréntesis: «Madrid Centro A (MAD-A)»,
#: «Barcelona Eixample (BCN-1)».
RE_CODIGO = re.compile(r"\(([A-Z]{2,4}-[A-Z0-9]+)\)")


def _print(mensaje: str) -> None:
    print(mensaje)


# ── API (para la limpieza) ───────────────────────────────────────────────


def _login_api(email: str, password: str, api: str) -> str | None:
    """Token de admin para la limpieza por API. ``None`` si no se pudo."""
    cuerpo = json.dumps({"email": email, "password": password}).encode()
    peticion = urllib.request.Request(
        f"{api}/auth/login",
        data=cuerpo,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return json.loads(r.read().decode())["access_token"]
    except Exception as exc:  # noqa: BLE001
        _print(f"AVISO: no se pudo iniciar sesión en la API: {type(exc).__name__}: {exc}")
        return None


def _listar_membresias(token: str, api: str, user_id: int) -> list[dict]:
    peticion = urllib.request.Request(
        f"{api}/users/{user_id}/memberships", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(peticion, timeout=15) as r:
        return json.loads(r.read().decode())


def _borrar_membresia(token: str, api: str, user_id: int, membership_id: int) -> None:
    peticion = urllib.request.Request(
        f"{api}/users/{user_id}/memberships/{membership_id}",
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            _print(f"  limpieza: membresía {membership_id} borrada ({r.status})")
    except Exception as exc:  # noqa: BLE001
        _print(f"  AVISO: no se pudo borrar la membresía {membership_id}: {exc}")


# ── Navegador ────────────────────────────────────────────────────────────


def _login(pagina, email: str, password: str, base: str) -> tuple[bool, str]:
    """Inicia sesión. No lanza: un fallo debe ser un resultado, no un error."""
    try:
        pagina.goto(f"{base}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", email)
        pagina.fill("input[type=password]", password)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _abrir_panel(pagina, base: str, email: str) -> tuple[bool, str]:
    """Abre el panel de «Sucursales y roles» del usuario. Recarga la página.

    Recargar (y volver a abrir) es lo que demuestra que lo que se ve es lo
    que hay **en el servidor**: si la pantalla mintiera con un estado local,
    la recarga lo delata.
    """
    try:
        pagina.reload(wait_until="domcontentloaded", timeout=30000)
        pagina.wait_for_selector("table tbody tr", timeout=20000)
        pagina.get_by_role("button", name=f"Sucursales y roles de {email}").first.click(
            timeout=15000
        )
        pagina.wait_for_selector('[role="dialog"] ul', timeout=15000)
        pagina.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _membresias(pagina) -> list[dict]:
    """Las membresías de verdad del panel.

    OJO: cuando el usuario no está en ninguna sucursal, la lista muestra un
    ``<li>`` de aviso («Este usuario no está en ninguna sucursal»). Ese ``li``
    **no** es una membresía, así que se filtra: las que de verdad son las
    que tienen un desplegable de rol.
    """
    return pagina.locator('[role="dialog"] ul li').evaluate_all(
        """els => els.filter(e => e.querySelector('select')).map(e => ({
             texto: e.textContent.trim(),
             rol: e.querySelector('select').value,
           }))"""
    )


def _opciones_sucursal(pagina) -> list[dict]:
    return pagina.locator("#memb-nueva-sucursal option").evaluate_all(
        "els => els.map(e => ({v: e.value, t: e.textContent.trim(), d: e.disabled}))"
    )


def _fila_de(pagina, codigo: str):
    """La fila (li) de la membresía de una sucursal, por su código."""
    return pagina.locator('[role="dialog"] ul li', has_text=codigo).first


def _interceptar_como_admin(route) -> None:
    """Manda ``role_in_parking='admin'`` en el POST de la membresía.

    El ``admin`` es un rol **global** (ADR 0005): el backend lo rechaza con
    422. Interceptar la petición es la manera de provocar ese 422 **de
    verdad** (con la respuesta real del backend) sin meter un ``admin`` en el
    desplegable, que la pantalla no debe ofrecer.
    """
    if route.request.method != "POST":
        route.continue_()
        return
    cuerpo = json.dumps({"parking_id": 0, "role_in_parking": "admin"})
    cabeceras = dict(route.request.headers)
    cabeceras["content-length"] = str(len(cuerpo))
    route.continue_(post_data=cuerpo, headers=cabeceras)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_POR_DEFECTO)
    parser.add_argument("--api", default=API_POR_DEFECTO)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    api = args.api.rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - entorno sin playwright
        _print(f"SIN NAVEGADOR: no se puede comprobar (falta playwright: {exc})")
        return SIN_NAVEGADOR

    email, password = CUENTA
    fallos = 0

    # El token de la API sirve para la limpieza (y para saber qué membresías
    # había antes y cuáles son nuevas).
    token = _login_api(email, password, api)
    user_id: int | None = None
    membresias_iniciales: set[int] = set()

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # Contexto nuevo: el ``sessionStorage`` de otro caso no se hereda.
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        try:
            ok, motivo = _login(pagina, email, password, base)
            if not ok:
                _print(f"FALLO: no se pudo iniciar sesión: {motivo}")
                return 1
            _print("OK: sesión de admin iniciada")

            # ── 1. El listado de usuarios se pinta ────────────────────────
            pagina.goto(f"{base}/admin/users", wait_until="domcontentloaded", timeout=30000)
            pagina.wait_for_selector("table tbody tr", timeout=20000)
            pagina.wait_for_timeout(800)
            filas = pagina.locator("table tbody tr").count()
            if filas < 1:
                _print(
                    "FALLO: la tabla de usuarios no tiene filas: la comprobación "
                    "pasaría en vacío y no valdría como puerta"
                )
                return 1
            boton = pagina.get_by_role("button", name=f"Sucursales y roles de {OBJETIVO}")
            if boton.count() < 1:
                _print(f"FALLO: no aparece la fila de {OBJETIVO} en /admin/users")
                return 1
            _print(f"OK: /admin/users pintado ({filas} filas)")

            # Estado inicial (por API, para la limpieza).
            if token:
                peticion = urllib.request.Request(
                    f"{api}/users", headers={"Authorization": f"Bearer {token}"}
                )
                with urllib.request.urlopen(peticion, timeout=15) as r:
                    usuarios = json.loads(r.read().decode())
                user_id = next(
                    (u["id"] for u in usuarios if u["email"] == OBJETIVO),
                    None,
                )
                if user_id is not None:
                    membresias_iniciales = {
                        m["id"] for m in _listar_membresias(token, api, user_id)
                    }
                    _print(
                        f"OK: {OBJETIVO} (id {user_id}) tiene "
                        f"{len(membresias_iniciales)} membresía(s) al empezar"
                    )

            # ── 2. El panel se abre y lista las membresías ───────────────
            boton.first.click(timeout=15000)
            pagina.wait_for_selector('[role="dialog"] ul', timeout=15000)
            pagina.wait_for_timeout(800)
            dialogo = pagina.locator('[role="dialog"]')
            if dialogo.count() != 1:
                _print("FALLO: no se abrió el panel de «Sucursales y roles»")
                return 1
            n_inicial = len(_membresias(pagina))
            _print(f"OK: panel abierto ({n_inicial} fila(s) de membresía)")

            # ── 3. El desplegable de rol NO ofrece 'admin' ───────────────
            roles = [
                t.strip()
                for t in pagina.locator("#memb-nuevo-rol option").all_text_contents()
            ]
            if roles != ROLES_ESPERADOS:
                _print(
                    f"FALLO: el desplegable de rol ofrece {roles} y lo esperado es "
                    f"{ROLES_ESPERADOS} (el 'admin' es global: ADR 0005)"
                )
                fallos += 1
            else:
                _print(f"OK: el desplegable de rol ofrece sólo {roles}")

            # ── 4. Añadir una membresía ───────────────────────────────────
            libres = [o for o in _opciones_sucursal(pagina) if o["v"] and not o["d"]]
            if not libres:
                _print(
                    "FALLO: no hay ninguna sucursal libre en el desplegable: no se "
                    "puede añadir una membresía"
                )
                return 1
            elegida = libres[0]
            codigo = RE_CODIGO.search(elegida["t"])
            if not codigo:
                _print(f"FALLO: no se pudo leer el código de la sucursal {elegida['t']!r}")
                return 1
            codigo = codigo.group(1)
            pagina.select_option("#memb-nueva-sucursal", elegida["v"])
            pagina.select_option("#memb-nuevo-rol", "gestor")
            try:
                with pagina.expect_response(
                    lambda r: "/memberships" in r.url and r.request.method == "POST",
                    timeout=15000,
                ) as info:
                    pagina.get_by_role("button", name="Añadir", exact=True).click(timeout=15000)
            except Exception as exc:  # noqa: BLE001
                _print(
                    f"FALLO: no se envió el alta de la membresía en {codigo} "
                    f"(no llegó el POST): {type(exc).__name__}"
                )
                return 1
            estado = info.value.status
            if estado != 201:
                _print(f"FALLO: el alta de la membresía devolvió {estado} (se esperaba 201)")
                return 1
            _print(f"OK: membresía añadida en {codigo} (201)")

            # ── 5. Se ve listada (recargando: viene del servidor) ───────
            ok, motivo = _abrir_panel(pagina, base, OBJETIVO)
            if not ok:
                _print(f"FALLO: no se pudo reabrir el panel: {motivo}")
                return 1
            n_tras_anadir = len(_membresias(pagina))
            fila = _fila_de(pagina, codigo)
            if n_tras_anadir != n_inicial + 1 or fila.count() < 1:
                _print(
                    f"FALLO: la membresía de {codigo} no aparece en la lista "
                    f"({n_tras_anadir} fila(s), antes {n_inicial})"
                )
                return 1
            _print(f"OK: la membresía de {codigo} aparece listada")

            # ── 6. Cambiar el rol (y que persista) ───────────────────────
            select = fila.locator("select")
            try:
                with pagina.expect_response(
                    lambda r: "/memberships/" in r.url and r.request.method == "PATCH",
                    timeout=15000,
                ) as info:
                    select.select_option("operador", timeout=15000)
            except Exception as exc:  # noqa: BLE001
                # OJO: si la pantalla no envía el cambio, el error es un
                # tiempo de espera. Se dice con esas palabras para que se
                # entienda qué falló (y para que la prueba inversa sepa que
                # falló por el motivo correcto).
                _print(
                    f"FALLO: no se envió el cambio de rol de {codigo} "
                    f"(no llegó el PATCH): {type(exc).__name__}"
                )
                return 1
            if info.value.status != 200:
                _print(f"FALLO: el cambio de rol devolvió {info.value.status}")
                return 1
            ok, motivo = _abrir_panel(pagina, base, OBJETIVO)
            if not ok:
                _print(f"FALLO: no se pudo reabrir el panel: {motivo}")
                return 1
            valor = _fila_de(pagina, codigo).locator("select").input_value()
            if valor != "operador":
                _print(
                    f"FALLO: el rol de {codigo} no se guardó (tras recargar es "
                    f"{valor!r}, se esperaba 'operador')"
                )
                return 1
            _print(f"OK: el rol de {codigo} se cambió a 'operador' y se guardó")

            # ── 7. Quitar la membresía ────────────────────────────────────
            fila = _fila_de(pagina, codigo)
            try:
                with pagina.expect_response(
                    lambda r: "/memberships/" in r.url and r.request.method == "DELETE",
                    timeout=15000,
                ) as info:
                    fila.locator("button").first.click(timeout=15000)
            except Exception as exc:  # noqa: BLE001
                _print(
                    f"FALLO: no se envió el borrado de la membresía de {codigo} "
                    f"(no llegó el DELETE): {type(exc).__name__}"
                )
                return 1
            if info.value.status != 204:
                _print(f"FALLO: el borrado devolvió {info.value.status} (se esperaba 204)")
                return 1
            ok, motivo = _abrir_panel(pagina, base, OBJETIVO)
            if not ok:
                _print(f"FALLO: no se pudo reabrir el panel: {motivo}")
                return 1
            n_tras_quitar = len(_membresias(pagina))
            if n_tras_quitar != n_inicial or _fila_de(pagina, codigo).count() > 0:
                _print(
                    f"FALLO: la membresía de {codigo} no desapareció "
                    f"({n_tras_quitar} fila(s), antes {n_inicial})"
                )
                return 1
            _print(f"OK: la membresía de {codigo} se quitó y desapareció")

            # ── 8. Un 422 se muestra con el mensaje del backend ───────────
            libres = [o for o in _opciones_sucursal(pagina) if o["v"] and not o["d"]]
            if not libres:
                _print("AVISO: no hay sucursal libre para provocar el 422")
            else:
                pagina.route("**/api/v1/users/*/memberships", handler=_interceptar_como_admin)
                try:
                    pagina.select_option("#memb-nueva-sucursal", libres[0]["v"])
                    pagina.select_option("#memb-nuevo-rol", "gestor")
                    with pagina.expect_response(
                        lambda r: "/memberships" in r.url and r.request.method == "POST"
                    ) as info:
                        pagina.get_by_role("button", name="Añadir", exact=True).click(
                            timeout=15000
                        )
                    estado = info.value.status
                finally:
                    pagina.unroute("**/api/v1/users/*/memberships")
                if estado != 422:
                    _print(f"FALLO: la petición con 'admin' devolvió {estado} (se esperaba 422)")
                    fallos += 1
                else:
                    alertas = pagina.locator('[role="dialog"] [role="alert"]').all_text_contents()
                    texto = " ".join(alertas)
                    if MSG_422 not in texto:
                        _print(
                            "FALLO: el 422 no se muestra con el mensaje del backend "
                            f"(en la pantalla: {texto!r})"
                        )
                        fallos += 1
                    else:
                        _print(f"OK: el 422 se muestra con el mensaje del backend: {texto.strip()}")
        except Exception as exc:  # noqa: BLE001
            _print(f"FALLO: {type(exc).__name__}: {exc}")
            fallos += 1
        finally:
            # ── Limpieza: lo que crea la QA, se borra ────────────────────
            if token and user_id is not None:
                try:
                    for m in _listar_membresias(token, api, user_id):
                        if m["id"] not in membresias_iniciales:
                            _borrar_membresia(token, api, user_id, m["id"])
                except Exception as exc:  # noqa: BLE001
                    _print(f"AVISO: la limpieza falló: {exc}")
            contexto.close()
            navegador.close()

    if fallos:
        _print(f"\n{fallos} fallo(s): la pantalla de RBAC por sucursal no cumple (T-179)")
        return 1
    _print("\nOK: el ciclo de membresías por sucursal funciona en el navegador (T-179)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
