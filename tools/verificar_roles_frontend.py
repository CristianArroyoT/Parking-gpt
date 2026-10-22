"""Comprueba que el guard de rol del frontend no promete más que el backend concede.

POR QUÉ (2026-10-22): el router del frontend protege cada pantalla con
``meta: { roles: [...] }`` y el backend protege cada endpoint con
``require_role(...)``. **Nada comparaba las dos listas.**

El síntoma del desajuste es silencioso y confuso: el router deja entrar
al gestor en una pantalla, la pantalla carga sus datos y el backend
responde **403**. El usuario ve una pantalla rota, no un "no tienes
permisos", porque desde el frontend no parece un problema de permisos:
la ruta existe, el método es el correcto, sólo el rol no encaja.

Esto ya pasó en el lado opuesto (T-35: el inventario de la API decía
"Público" en 9 endpoints de admin). Aquí se comprueba la otra dirección:
que un endpoint **exija** un rol que la pantalla **no** contempla.

Uso:
    python tools/verificar_roles_frontend.py
    python tools/verificar_roles_frontend.py --detalle
    python tools/verificar_roles_frontend.py --autoprueba
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from extraer_api import extraer_de_modulo  # noqa: E402

V1 = RAIZ / "backend" / "app" / "api" / "v1"
SRC = RAIZ / "frontend" / "src"
ROUTER = SRC / "router" / "index.ts"
API = SRC / "api"

#: ``export async function nombre(`` o ``export function nombre(``.
RE_FUNCION = re.compile(
    r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE
)

#: ``http.get('/ruta')`` — con el tipo genérico opcional.
RE_LLAMADA = re.compile(
    r"http\.(get|post|put|patch|delete)\s*(?:<[^;]{0,300}?>)?\s*\(\s*"
    r"[`'\"]\s*([^`'\"]+?)\s*[`'\"]",
    re.DOTALL,
)

#: ``import { a, b, type C } from '@/api/modulo'``.
RE_IMPORT = re.compile(
    r"import\s*\{([^}]*)\}\s*from\s*['\"]@/api/([A-Za-z0-9_]+)['\"]", re.DOTALL
)

#: ``import Algo from '@/views/gestor/Algo.vue'`` — componentes locales.
RE_IMPORT_LOCAL = re.compile(
    r"import\s+[^;]*?\s+from\s*['\"]@/([^'\"]+?)['\"]", re.DOTALL
)

#: ``require_role('admin', 'gestor')`` dentro de la columna "Quién".
RE_REQUIRE_ROLE = re.compile(r"require_role\(\s*((?:'[^']*'\s*,?\s*)+)\)")
RE_ROL = re.compile(r"'([^']+)'")

#: ``${variable}`` y ``{parametro}`` se normalizan a ``{}``.
RE_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")

#: La dependencia ``_gestor_o_admin`` (adjuntos de incidentes) admite
#: exactamente estos dos roles.
ROLES_GESTOR_O_ADMIN = {"admin", "gestor"}


def _forma(ruta: str) -> str:
    """La ruta con los parámetros normalizados a ``{}``.

    La **query string** se quita antes de comparar: ``/alerts?type=x``
    y ``/alerts`` son la misma ruta para el backend (los query params
    no forman parte del camino).
    """
    ruta = ruta.split("?", 1)[0]
    ruta = RE_PLACEHOLDER.sub("{}", ruta)
    return re.sub(r"\{[^}]*\}", "{}", ruta)


def _ruta_del_backend(ruta: str) -> str:
    """La ruta del frontend traducida a la forma que usa el backend.

    El cliente habla en rutas relativas (``/users``) porque axios pone el
    prefijo; el backend las registra con el prefijo puesto
    (``/api/v1/users``). Sin esta traducción, **ninguna** llamada del
    frontend encuentra su endpoint en el backend y la puerta compara
    contra un vacío: sale verde sin haber mirado nada.
    """
    if ruta.startswith("/api/v1"):
        return ruta
    return "/api/v1" + ruta


def _roles_del_backend() -> dict[tuple[str, str], set[str]]:
    """(método, ruta) → roles que el backend exige (vacío = no exige rol)."""
    salida: dict[tuple[str, str], set[str]] = {}
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, quien, _modulo in extraer_de_modulo(fichero):
            roles: set[str] = set()
            for grupo in RE_REQUIRE_ROLE.findall(quien):
                roles.update(RE_ROL.findall(grupo))
            if "_gestor_o_admin" in quien:
                roles |= ROLES_GESTOR_O_ADMIN
            salida[(metodo.upper(), _forma(ruta))] = roles
    return salida


def _funciones_de_modulo(fichero: Path) -> dict[str, list[tuple[str, str]]]:
    """nombre de la función exportada → [(método, ruta)] que llama."""
    texto = fichero.read_text(encoding="utf-8")
    posiciones = [(m.start(), m.group(1)) for m in RE_FUNCION.finditer(texto)]
    resultado: dict[str, list[tuple[str, str]]] = {}
    for indice, (pos, nombre) in enumerate(posiciones):
        fin = posiciones[indice + 1][0] if indice + 1 < len(posiciones) else len(texto)
        cuerpo = texto[pos:fin]
        llamadas = [
            (metodo.upper(), _forma(ruta)) for metodo, ruta in RE_LLAMADA.findall(cuerpo)
        ]
        if llamadas:
            resultado[nombre] = llamadas
    return resultado


def _modulos_del_frontend() -> dict[str, dict[str, list[tuple[str, str]]]]:
    """nombre del módulo → {función: [(método, ruta)]}."""
    modulos: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for fichero in sorted(API.glob("*.ts")):
        modulos[fichero.stem] = _funciones_de_modulo(fichero)
    return modulos


def _rutas_del_router() -> list[tuple[str, str, list[str]]]:
    """(ruta, vista, roles) de cada ruta con guard de rol."""
    texto = ROUTER.read_text(encoding="utf-8")
    salida: list[tuple[str, str, list[str]]] = []
    patron = re.compile(
        r"path:\s*'([^']+)'[\s\S]{0,400}?"
        r"component:\s*\(\)\s*=>\s*import\('@/views/([^']+)'\)[\s\S]{0,200}?"
        r"meta:\s*\{([\s\S]*?)\}",
    )
    for coincidencia in patron.finditer(texto):
        ruta, vista, meta = coincidencia.groups()
        roles = re.findall(r"'([^']+)'", meta.split("roles:")[-1]) if "roles:" in meta else []
        salida.append((ruta, vista, roles))
    return salida


def _imports_de_vista(fichero: Path) -> list[tuple[str, str]]:
    """(módulo, función) que importa la vista de ``@/api/``."""
    texto = fichero.read_text(encoding="utf-8")
    salida: list[tuple[str, str]] = []
    for nombres, modulo in RE_IMPORT.findall(texto):
        for nombre in nombres.split(","):
            limpio = nombre.strip()
            if not limpio or limpio.startswith("type "):
                continue
            limpio = limpio.split(" as ")[0].strip()
            if limpio:
                salida.append((modulo, limpio))
    return salida


def _ficheros_de_la_vista(vista: str) -> list[Path]:
    """El ``.vue`` de la vista y los componentes locales que importa.

    Cierre transitivo: un componente puede importar a otro. Sin esto, un
    ``403`` dentro de un componente se escondería detrás de la pantalla
    que lo usa (y el componente no tiene guard de rol propio).
    """
    inicio = SRC / "views" / vista
    if not inicio.exists():
        return []
    vistos: set[Path] = set()
    pendientes = [inicio]
    while pendientes:
        fichero = pendientes.pop()
        if fichero in vistos or not fichero.exists():
            continue
        vistos.add(fichero)
        texto = fichero.read_text(encoding="utf-8")
        for camino in RE_IMPORT_LOCAL.findall(texto):
            if not camino.endswith(".vue"):
                continue
            pendientes.append(SRC / camino)
    return sorted(vistos)


def _llamadas_directas(fichero: Path) -> list[tuple[str, str]]:
    """(método, ruta) de las llamadas ``http.*`` escritas en el fichero.

    Muchas vistas **no** pasan por los módulos de ``@/api/``: llaman a
    ``http.get(...)`` directamente. Contar sólo los módulos dejaría la
    mitad del cliente fuera del análisis, que es exactamente el modo de
    fallo que esta puerta viene a evitar.
    """
    texto = fichero.read_text(encoding="utf-8")
    return [
        (metodo.upper(), _forma(ruta)) for metodo, ruta in RE_LLAMADA.findall(texto)
    ]


def _desajustes(
    rutas_extra: list[tuple[str, str, list[str]]] | None = None,
) -> tuple[list[tuple[str, str, str, str, str]], int, int]:
    """(desajustes, llamadas analizadas, llamadas resueltas).

    El segundo y el tercero son la **prueba de que la puerta miró
    algo**: si ``resueltas`` es 0, la puerta no ha comparado nada y su
    "verde" no significa nada.

    ``rutas_extra`` permite inyectar rutas de mentira: es lo que usa la
    autoprueba para comprobar, con una vista **real** y un endpoint
    **real**, que la puerta canta un desajuste de verdad.
    """
    roles_backend = _roles_del_backend()
    modulos = _modulos_del_frontend()
    hallazgos: list[tuple[str, str, str, str, str]] = []
    analizadas = 0
    resueltas = 0

    rutas = list(_rutas_del_router())
    if rutas_extra:
        rutas.extend(rutas_extra)

    for ruta, vista, roles_view in rutas:
        if not roles_view:
            continue
        endpoints: list[tuple[str, str]] = []
        for fichero in _ficheros_de_la_vista(vista):
            # 1. Las llamadas escritas directamente en el .vue.
            endpoints.extend(_llamadas_directas(fichero))
            # 2. Las que llegan a través de los módulos de @/api/.
            for modulo, funcion in _imports_de_vista(fichero):
                llamadas = modulos.get(modulo, {}).get(funcion)
                if llamadas:
                    endpoints.extend(llamadas)
        for metodo, ruta_api in endpoints:
            analizadas += 1
            completa = _ruta_del_backend(ruta_api)
            exigidos = roles_backend.get((metodo, completa))
            if exigidos is None:
                # La ruta no existe en el backend: lo dice otra puerta.
                continue
            resueltas += 1
            if not exigidos:
                # El endpoint no exige un rol concreto.
                continue
            for rol in roles_view:
                if rol not in exigidos:
                    hallazgos.append(
                        (ruta, vista, f"{metodo} {completa}", rol, ", ".join(sorted(exigidos)))
                    )
    return hallazgos, analizadas, resueltas


def _autoprueba() -> int:
    """Comprueba que esta puerta SIGUE detectando un desajuste real.

    La comprobación que importa es la del final: que la puerta haya
    **resuelto** llamadas de verdad. Una puerta que no encuentra ni una
    sola ruta en el backend no está comprobando que no haya
    desajustes: está comprobando que no sabe nada.
    """
    fallos = 0

    # 1. La puerta tiene que haber resuelto llamadas. Si no resuelve
    #    ninguna, su "verde" no significa nada (pasó con un prefijo mal
    #    puesto y comparaba contra un vacío durante todo ese tiempo).
    desajustes, analizadas, resueltas = _desajustes()
    if resueltas == 0:
        print("  FALLO: la puerta no ha resuelto NINGUNA llamada: no compara nada")
        fallos += 1
    else:
        print(f"  OK: la puerta compara de verdad ({resueltas} de {analizadas} llamadas resueltas)")

    if desajustes:
        print(f"  OK: hay {len(desajustes)} desajuste(s) real(es) en el repo")
    else:
        print("  (el repo no tiene desajustes: no hay caso positivo real)")

    # 2. Un endpoint de sólo admin llamado desde una pantalla de gestor
    #    tiene que salir.
    roles_backend = _roles_del_backend()
    admin_solamente = [
        (metodo, ruta) for (metodo, ruta), roles in roles_backend.items()
        if roles == {"admin"}
    ]
    if not admin_solamente:
        print("  FALLO: no hay ningun endpoint de sólo admin (no se puede probar)")
        fallos += 1
    else:
        metodo, ruta_api = sorted(admin_solamente)[0]
        exigidos = roles_backend[(metodo, ruta_api)]
        detectados = [r for r in ("gestor", "cliente") if r not in exigidos]
        if not detectados:
            print("  FALLO: ningun rol no concedido se ha detectado")
            fallos += 1
        else:
            print(f"  OK: un rol no concedido se detecta ({metodo} {ruta_api} -> {detectados})")

    # 3. Y una vista con el rol correcto NO tiene que salir.
    if roles_backend:
        metodo, ruta_api = sorted(roles_backend)[0]
        exigidos = roles_backend[(metodo, ruta_api)]
        concedidos = [r for r in ("admin", "gestor", "cliente", "operador") if r in exigidos]
        if not concedidos and exigidos:
            print(f"  FALLO: {metodo} {ruta_api} no concede a nadie (RBAC raro)")
            fallos += 1
        else:
            print(f"  OK: un rol concedido no se marca ({metodo} {ruta_api} -> {concedidos})")

    # 4. El caso de mentira completo, con una vista REAL y un endpoint
    #    REAL: se declara una ruta de mentira que abre la pantalla de
    #    usuarios al gestor. Esa pantalla llama a ``GET /users``, que es
    #    de sólo admin, así que la puerta tiene que cantarlo.
    #
    #    Es el caso que importa: comprueba la cadena ENTERA (router →
    #    vista → llamada directa → RBAC del backend), no una pieza suelta.
    desajustes_falsos, analizadas_falsas, resueltas_falsas = _desajustes(
        [("/ruta-de-mentira", "admin/UsersView.vue", ["admin", "gestor"])]
    )
    if resueltas_falsas == 0:
        print("  FALLO: la vista de mentira no ha resuelto ninguna llamada")
        fallos += 1
    elif not desajustes_falsos:
        print("  FALLO: el caso de mentira NO ha producido desajustes")
        fallos += 1
    else:
        print(f"  OK: el caso de mentira produce {len(desajustes_falsos)} desajuste(s) "
              f"({analizadas_falsas} llamadas, {resueltas_falsas} resueltas)")

    # 5. Y al revés: una pantalla de mentira que SÍ tiene el rol no
    #    debe producir desajustes.
    desajustes_buenos, _a, _r = _desajustes(
        [("/ruta-de-mentira-ok", "admin/UsersView.vue", ["admin"])]
    )
    if desajustes_buenos:
        print(f"  FALLO: una pantalla con el rol correcto ha producido "
              f"{len(desajustes_buenos)} desajuste(s)")
        fallos += 1
    else:
        print("  OK: una pantalla con el rol correcto no produce desajustes")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de roles sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando desajustes")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    rutas = _rutas_del_router()
    con_guard = [r for r in rutas if r[2]]
    modulos = _modulos_del_frontend()
    total_funciones = sum(len(f) for f in modulos.values())
    roles_backend = _roles_del_backend()

    print(f"rutas del router:            {len(rutas)} ({len(con_guard)} con guard de rol)")
    print(f"funciones del cliente HTTP:  {total_funciones} en {len(modulos)} modulos")
    print(f"endpoints con rol explicito: {sum(1 for r in roles_backend.values() if r)}")

    desajustes, analizadas, resueltas = _desajustes()
    print(f"llamadas analizadas:         {analizadas} ({resueltas} resueltas contra el backend)")

    # El guardia: una puerta que no ha resuelto nada no puede estar verde.
    if resueltas == 0:
        print("\nFALLO: la puerta no ha resuelto ninguna llamada contra el backend.")
        print("       No está comparando nada: el verde de esta puerta no significaría nada.")
        return 1

    if desajustes:
        print(f"\nLA PANTALLA PROMETE UN ROL QUE EL BACKEND NO CONCEDE ({len(desajustes)}):")
        for ruta, vista, endpoint, rol, exigidos in desajustes:
            print(f"  {ruta:26} rol '{rol}' llama a {endpoint:48}")
            print(f"  {'':26} el backend exige: {exigidos}   (vista: {vista})")
    else:
        print("\nOK: ninguna pantalla llama a un endpoint con un rol que no tenga.")

    if args.detalle:
        print("\nPantallas con guard de rol:")
        for ruta, vista, roles in con_guard:
            print(f"  {ruta:26} {', '.join(roles):28} {vista}")

    if desajustes:
        print(f"\n{len(desajustes)} desajuste(s) de rol.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
