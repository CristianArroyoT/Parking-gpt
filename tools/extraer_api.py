"""Extrae de los routers las rutas y su RBAC, leyendo el código.

El inventario de ``docs/API-INTERNAL.md`` tiene una columna "Quién" que
sale de las dependencias que cada endpoint declara. Este script la
extrae del código con el módulo ``ast`` (no del introspection de
FastAPI, que cambia entre versiones: en la 0.156 los routers incluidos
ya no se ven en ``app.routes``).

Se apoya en el OpenAPI **real** para la lista de rutas (esa es la
verdad) y en el código para el RBAC de cada una.

Uso:
    python tools/extraer_api.py            # tabla metodo · ruta · quien
    python tools/extraer_api.py --markdown # en formato de tabla del doc
"""
from __future__ import annotations

import argparse
import ast
import sys
import warnings
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
V1 = RAIZ / "backend" / "app" / "api" / "v1"
PREFIX_GLOBAL = "/api/v1"

#: Como se describe cada dependencia en la columna "Quién" del inventario.
DESCRIPCION_DEP = {
    "get_current_user": "Autenticado",
    "get_current_user_or_query_token": "`get_current_user_or_query_token`",
    "parking_context": "`parking_context`",
    "enforce_parking_membership": "`enforce_parking_membership`",
    "require_role": "`require_role(...)`",
    "require_roles": "`require_roles(...)`",
    "get_optional_user": "Autenticado (opcional)",
}

#: Dependencias que no son de autorizacion (base de datos, etc.).
NO_AUTORIZACION = {"get_db", "get_current_user_optional"}

#: (nombre de la dependencia, roles que acepta)
Dep = tuple[str, tuple[str, ...]]


def _nombre_dep(nodo: ast.AST) -> str | None:
    """El nombre de la funcion si el nodo es un ``Depends(...)``."""
    if not isinstance(nodo, ast.Call):
        return None
    func = nodo.func
    if not (isinstance(func, ast.Name) and func.id == "Depends"):
        return None
    if not nodo.args:
        return None
    primero = nodo.args[0]
    if isinstance(primero, ast.Name):
        return primero.id
    if isinstance(primero, ast.Call) and isinstance(primero.func, ast.Name):
        return primero.func.id
    return None


def _roles_de(nodo: ast.AST, constantes: dict[str, list[str]]) -> list[str]:
    """Los roles que se pasan a ``require_role(...)``.

    Admite las tres formas que usa el codigo:
      * ``require_role(UserRole.ADMIN)``      → ``['admin']``
      * ``require_role(UserRole.ADMIN.value)`` → ``['admin']``
      * ``require_role(*_STAFF)``              → los roles de la constante
    """
    if isinstance(nodo, ast.Call) and nodo.args:
        # ``require_role(UserRole.ADMIN)`` → miramos su primer argumento.
        return _roles_de(nodo.args[0], constantes)
    if isinstance(nodo, ast.Starred):
        nombre = nodo.value.id if isinstance(nodo.value, ast.Name) else None
        return list(constantes.get(nombre, [])) if nombre else []
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return [nodo.value]
    if isinstance(nodo, ast.Attribute):
        # ``UserRole.ADMIN.value`` → el atributo util es el anterior.
        if nodo.attr == "value" and isinstance(nodo.value, ast.Attribute):
            return [nodo.value.attr.lower()]
        return [nodo.attr.lower()]
    return []


def _constantes_de_roles(arbol: ast.AST) -> dict[str, list[str]]:
    """Constantes de modulo que son tuplas de roles (``_STAFF``)."""
    constantes: dict[str, list[str]] = {}
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, (ast.Tuple, ast.List)):
            continue
        roles: list[str] = []
        for elem in nodo.value.elts:
            extraidos = _roles_de(elem, constantes)
            if extraidos:
                roles.extend(extraidos)
        if not roles:
            continue
        for objetivo in nodo.targets:
            if isinstance(objetivo, ast.Name):
                constantes[objetivo.id] = roles
    return constantes


