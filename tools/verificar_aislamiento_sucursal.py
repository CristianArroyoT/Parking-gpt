"""Comprueba que los endpoints respetan el aislamiento por sucursal.

POR QUÉ esta puerta
-------------------
El modelo de datos **no tiene `client_id`**: el aislamiento entre
sucursales se hace con `parking_memberships` (quién pertenece a qué
sucursal) y con los roles. Ese aislamiento lo aplican **a mano**, endpoint
a endpoint, y cuatro endpoints se lo saltaron (T-113...T-116), todos
medidos contra el sistema en marcha:

- ``POST /tickets`` aceptaba el ``parking_id`` del cuerpo sin mirar la
  membresía (T-113).
- ``enforce_parking_membership`` miraba la membresía pero no el rol: un
  conductor con una membresía gestionaba la sucursal (T-114).
- ``GET``/``PATCH`` de geocercas no cruzaban la cámara con la sucursal
  del path (T-115).
- ``GET /vehicles`` devolvía la flota entera a cualquier gestor (T-116).

Un test cubre los que ya están escritos. Esta puerta cubre el que
falta: **el endpoint que alguien escriba mañana**, que no tendrá test
todavía. Por eso es estática (mira el código) y por eso tiene que
detectar los tres patrones sin ayuda de los tests.

QUÉ COMPRUEBA
-------------
- **R1**: un endpoint cuyo cuerpo acepta ``parking_id`` tiene que validar
  la membresía (salvo que sea de admin solamente).
- **R2**: un router cuyo prefijo lleva ``{parking_id}`` tiene que acotar:
  con ``parking_context`` en las dependencias del router, o endpoint a
  endpoint.
- **R3**: un endpoint que carga un recurso con sucursal tiene que
  comprobar que ese recurso es de la sucursal (cruzar el recurso con el
  ``parking_id`` del path, o validar la membresía sobre el recurso).

Y la autoprueba monta **casos de mentira escritos a mano** (en un
directorio temporal, con sus propios schemas y modelos) para demostrar
que la puerta detecta los tres patrones y **no** grita con el código
correcto.

Uso
---
    python tools/verificar_aislamiento_sucursal.py
    python tools/verificar_aislamiento_sucursal.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
V1_POR_DEFECTO = RAIZ / "backend" / "app" / "api" / "v1"
SCHEMAS_POR_DEFECTO = RAIZ / "backend" / "app" / "schemas"
MODELOS_POR_DEFECTO = RAIZ / "backend" / "app" / "models"

#: Funciones que ya comprueban que un recurso es de la sucursal del
#: usuario. La lista es **declarada y auditable**: si se añade una, hay
#: que añadirla aquí (la autoprueba lo comprueba con un caso de mentira).
VALIDADORES_DE_RECURSO = {
    "_camara_de_sucursal",
    "_adjunto_de_sucursal",
    "_scoped_query",
}

#: Consultas que ya quedan acotadas por la membresía del usuario.
CONSULTAS_ACOTADAS = {"_scoped_query"}

#: Dependencias que acotan a la sucursal del path.
DEPENDENCIAS_DE_SUCURSAL = {"parking_context", "enforce_parking_membership"}

#: Funciones que se pueden llamar dentro del endpoint para acotar.
LLAMADAS_DE_SUCURSAL = {"parking_context", "enforce_parking_membership"}

#: Exenciones **con su motivo**. Un endpoint exento tiene que decir por
#: qué: una exención sin motivo es una opinión, y las opiniones no
#: mantienen una puerta en pie.
EXENCIONES: dict[str, str] = {
    "tariffs.py:GET /parkings/{parking_id}/tariffs": (
        "T-117: el precio es público para quien va a aparcar; la app del "
        "cliente lo necesita antes de entrar. La escritura sí está acotada."
    ),
}


@dataclass
class Endpoint:
    modulo: str
    metodo: str
    ruta: str
    funcion: str
    prefijo: str = ""
    dependencias: list[str] = field(default_factory=list)
    roles: set[str] = field(default_factory=set)
    schema_cuerpo: str | None = None
    params_path: list[str] = field(default_factory=list)
    llamadas: set[str] = field(default_factory=set)
    compara_parking_id: bool = False

    @property
    def ruta_completa(self) -> str:
        return f"{self.prefijo}{self.ruta}"

    @property
    def clave(self) -> str:
        return f"{self.modulo}:{self.metodo} {self.ruta_completa}"


# ── datos auxiliares ─────────────────────────────────────────────────────


def _campos_de_schema(directorio: Path) -> dict[str, set[str]]:
    """Clase -> nombres de sus campos (en ``backend/app/schemas``)."""
    campos: dict[str, set[str]] = {}
    for fichero in sorted(directorio.glob("*.py")):
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for clase in [n for n in ast.walk(arbol) if isinstance(n, ast.ClassDef)]:
            nombres: set[str] = set()
            for nodo in clase.body:
                if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
                    nombres.add(nodo.target.id)
                elif isinstance(nodo, ast.Assign):
                    for objetivo in nodo.targets:
                        if isinstance(objetivo, ast.Name):
                            nombres.add(objetivo.id)
            if nombres:
                campos.setdefault(clase.name, set()).update(nombres)
    return campos


def _modelos_con_sucursal(directorio: Path) -> set[str]:
    """Clases de modelo que tienen una columna ``parking_id``."""
    clases: set[str] = set()
    for fichero in sorted(directorio.glob("*.py")):
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for clase in [n for n in ast.walk(arbol) if isinstance(n, ast.ClassDef)]:
            for nodo in clase.body:
                if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
                    if nodo.target.id == "parking_id":
                        clases.add(clase.name)
                elif isinstance(nodo, ast.Assign):
                    for objetivo in nodo.targets:
                        if isinstance(objetivo, ast.Name) and objetivo.id == "parking_id":
                            clases.add(clase.name)
    return clases


def _nombre_de_dependencia(nodo: ast.AST) -> str | None:
    """El nombre de la función de un ``Depends(...)``."""
    if not isinstance(nodo, ast.Call):
        return None
    func = nodo.func
    if isinstance(func, ast.Name) and func.id == "Depends" and nodo.args:
        primero = nodo.args[0]
        if isinstance(primero, ast.Name):
            return primero.id
        if isinstance(primero, ast.Call) and isinstance(primero.func, ast.Name):
            return primero.func.id
    return None


def _roles_de(nodo: ast.AST) -> set[str]:
    """Los roles que se pasan a ``require_role(...)``."""
    if not isinstance(nodo, ast.Call) or not nodo.args:
        return set()
    roles: set[str] = set()
    for argumento in nodo.args:
        if isinstance(argumento, ast.Starred):
            continue
        if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
            roles.add(argumento.value)
        elif isinstance(argumento, ast.Attribute):
            if argumento.attr == "value" and isinstance(argumento.value, ast.Attribute):
                roles.add(argumento.value.attr.lower())
            else:
                roles.add(argumento.attr.lower())
    return roles


def _roles_de_dependencia(nodo: ast.AST) -> set[str]:
    """Los roles de una dependencia ``Depends(require_role(...))``.

    OJO: los roles NO estan en ``elemento.func`` (que es ``Depends``),
    sino en ``elemento.args[0]`` (la llamada a ``require_role``). Antes
    se leian ahi, con lo que un router de admin (``costs.py``) parecia no
    exigir ningun rol.
    """
    if not isinstance(nodo, ast.Call) or not nodo.args:
        return set()
    primero = nodo.args[0]
    if (
        isinstance(primero, ast.Call)
        and isinstance(primero.func, ast.Name)
        and primero.func.id.startswith("require_role")
    ):
        return _roles_de(primero)
    return set()


def _llamadas_de(funcion: ast.FunctionDef) -> set[str]:
    """Los nombres de funcion que se LLAMAN en el cuerpo.

    OJO: se leen del AST, no del texto. Leerlos del texto cuenta tambien
    la prosa del docstring: un endpoint que solo **menciona**
    ``parking_context(...)`` en su documentacion pareceria acotar. Eso es
    un "verde sobre mentira", y fue lo que encontró la prueba inversa.
    """
    nombres: set[str] = set()
    for nodo in ast.walk(funcion):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            nombres.add(nodo.func.id)
    return nombres


def _compara_el_parking_id(funcion: ast.FunctionDef) -> bool:
    """Si el cuerpo compara el ``parking_id`` de un recurso con el del path."""
    for nodo in ast.walk(funcion):
        if not isinstance(nodo, ast.Compare) or not isinstance(nodo.left, ast.Attribute):
            continue
        if nodo.left.attr != "parking_id":
            continue
        for op, comparador in zip(nodo.ops, nodo.comparators, strict=False):
            if (
                isinstance(op, ast.Eq)
                and isinstance(comparador, ast.Name)
                and comparador.id == "parking_id"
            ):
                return True
    return False


def _params_de_la_ruta(ruta: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", ruta)


def _schema_del_cuerpo(funcion: ast.FunctionDef, campos: dict[str, set[str]]) -> str | None:
    """El schema del body (el parámetro cuyo tipo es un schema conocido)."""
    for argumento in funcion.args.args:
        anotacion = argumento.annotation
        if not isinstance(anotacion, ast.Name):
            continue
        if anotacion.id in campos:
            return anotacion.id
    return None


# ── análisis de un módulo ───────────────────────────────────────────────


def _analizar_modulo(
    fichero: Path, codigo: str, campos: dict[str, set[str]]
) -> list[Endpoint]:
    arbol = ast.parse(codigo)
    prefijo = ""
    dependencias_router: list[str] = []
    roles_router: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            llamada = nodo.value
            if isinstance(llamada.func, ast.Name) and llamada.func.id == "APIRouter":
                for clave in llamada.keywords:
                    if clave.arg == "prefix" and isinstance(clave.value, ast.Constant):
                        prefijo = str(clave.value.value)
                    elif clave.arg == "dependencies":
                        for elemento in getattr(clave.value, "elts", []) or []:
                            nombre = _nombre_de_dependencia(elemento)
                            if nombre:
                                dependencias_router.append(nombre)
                            roles_router |= _roles_de_dependencia(elemento)

    endpoints: list[Endpoint] = []
    for funcion in [n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)]:
        for decorador in funcion.decorator_list:
            if not isinstance(decorador, ast.Call):
                continue
            func = decorador.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "router"
            ):
                continue
            metodo = func.attr.upper()
            ruta = ""
            if decorador.args and isinstance(decorador.args[0], ast.Constant):
                ruta = str(decorador.args[0].value)
            dependencias: list[str] = list(dependencias_router)
            roles: set[str] = set(roles_router)
            for clave in decorador.keywords:
                if clave.arg == "dependencies":
                    for elemento in getattr(clave.value, "elts", []) or []:
                        nombre = _nombre_de_dependencia(elemento)
                        if nombre:
                            dependencias.append(nombre)
                        roles |= _roles_de_dependencia(elemento)
            for _argumento in funcion.args.args + funcion.args.kwonlyargs:
                default = None
                for d in funcion.args.defaults:
                    if d is not None:
                        default = d
                if default is None:
                    continue
                nombre = _nombre_de_dependencia(default)
                if nombre:
                    dependencias.append(nombre)
                    if nombre.startswith("require_role") and default.args:
                        roles |= _roles_de(default.args[0])
            endpoints.append(
                Endpoint(
                    modulo=fichero.name,
                    metodo=metodo,
                    ruta=ruta,
                    funcion=funcion.name,
                    prefijo=prefijo,
                    dependencias=list(dict.fromkeys(dependencias)),
                    roles=roles,
                    schema_cuerpo=_schema_del_cuerpo(funcion, campos),
                    params_path=_params_de_la_ruta(f"{prefijo}{ruta}"),
                    llamadas=_llamadas_de(funcion),
                    compara_parking_id=_compara_el_parking_id(funcion),
                )
            )
    return endpoints


# ── las tres reglas ─────────────────────────────────────────────────────


def _recurso_con_sucursal(
    endpoint: Endpoint, modelos_con_sucursal: set[str]
) -> str | None:
    """El modelo del recurso con sucursal que el endpoint carga por el path."""
    for param in endpoint.params_path:
        if not param.endswith("_id"):
            continue
        base = param[:-3].lower()
        for candidato in sorted(modelos_con_sucursal):
            nombre = candidato.lower()
            if nombre == base or nombre.endswith(base):
                return candidato
    return None


def _cruza_el_recurso(
    endpoint: Endpoint, modelos_con_sucursal: set[str]
) -> bool:
    """El endpoint cruza el recurso con el ``parking_id`` del path."""
    modelo = _recurso_con_sucursal(endpoint, modelos_con_sucursal)
    if modelo is None:
        return False
    if endpoint.compara_parking_id:
        return True
    return bool(endpoint.llamadas & VALIDADORES_DE_RECURSO)


def _acota_el_recurso(
    endpoint: Endpoint, modelos_con_sucursal: set[str]
) -> bool:
    """El endpoint comprueba que el recurso es de la sucursal del usuario.

    OJO: ``parking_context`` como **dependencia** no cuenta aquí: acota la
    sucursal del *path*, no la del *recurso*. Si contara, la puerta no
    vería el defecto de T-115 (las geocercas: el router acota la
    sucursal, pero la cámara podía ser de otra).
    """
    if _cruza_el_recurso(endpoint, modelos_con_sucursal):
        return True
    # Validar la membresía sobre la sucursal del propio recurso.
    if "enforce_parking_membership" in endpoint.llamadas:
        return True
    # Un validador dedicado al recurso.
    return bool(endpoint.llamadas & VALIDADORES_DE_RECURSO)


def _acota_la_sucursal(
    endpoint: Endpoint, modelos_con_sucursal: set[str]
) -> bool:
    """El endpoint acota de alguna forma a la sucursal.

    Tres formas válidas (cualquiera de las tres cierra la puerta):
    ``parking_context`` como dependencia, ``parking_context(...)`` dentro
    del cuerpo, o **cruzar** el recurso con el ``parking_id`` del path.
    """
    if any(d in DEPENDENCIAS_DE_SUCURSAL for d in endpoint.dependencias):
        return True
    if endpoint.llamadas & LLAMADAS_DE_SUCURSAL:
        return True
    if endpoint.llamadas & CONSULTAS_ACOTADAS:
        return True
    return _cruza_el_recurso(endpoint, modelos_con_sucursal)


def _es_solo_admin(endpoint: Endpoint) -> bool:
    """El endpoint exige admin y nada más (admin no necesita membresía)."""
    return endpoint.roles == {"admin"}


def _problemas_de_endpoint(
    endpoint: Endpoint,
    campos: dict[str, set[str]],
    modelos_con_sucursal: set[str],
) -> list[str]:
    problemas: list[str] = []
    etiqueta = f"{endpoint.modulo}: {endpoint.metodo} {endpoint.ruta_completa}"

    if endpoint.clave in EXENCIONES:
        return problemas

    # R1: el cuerpo acepta ``parking_id``.
    if (
        endpoint.schema_cuerpo
        and "parking_id" in campos.get(endpoint.schema_cuerpo, set())
        and not _acota_la_sucursal(endpoint, modelos_con_sucursal)
        and not _es_solo_admin(endpoint)
    ):
        problemas.append(
            f"{etiqueta}: acepta `parking_id` en el cuerpo y no valida la "
            f"membresía (usa `parking_context(...)`) [R1]"
        )

    # R2: el router lleva ``{parking_id}`` en el prefijo.
    if (
        "{parking_id}" in endpoint.prefijo
        and not _acota_la_sucursal(endpoint, modelos_con_sucursal)
        and not _es_solo_admin(endpoint)
    ):
        problemas.append(
            f"{etiqueta}: el router lleva `{{parking_id}}` en el prefijo y "
            f"el endpoint no acota la sucursal [R2]"
        )

    # R3: carga un recurso con sucursal y no comprueba de qué sucursal es.
    modelo = _recurso_con_sucursal(endpoint, modelos_con_sucursal)
    if (
        modelo is not None
        and not _acota_el_recurso(endpoint, modelos_con_sucursal)
        and not _es_solo_admin(endpoint)
    ):
        problemas.append(
            f"{etiqueta}: carga un recurso con sucursal (`{modelo}`) y no "
            f"comprueba de qué sucursal es [R3]"
        )

    return problemas


def verificar(v1: Path, schemas: Path, modelos: Path) -> list[str]:
    """Los problemas que encuentra en los routers dados."""
    campos = _campos_de_schema(schemas)
    modelos_con_sucursal = _modelos_con_sucursal(modelos)
    problemas: list[str] = []
    endpoints_analizados = 0
    for fichero in sorted(v1.glob("*.py")):
        if fichero.name == "__init__.py":
            continue
        codigo = fichero.read_text(encoding="utf-8")
        for endpoint in _analizar_modulo(fichero, codigo, campos):
            endpoints_analizados += 1
            problemas.extend(
                _problemas_de_endpoint(endpoint, campos, modelos_con_sucursal)
            )
    print(f"endpoints analizados: {endpoints_analizados}")
    print(f"modelos con `parking_id`: {len(modelos_con_sucursal)}")
    return problemas


# ── autoprueba: casos de mentira escritos a mano ────────────────────────

MODULO_MENTIRA = '''
from fastapi import APIRouter, Depends
from app.core.deps import parking_context, require_role
from app.models.user import User
from app.schemas.caso import CasoCreate, CasoRead

router = APIRouter(prefix="/parkings/{parking_id}/cosas")


@router.post("", response_model=CasoRead)
def crear(parking_id: int, payload: CasoCreate, db=Depends(get_db)) -> dict:
    """SIN acotar: acepta el parking_id del cuerpo sin validar la membresia."""
    return {}


@router.get("/{caso_id}/detalle")
def detalle(parking_id: int, caso_id: int, db=Depends(get_db)) -> dict:
    """SIN cruzar: carga el recurso sin comprobar de que sucursal es."""
    return {}
'''

MODULO_BUENO = '''
from fastapi import APIRouter, Depends
from app.core.deps import parking_context, require_role
from app.models.user import User
from app.schemas.caso import CasoCreate, CasoRead

router = APIRouter(prefix="/parkings/{parking_id}/cosas")


@router.post("", response_model=CasoRead)
def crear(parking_id: int, payload: CasoCreate, db=Depends(get_db)) -> dict:
    """BIEN: valida la membresia de la sucursal del cuerpo."""
    parking_context(payload.parking_id, current=user, db=db)
    return {}


@router.get("/{caso_id}/detalle")
def detalle(parking_id: int, caso_id: int, db=Depends(get_db)) -> dict:
    """BIEN: cruza el recurso con la sucursal del path."""
    caso = db.query(Caso).filter(Caso.id == caso_id, Caso.parking_id == parking_id).one_or_none()
    return {}
'''

MODULO_CON_VALIDADOR = '''
from fastapi import APIRouter, Depends
from app.core.deps import parking_context, require_role
from app.models.user import User
from app.schemas.caso import CasoCreate, CasoRead

router = APIRouter(prefix="/parkings/{parking_id}/cosas")


@router.get("/{caso_id}/detalle")
def detalle(parking_id: int, caso_id: int, db=Depends(get_db)) -> dict:
    """BIEN: usa un validador declarado (la lista de la puerta)."""
    caso = _camara_de_sucursal(db, caso_id, parking_id)
    return {}
'''

SCHEMA_MENTIRA = '''
from pydantic import BaseModel


class CasoCreate(BaseModel):
    parking_id: int
    nombre: str


class CasoRead(BaseModel):
    id: int
'''

MODELO_MENTIRA = '''
from sqlalchemy.orm import Mapped, mapped_column


class Caso:
    id: int
    parking_id: Mapped[int]
'''


def _montar_caso(raiz: Path, modulo: str) -> Path:
    (raiz / "app" / "api" / "v1").mkdir(parents=True, exist_ok=True)
    (raiz / "app" / "schemas").mkdir(parents=True, exist_ok=True)
    (raiz / "app" / "models").mkdir(parents=True, exist_ok=True)
    (raiz / "app" / "api" / "v1" / "caso.py").write_text(modulo, encoding="utf-8")
    (raiz / "app" / "schemas" / "caso.py").write_text(SCHEMA_MENTIRA, encoding="utf-8")
    (raiz / "app" / "models" / "caso.py").write_text(MODELO_MENTIRA, encoding="utf-8")
    return raiz


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira y callar con el bueno.

    POR QUÉ existe: una puerta que no puede demostrar que detecta lo que
    dice detectar no es una puerta. Los casos de mentira se montan aquí,
    **en runtime**, con sus propios schemas y modelos: si compartieran
    los del repo, la puerta y el código se vigilarían a sí mismos y los
    dos podrían mentir a la vez.
    """
    fallos = 0
    with tempfile.TemporaryDirectory(prefix="aislamiento_") as temporal:
        raiz = Path(temporal)

        # 1) El caso de mentira tiene que dar problemas.
        _montar_caso(raiz, MODULO_MENTIRA)
        problemas = verificar(
            raiz / "app" / "api" / "v1", raiz / "app" / "schemas", raiz / "app" / "models"
        )
        tiene_r1 = any("[R1]" in p for p in problemas)
        tiene_r2 = any("[R2]" in p for p in problemas)
        tiene_r3 = any("[R3]" in p for p in problemas)
        if tiene_r1 and tiene_r2 and tiene_r3:
            print("  OK: el caso de mentira se detecta (R1, R2 y R3)")
        else:
            print(f"  FALLO: el caso de mentira solo dio {problemas}")
            fallos += 1

        # 2) El caso bueno **no** tiene que dar problemas (una puerta que
        #    grita de más es una puerta que nadie mira).
        _montar_caso(raiz, MODULO_BUENO)
        problemas = verificar(
            raiz / "app" / "api" / "v1", raiz / "app" / "schemas", raiz / "app" / "models"
        )
        if not problemas:
            print("  OK: el caso correcto no da problemas (la puerta no grita de más)")
        else:
            print(f"  FALLO: el caso correcto dio {problemas}")
            fallos += 1

        # 3) Un endpoint que usa un VALIDADOR declarado tiene que dar 0
        #    problemas: si la lista de validadores de la puerta no
        #    funcionara, este caso daria un falso positivo.
        _montar_caso(raiz, MODULO_CON_VALIDADOR)
        problemas = verificar(
            raiz / "app" / "api" / "v1", raiz / "app" / "schemas", raiz / "app" / "models"
        )
        if not problemas:
            print("  OK: el caso con un validador declarado no da problemas")
        else:
            print(f"  FALLO: el caso con un validador declarado dio {problemas}")
            fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta detecta los tres patrones.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="comprueba que la puerta detecta los casos de mentira",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return _autoprueba()

    problemas = verificar(V1_POR_DEFECTO, SCHEMAS_POR_DEFECTO, MODELOS_POR_DEFECTO)
    if problemas:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nOK: todos los endpoints acotan la sucursal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
