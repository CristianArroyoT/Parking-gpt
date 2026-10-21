"""Test que falla si la app vuelve a usar una función SQL que sólo existe en SQLite.

POR QUÉ existe este test (T-04, plan maestro 2026-10-21)
----------------------------------------------------------
El 2026-07-21 se coló un ``strftime()`` (función **de SQLite**) en
``app/services/ticket_summary.py``. Pasó el CI porque la suite corría
siempre contra SQLite, llegó a ``main`` y en Docker devolvió HTTP 500:

    function strftime(character varying, timestamp with time zone) does not exist

PostgreSQL (el motor de producción) no tiene esa función. Este test
recorre el código de la aplicación y falla si aparece una función que
sólo existe en SQLite, para que el error se detecte **antes** de
desplegar.

CÓMO DISTINGUE SQL DE PYTHON (y por qué)
-----------------------------------------
``strftime`` significa DOS cosas distintas en este repo:

1. ``datetime.now().strftime("%Y-%m-%d")`` → método de Python. Es
   correcto, portable y aparece en varios sitios (``app/services/pdf.py``,
   ``app/services/email.py``, ``app/services/alerts.py``). **No** es un
   bug.
2. ``func.strftime("%Y", Ticket.entry_at)`` o ``text("SELECT strftime(...)")``
   → SQL enviado al motor. En PostgreSQL es un error 500.

Por eso el detector NO busca la palabra ``strftime`` por todo el código:
trabaja sobre el **AST** y sólo examina contextos que son SQL con
certainty:

- ``func.<nombre>(...)`` (``sqlalchemy.func``): es SQL por definición.
- ``text("...")`` / ``literal_column("...")``: el argumento es SQL.
- Una cadena literal que **parece SQL** (contiene ``SELECT``, ``INSERT
  INTO``, ``DELETE FROM``, ``CREATE TABLE``, ``UPDATE ... SET`` o un
  ``FROM`` acompañado de ``WHERE``/``JOIN``/``GROUP BY``/``ORDER BY``).

Todo lo demás (métodos de Python, comentarios, docstrings, cadenas de
texto corriente) queda fuera. Los comentarios y los docstrings se
excluyen a propósito: el propio ``ticket_summary.py`` documenta el bug
mencionando ``strftime()``, y un detector que leyera los comentarios
estaría gritándole al fuego.

EXCEPCIONES ACEPTADAS
----------------------
- ``# solidapp: allow-sqlite-only <motivo>`` en la línea del uso (o en
  la línea inmediatamente anterior) permite el uso y obliga a dejar
  escrito **por qué** es aceptable. Sin ese comentario, el test falla.
- Las funciones de Python ``datetime.strftime`` / ``date.strftime`` no
  son excepción: sencillamente no se miran, porque no son SQL.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

#: Directorio de la aplicación (lo que se despliega en Docker).
APP_DIR = Path(__file__).resolve().parents[1] / "app"

#: Funciones SQL que sólo existen en SQLite, con su alternativa en PostgreSQL.
FUNCIONES_SOLO_SQLITE: dict[str, str] = {
    "strftime": "PostgreSQL no la tiene: usa ``func.extract('epoch', ...)`` o ``to_char()``",
    "julianday": "PostgreSQL no la tiene: usa ``EXTRACT(EPOCH FROM ...)::float``",
    "ifnull": "PostgreSQL no la tiene: usa ``COALESCE(a, b)``",
    "group_concat": "PostgreSQL no la tiene: usa ``string_agg(expr, ',')``",
    "unixepoch": "PostgreSQL no la tiene: usa ``EXTRACT(EPOCH FROM ...)::bigint``",
    "last_insert_rowid": "PostgreSQL no la tiene: usa ``RETURNING id``",
    "sqlite_version": "SQLite-only: usa ``server_version()`` de PostgreSQL",
    "randomblob": "SQLite-only: usa ``gen_random_bytes()`` de PostgreSQL",
    "zeroblob": "SQLite-only: usa ``decode(repeat('0', n), 'hex')``",
}

#: Marcador que permite una excepción explícita (con su motivo al lado).
MARCA_PERMISO = "solidapp: allow-sqlite-only"

#: Nombres de las funciones prohibidas (para el detector de SQL crudo).
_ALTERNATIVAS = "|".join(sorted(FUNCIONES_SOLO_SQLITE))

#: ``nombre(`` dentro de una cadena SQL. El lookbehind excluye
#: ``datetime.strftime(`` (precedido por un punto) porque eso es Python.
_RE_FUNCION_SOLO_SQLITE = re.compile(
    rf"(?<![\w.$])(?P<fn>{_ALTERNATIVAS})\s*\(", re.IGNORECASE
)

#: SQL inequívoco: si aparece esto, la cadena es SQL.
_RE_SQL_FUERTE = re.compile(
    r"\b(select|insert\s+into|delete\s+from|create\s+table|drop\s+table)\b"
    r"|\bupdate\s+\w+\s+set\b",
    re.IGNORECASE,
)

#: SQL probable: ``FROM`` + una cláusula típica de SQL.
_RE_SQL_PROBABLE = re.compile(
    r"\bfrom\b[^;]*\b(where|join|group\s+by|order\s+by|having)\b",
    re.IGNORECASE | re.DOTALL,
)

#: Nombres de las funciones de SQLAlchemy que reciben SQL crudo.
_FUNCIONES_SQL_CRUDA = {"text", "literal_column"}


def _parece_sql(texto: str) -> bool:
    """¿Esta cadena parece SQL (y no texto corriente)?"""
    return bool(_RE_SQL_FUERTE.search(texto) or _RE_SQL_PROBABLE.search(texto))


def _es_func_sqlalchemy(nodo: ast.AST) -> bool:
    """¿Este nodo es el ``func`` de SQLAlchemy (``func`` / ``sa.func``)?"""
    if isinstance(nodo, ast.Name):
        return nodo.id == "func"
    if isinstance(nodo, ast.Attribute):
        return nodo.attr == "func"
    return False


def _ids_de_docstrings(arbol: ast.AST) -> set[int]:
    """IDs de los nodos que son docstrings (nunca se envían a la BD)."""
    ids: set[int] = set()
    for nodo in ast.walk(arbol):
        if isinstance(
            nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if not nodo.body:
                continue
            primero = nodo.body[0]
            if (
                isinstance(primero, ast.Expr)
                and isinstance(primero.value, ast.Constant)
                and isinstance(primero.value.value, str)
            ):
                ids.add(id(primero.value))
    return ids


class _Detector:
    """Detecta usos de funciones SQL que sólo existen en SQLite."""

    def __init__(self, lineas: list[str]) -> None:
        self.lineas = lineas
        self.incidencias: set[tuple[int, str]] = set()

    def _tiene_permiso(self, lineno: int) -> bool:
        """¿La línea (o la anterior) lleva el marcador de excepción?"""
        for numero in (lineno, lineno - 1):
            if 1 <= numero <= len(self.lineas) and MARCA_PERMISO in self.lineas[numero - 1]:
                return True
        return False

    def _reportar(self, lineno: int, nombre: str) -> None:
        if self._tiene_permiso(lineno):
            return
        self.incidencias.add((lineno, nombre))

    def revisar_texto_sql(self, texto: str, lineno: int) -> None:
        """Busca funciones prohibidas dentro de un trozo de SQL."""
        for coincidencia in _RE_FUNCION_SOLO_SQLITE.finditer(texto):
            self._reportar(lineno, coincidencia.group("fn").lower())

    def revisar_llamada(self, nodo: ast.Call) -> None:
        """Revisa una llamada: ``func.X(...)`` y ``text("...")``."""
        func = nodo.func
        if isinstance(func, ast.Attribute):
            # ``func.strftime(...)`` / ``sqlalchemy.func.strftime(...)``
            if (
                _es_func_sqlalchemy(func.value)
                and func.attr.lower() in FUNCIONES_SOLO_SQLITE
            ):
                self._reportar(nodo.lineno, func.attr.lower())
        elif isinstance(func, ast.Name) and func.id in _FUNCIONES_SQL_CRUDA:
            # ``text("SELECT ...")``: el argumento es SQL.
            for argumento in nodo.args:
                if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
                    self.revisar_texto_sql(argumento.value, argumento.lineno)

    def revisar_fstring(self, nodo: ast.JoinedStr) -> None:
        """Revisa un f-string: sólo sus trozos literales (el resto son valores)."""
        partes = [p.value for p in nodo.values if isinstance(p, ast.Constant)]
        if not partes:
            return
        texto = "".join(partes)
        if _parece_sql(texto):
            self.revisar_texto_sql(texto, nodo.lineno)


def _detectar_arbol(arbol: ast.AST, lineas: list[str]) -> list[tuple[int, str]]:
    """Detecta usos de funciones sólo de SQLite en un AST ya parseado."""
    docstrings = _ids_de_docstrings(arbol)
    detector = _Detector(lineas)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            detector.revisar_llamada(nodo)
        elif isinstance(nodo, ast.Constant):
            if id(nodo) in docstrings:
                continue  # un docstring nunca se envía al motor
            if isinstance(nodo.value, str) and _parece_sql(nodo.value):
                detector.revisar_texto_sql(nodo.value, nodo.lineno)
        elif isinstance(nodo, ast.JoinedStr):
            detector.revisar_fstring(nodo)
    return sorted(detector.incidencias)


def _detectar_codigo(codigo: str) -> list[tuple[int, str]]:
    """Detecta usos de funciones sólo de SQLite en un fragmento de código.

    Devuelve una lista de ``(línea, función)``.
    """
    return _detectar_arbol(ast.parse(codigo), codigo.splitlines())


def _detectar_fichero(ruta: Path) -> list[str]:
    """Detecta usos de funciones sólo de SQLite en un fichero real."""
    codigo = ruta.read_text(encoding="utf-8")
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:  # pragma: no cover — el código de la app debe compilar
        return []
    return [
        f"{ruta.relative_to(APP_DIR.parent)}:{linea}: {nombre}() sólo existe en SQLite "
        f"→ {FUNCIONES_SOLO_SQLITE[nombre]}"
        for linea, nombre in _detectar_arbol(arbol, codigo.splitlines())
    ]


def _infracciones_en_la_app() -> list[str]:
    """Recorre toda la aplicación y devuelve las infracciones encontradas."""
    infracciones: list[str] = []
    for ruta in sorted(APP_DIR.rglob("*.py")):
        infracciones.extend(_detectar_fichero(ruta))
    return infracciones


# ── el test que importa ───────────────────────────────────────────────────

def test_la_app_no_usa_funciones_solo_de_sqlite() -> None:
    """Falla si alguien reintroduce una función SQL exclusiva de SQLite.

    Es el test que habría pillado el ``strftime()`` de
    ``ticket_summary.py`` antes de que llegara a producción.
    """
    infracciones = _infracciones_en_la_app()
    assert not infracciones, (
        "Se han encontrado funciones SQL que sólo existen en SQLite. En "
        "PostgreSQL (el motor de producción) devuelven un HTTP 500:\n"
        + "\n".join(f"  - {i}" for i in infracciones)
        + "\n\nSustitúyelas por su equivalente en PostgreSQL (ver el comentario "
        "de cada una) o, si el uso es intencionado, añade el comentario "
        f"``# {MARCA_PERMISO} <motivo>`` en la línea."
    )


# ── tests del propio detector (para que no se degrade en silencio) ────────

def test_el_detector_pilla_func_strftime() -> None:
    """``func.strftime(...)`` es SQL → tiene que saltar."""
    codigo = (
        "from sqlalchemy import func\n"
        "def q(db):\n"
        "    return db.query(func.strftime('%Y', Ticket.entry_at))\n"
    )
    assert _detectar_codigo(codigo) == [(3, "strftime")]


@pytest.mark.parametrize("nombre", ["julianday", "ifnull", "group_concat", "unixepoch"])
def test_el_detector_pilla_las_demas_funciones_de_sqlite(nombre: str) -> None:
    """La lista de funciones prohibidas está completa y se detecta cada una."""
    codigo = (
        "from sqlalchemy import func\n"
        "def q(db):\n"
        f"    return db.query(func.{nombre}(1, 2))\n"
    )
    assert _detectar_codigo(codigo) == [(3, nombre)]


def test_el_detector_pilla_sql_crudo_en_text() -> None:
    """``text("SELECT strftime(...)")`` es SQL → tiene que saltar."""
    codigo = (
        "from sqlalchemy import text\n"
        "def q(db):\n"
        "    return db.execute(text(\"SELECT strftime('%Y', created_at) FROM tickets\"))\n"
    )
    assert _detectar_codigo(codigo) == [(3, "strftime")]


def test_el_detector_pilla_sql_crudo_en_una_cadena() -> None:
    """Una cadena que es SQL (aunque no esté en ``text()``) también salta."""
    codigo = "SQL = \"SELECT id FROM tickets WHERE strftime('%Y', created_at) = '2026'\"\n"
    assert _detectar_codigo(codigo) == [(1, "strftime")]


def test_el_detector_ignora_el_strftime_de_python() -> None:
    """``datetime.strftime(...)`` es Python: NO es un bug de dialecto."""
    codigo = (
        "from datetime import datetime, timezone\n"
        "def formatear(dt):\n"
        "    return dt.strftime('%d/%m/%Y %H:%M')\n"
        "def ahora():\n"
        "    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')\n"
    )
    assert _detectar_codigo(codigo) == []


def test_el_detector_ignora_comentarios_y_docstrings() -> None:
    """Documentar el bug no es usar el bug."""
    codigo = (
        '"""Módulo que documenta el uso de strftime()."""\n'
        "# OJO: strftime() es de SQLite y no existe en PostgreSQL.\n"
        "def f():\n"
        "    '''Docstring que menciona strftime() y julianday().'''\n"
        "    return 1\n"
    )
    assert _detectar_codigo(codigo) == []


def test_el_detector_ignora_texto_corriente() -> None:
    """Una frase que hable de SQL pero no lo es, no se marca."""
    codigo = (
        "AVISO = 'select the best option from the list where it fits'\n"
        "def f():\n"
        "    return AVISO\n"
    )
    assert _detectar_codigo(codigo) == []


def test_el_marcador_de_permiso_permite_la_excepcion() -> None:
    """``# solidapp: allow-sqlite-only <motivo>`` desactiva el test."""
    codigo = (
        "from sqlalchemy import func\n"
        "def q(db):\n"
        "    # solidapp: allow-sqlite-only sólo para el export CSV de SQLite\n"
        "    return db.query(func.strftime('%Y', Ticket.entry_at))\n"
    )
    assert _detectar_codigo(codigo) == []


def test_el_detector_cubre_toda_la_app() -> None:
    """El detector recorre de verdad todos los ficheros de ``app/``."""
    ficheros = list(APP_DIR.rglob("*.py"))
    assert len(ficheros) > 10, f"sólo encontré {len(ficheros)} ficheros en {APP_DIR}"
    assert (APP_DIR / "services" / "ticket_summary.py").exists()