def _deps_de_lista(nodo: ast.AST, constantes: dict[str, list[str]]) -> list[Dep]:
    """Las dependencias de una lista de ``Depends(...)``."""
    encontradas: list[Dep] = []
    for elemento in getattr(nodo, "elts", []) or []:
        nombre = _nombre_dep(elemento)
        if not nombre:
            continue
        roles: tuple[str, ...] = ()
        if isinstance(elemento, ast.Call) and elemento.args:
            roles = tuple(_roles_de(elemento.args[0], constantes))
        dep: Dep = (nombre, roles)
        if dep not in encontradas:
            encontradas.append(dep)
    return encontradas


def _deps_de_decorador(dec: ast.Call, constantes: dict[str, list[str]]) -> list[Dep]:
    """Las dependencias declaradas en ``dependencies=[...]``."""
    encontradas: list[Dep] = []
    for kw in dec.keywords:
        if kw.arg != "dependencies":
            continue
        for d in _deps_de_lista(kw.value, constantes):
            if d not in encontradas:
                encontradas.append(d)
    return encontradas


def _deps_de_firma(func: ast.FunctionDef, constantes: dict[str, list[str]]) -> list[Dep]:
    """Las dependencias declaradas en la firma de la funcion."""
    encontradas: list[Dep] = []
    posicionales = func.args.args
    n_defs = len(func.args.defaults)
    pares: list[tuple[ast.expr, ast.expr | None]] = []
    for i, default in enumerate(func.args.defaults):
        pares.append((posicionales[len(posicionales) - n_defs + i], default))
    for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults):
        pares.append((arg, default))
    for _arg, default in pares:
        if default is None:
            continue
        nombre = _nombre_dep(default)
        if not nombre:
            continue
        roles: tuple[str, ...] = ()
        if isinstance(default, ast.Call) and default.args:
            roles = tuple(_roles_de(default.args[0], constantes))
        dep: Dep = (nombre, roles)
        if dep not in encontradas:
            encontradas.append(dep)
    return encontradas


#: Dependencias de autorizacion que algunos endpoints llaman **a mano**
#: dentro del cuerpo (el patron "opt-in por endpoint" del preview y el
#: SSE, en vez de un ``Depends`` en la firma).
LLAMADAS_MANUALES = {
    "get_current_user": "Autenticado",
    "get_current_user_or_query_token": "`get_current_user_or_query_token`",
    "parking_context": "`parking_context`",
    "enforce_parking_membership": "`enforce_parking_membership`",
}


def _deps_del_cuerpo(func: ast.FunctionDef) -> list[Dep]:
    """Dependencias que el endpoint invoca directamente en su cuerpo."""
    encontradas: list[Dep] = []
    for nodo in ast.walk(func):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Name):
            continue
        nombre = nodo.func.id
        if nombre not in LLAMADAS_MANUALES:
            continue
        dep: Dep = (nombre, ())
        if dep not in encontradas:
            encontradas.append(dep)
    return encontradas


def _usa_audit_del_middleware(func: ast.FunctionDef) -> bool:
    """Si el endpoint lee ``request.state.audit``.

    El ``AuditMiddleware`` valida el token Bearer y deja el contexto en
    ``request.state.audit``; un endpoint que lo lee (como ``logout``)
    depende de esa validacion aunque no declare ninguna dependencia.
    """
    for nodo in ast.walk(func):
        # ``request.state.audit``
        if isinstance(nodo, ast.Attribute) and nodo.attr == "audit":
            valor = nodo.value
            if isinstance(valor, ast.Attribute) and valor.attr == "state":
                return True
        # ``getattr(request.state, "audit", None)``
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "getattr" and nodo.args
                and isinstance(nodo.args[0], ast.Attribute)
                and nodo.args[0].attr == "state"
                and len(nodo.args) > 1
                and isinstance(nodo.args[1], ast.Constant)
                and nodo.args[1].value == "audit"):
            return True
    return False


def _ambito_del_cuerpo(
    func: ast.FunctionDef,
    helpers: dict[str, ast.FunctionDef] | None = None,
) -> list[str]:
    """El **ámbito de datos** que el endpoint aplica en su cuerpo.

    Las dependencias dicen *quién puede llamar* al endpoint, pero varios
    endpoints filtran además *qué ve* segun el rol y las membresias, y
    esa parte no sale de las dependencias: se comprueba a mano en el
    cuerpo (a proposito, para no duplicar el JOIN con
    ``parking_context``).

    El filtro muchas veces no esta en el endpoint sino en una
    **funcion auxiliar** del modulo (``_scoped_query``,
    ``_resolve_parking_id``...), asi que se siguen las llamadas a
    funciones locales del mismo fichero.
    """
    ambitos: list[str] = []
    helpers = helpers or {}
    vistas: set[int] = set()

    def recorrer(objetivo: ast.AST) -> None:
        if id(objetivo) in vistas:
            return
        vistas.add(id(objetivo))
        for nodo in ast.walk(objetivo):
            if not isinstance(nodo, ast.Call):
                continue
            # Si llama a una funcion auxiliar del modulo, se sigue su
            # cuerpo: ahi suele estar el filtro.
            if isinstance(nodo.func, ast.Name) and nodo.func.id in helpers:
                recorrer(helpers[nodo.func.id])

    def clases_consultadas(objetivo: ast.AST) -> set[str]:
        """Clases de ambito que se CONSULTAN (no las que se construyen).

        ``db.query(VehicleUser)`` y ``db.query(Vehicle).join(VehicleUser, ...)``
        son filtros; ``VehicleUser(user_id=..., role=...)`` es el ALTA de
        un vinculo, no un filtro.
        """
        padres: dict[ast.AST, ast.AST] = {}
        for padre in ast.walk(objetivo):
            for hijo in ast.iter_child_nodes(padre):
                padres[hijo] = padre
        consultadas: set[str] = set()
        for nodo in ast.walk(objetivo):
            if not isinstance(nodo, ast.Name):
                continue
            if nodo.id not in ("VehicleUser", "ParkingMembership"):
                continue
            padre = padres.get(nodo)
            if isinstance(padre, ast.Call) and padre.func is nodo:
                continue  # construccion: no es un filtro
            if isinstance(padre, (ast.FunctionDef, ast.AsyncFunctionDef, ast.arg)):
                continue  # anotacion de tipo: no es un filtro
            consultadas.add(nodo.id)
        return consultadas

    def anotar(objetivo: ast.AST) -> None:
        for clase in clases_consultadas(objetivo):
            ambito = (
                "ámbito: membresías de sucursal"
                if clase == "ParkingMembership"
                else "ámbito: sus vehículos"
            )
            if ambito not in ambitos:
                ambitos.append(ambito)

    def recorrer_con_ambito(objetivo: ast.AST) -> None:
        if id(objetivo) in vistas:
            return
        vistas.add(id(objetivo))
        anotar(objetivo)
        for nodo in ast.walk(objetivo):
            if not isinstance(nodo, ast.Call):
                continue
            if isinstance(nodo.func, ast.Name) and nodo.func.id in helpers:
                recorrer_con_ambito(helpers[nodo.func.id])

    recorrer_con_ambito(func)
    return ambitos


def _quien(deps: list[Dep], por_middleware: bool = False) -> str:
    textos: list[str] = []
    for nombre, roles in deps:
        if nombre in NO_AUTORIZACION:
            continue
        if nombre.startswith("require_role") and roles:
            lista = ", ".join(f"'{r}'" for r in roles)
            textos.append(f"`require_role({lista})`")
            continue
        textos.append(DESCRIPCION_DEP.get(nombre, f"`{nombre}`"))
    if not textos and por_middleware:
        return "Autenticado (middleware de auditoría)"
    if not textos:
        return "Público"
    return " + ".join(dict.fromkeys(textos))


def extraer_de_modulo(ruta_fichero: Path) -> list[tuple[str, str, str, str]]:
    """(metodo, ruta completa, quien, modulo) de un fichero de router."""
    arbol = ast.parse(ruta_fichero.read_text(encoding="utf-8"))
    constantes = _constantes_de_roles(arbol)
    prefijo = ""
    deps_router: list[Dep] = []

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            func = nodo.value.func
            if isinstance(func, ast.Name) and func.id == "APIRouter":
                for kw in nodo.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefijo = str(kw.value.value)
                    if kw.arg == "dependencies":
                        deps_router.extend(_deps_de_lista(kw.value, constantes))

    filas: list[tuple[str, str, str, str]] = []
    vistas: set[tuple[str, str]] = set()
    # Funciones auxiliares del modulo: ahi suele estar el filtro de
    # ambito (por ejemplo ``_scoped_query`` en tickets.py).
    auxiliares: dict[str, ast.FunctionDef] = {
        nodo.name: nodo
        for nodo in arbol.body
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in nodo.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            metodo = dec.func.attr.upper()
            if metodo not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            local = str(dec.args[0].value)
            completa = f"{PREFIX_GLOBAL}{prefijo}{local}"
            if (metodo, completa) in vistas:
                # La misma ruta registrada dos veces: FastAPI avisa con
                # "Duplicate Operation ID" al generar el OpenAPI.
                continue
            vistas.add((metodo, completa))
            deps = list(deps_router)
            for d in (_deps_de_decorador(dec, constantes)
                      + _deps_de_firma(nodo, constantes)
                      + _deps_del_cuerpo(nodo)):
                if d not in deps:
                    deps.append(d)
            quien = _quien(deps, por_middleware=_usa_audit_del_middleware(nodo))
            for ambito in _ambito_del_cuerpo(nodo, auxiliares):
                quien = f"{quien} + {ambito}"
            filas.append((metodo, completa, quien, ruta_fichero.stem))
    return filas


def _rutas_openapi() -> set[tuple[str, str]]:
    """Las rutas reales, tal y como las publica la app."""
    sys.path.insert(0, str(RAIZ / "backend"))
    warnings.filterwarnings("ignore")
    from app.main import create_app  # noqa: PLC0415

    spec = create_app().openapi()
    reales: set[tuple[str, str]] = set()
    for ruta, operaciones in spec["paths"].items():
        for metodo in operaciones:
            if metodo in ("get", "post", "put", "patch", "delete"):
                reales.add((metodo.upper(), ruta))
    return reales


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", action="store_true",
                    help="Salida en formato de tabla para el documento")
    args = ap.parse_args()

    filas: list[tuple[str, str, str, str]] = []
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        filas.extend(extraer_de_modulo(fichero))
    filas.sort(key=lambda f: (f[3], f[1], f[0]))

    # El OpenAPI manda: si el extractor se deja alguna ruta fuera, se ve.
    openapi = _rutas_openapi() - {("GET", "/health")}
    extraidas = {(m, r) for m, r, _, _ in filas}
    if args.markdown:
        for metodo, ruta, quien, _modulo in filas:
            print(f"| {metodo} | `{ruta}` | {quien} |")
    else:
        for metodo, ruta, quien, modulo in filas:
            print(f"{metodo:6} {ruta:56} {quien:46} [{modulo}]")
        print(f"\n{len(filas)} rutas extraidas del codigo")
    faltan = openapi - extraidas
    sobran = extraidas - openapi
    if faltan:
        print(f"\nEl extractor NO ha visto {len(faltan)} ruta(s) del OpenAPI:")
        for m, r in sorted(faltan):
            print(f"  {m:6} {r}")
    if sobran:
        print(f"\nEl extractor ha visto {len(sobran)} ruta(s) que NO estan en el OpenAPI:")
        for m, r in sorted(sobran):
            print(f"  {m:6} {r}")
    return 1 if (faltan or sobran) else 0


if __name__ == "__main__":
    raise SystemExit(main())
