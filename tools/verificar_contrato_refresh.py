"""Comprueba que el cuerpo de ``POST /auth/refresh`` encaja con el frontend.

POR QUÉ (2026-10-25, T-187): el cliente renueva la sesión con
``POST /auth/refresh`` mandando **sólo** ``{"refresh_token": ...}``, pero el
backend exigía un ``TokenPair`` COMPLETO (``access_token`` + ``expires_in``
+ ``refresh_token``): el endpoint respondía **422**, el cliente limpiaba la
sesión y el operador se quedaba en el login a los 15 minutos (el TTL del
access token) con el refresh token —válido 7 días— sin poder usarlo.

Medido en el navegador (2026-10-25): ``GET /api/v1/parkings`` → **401** y
``POST /api/v1/auth/refresh`` → **422**.

El arreglo (un ``TokenRefreshRequest`` con **un solo** campo) no lo vigilaba
nadie: ``verificar_contrato_frontend.py`` compara **rutas**, no **cuerpos**,
y una ruta correcta con un body equivocado se le escapa. Esta puerta mira el
cuerpo, los dos lados, de forma estática.

QUÉ COMPRUEBA
-------------
- **R1**: todo campo **obligatorio** del modelo del body (el que el backend
  usa para validar la petición) tiene que estar en lo que manda el
  frontend. Si el backend exige un campo que el cliente no manda, el
  cliente recibe un 422.
- **R1b**: todo campo que el frontend manda tiene que existir en el modelo
  del body. Un nombre distinto no da un 422, da un 401: el backend leería
  un campo vacío.
- **R1c**: el endpoint tiene que **leer** alguno de los campos que manda el
  frontend.
- **R2**: todo campo que el frontend lee de la respuesta tiene que existir
  en el modelo de respuesta del backend (``response_model``).
- **R3**: la URL que llama el frontend tiene que ser la del backend, con el
  ``baseURL`` leído del **propio cliente** (no hardcodeado).

De dónde sale cada dato
-----------------------
- **Frontend** (``frontend/src/api/client.ts``): la función ``doRefresh()``,
  el tipo de la respuesta (``axios.post<{...}>``), la URL (con el
  ``${baseURL}`` resuelto) y las **claves** del objeto que se manda como
  body (el segundo argumento de ``axios.post``). Los comentarios se
  ignoran: un comentario que mentiona ``{ refresh_token: ... }`` no hace
  que el cliente lo mande.
- **Backend** (``backend/app/api/v1/auth.py`` y
  ``backend/app/schemas/__init__.py``): el endpoint ``refresh`` (su
  ``payload``, su ``response_model``), el prefijo del router y los campos
  del modelo (obligatorios los que **no** tienen valor por defecto).

Todo es estático (sólo ``ast`` y ``re``): la puerta no arranca nada, así que
el CI la puede correr **antes** del ``pip install`` del backend.

Uso:
    python tools/verificar_contrato_refresh.py
    python tools/verificar_contrato_refresh.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent

#: Los ficheros que la puerta mira, relativos a la raíz del repo.
CLIENTE = Path("frontend") / "src" / "api" / "client.ts"
AUTH = Path("backend") / "app" / "api" / "v1" / "auth.py"
API_V1 = Path("backend") / "app" / "api" / "v1" / "__init__.py"
SCHEMAS = Path("backend") / "app" / "schemas" / "__init__.py"

#: Los ficheros que la autoprueba copia al directorio temporal.
FICHEROS = (CLIENTE, AUTH, API_V1, SCHEMAS)

#: Los atributos que el frontend lee de la respuesta (``data.access_token``).
RE_ACCESO_DATA = re.compile(r"\bdata\s*\.\s*([A-Za-z_$][\w$]*)")

#: El ``baseURL`` del cliente (su valor, no el atajo ``baseURL,``).
RE_BASE_URL = re.compile(r"""(?:const\s+)?baseURL\s*[:=]\s*['"]([^'"]+)['"]""")


class _NoSePudoError(Exception):
    """Falta información para comprobar el contrato.

    OJO (regla del repo): esto NO es un verde. Si la puerta no puede
    comprobar lo que dice comprobar, lo dice y sale en rojo: un verde
    silencioso sobre una comprobación que no se ha hecho no vale.
    """


@dataclass
class Contrato:
    """Lo que dicen los dos lados sobre ``POST /auth/refresh``."""

    base_url: str
    url_frontend: str
    url_relativa: str
    ruta_relativa_backend: str
    prefijo_api: str
    modelo_cuerpo: str
    modelo_respuesta: str
    obligatorios: set[str]
    opcionales: set[str]
    campos_respuesta: set[str]
    campos_respuesta_backend: set[str]
    claves_cuerpo: set[str]
    leidos_por_el_backend: set[str]


# ── Lectura de ficheros (sin tocar los finales de línea) ──────────────────


def _leer(ruta: Path) -> str:
    """El texto del fichero, con sus finales de línea tal cual."""
    with open(ruta, encoding="utf-8", newline="") as fichero:
        return fichero.read()


def _escribir(ruta: Path, texto: str) -> None:
    """Escribe el texto sin convertir los finales de línea."""
    with open(ruta, "w", encoding="utf-8", newline="") as fichero:
        fichero.write(texto)


# ── Mini-lector de TypeScript (lo justo para el cliente) ─────────────────


def _sin_comentarios(texto: str) -> str:
    """Sustituye los comentarios por espacios (conservando las líneas).

    POR QUÉ: una puerta que mira el código tiene que mirarlo **sin
    comentarios**. Un comentario que menciona ``{ refresh_token: ... }`` no
    hace que el cliente mande ese campo, y una puerta que lo creyera daría
    el visto bueno a un defecto.
    """
    salida: list[str] = []
    i = 0
    n = len(texto)
    while i < n:
        caracter = texto[i]
        if caracter == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                salida.append(" ")
                i += 1
            continue
        if caracter == "/" and i + 1 < n and texto[i + 1] == "*":
            while i < n and not (texto[i] == "*" and i + 1 < n and texto[i + 1] == "/"):
                salida.append("\n" if texto[i] == "\n" else " ")
                i += 1
            salida.append("  ")
            i += 2
            continue
        if caracter in "'\"`":
            fin = _fin_de_cadena(texto, i)
            salida.append(texto[i:fin])
            i = fin
            continue
        salida.append(caracter)
        i += 1
    return "".join(salida)


def _fin_de_cadena(texto: str, i: int) -> int:
    """El índice justo detrás de la cadena que empieza en ``i``.

    Las plantillas de JavaScript (`````${...}```) se resuelven contando
    llaves, así que un ``}`` dentro de un ``${}`` no cierra el bloque.
    """
    comilla = texto[i]
    i += 1
    n = len(texto)
    while i < n:
        caracter = texto[i]
        if caracter == "\\":
            i += 2
            continue
        if comilla == "`" and caracter == "$" and i + 1 < n and texto[i + 1] == "{":
            i = _fin_de_bloque(texto, i + 1, "{", "}")
            continue
        if caracter == comilla:
            return i + 1
        i += 1
    return n


def _fin_de_bloque(texto: str, i: int, abre: str, cierra: str) -> int:
    """El índice justo detrás del bloque que empieza en ``i``."""
    n = len(texto)
    profundidad = 0
    while i < n:
        caracter = texto[i]
        if caracter in "'\"`":
            i = _fin_de_cadena(texto, i)
            continue
        if caracter == abre:
            profundidad += 1
        elif caracter == cierra:
            profundidad -= 1
            if profundidad == 0:
                return i + 1
        i += 1
    return n


def _saltar_espacios(texto: str, i: int) -> int:
    while i < len(texto) and texto[i].isspace():
        i += 1
    return i


def _argumentos(texto: str, i: int) -> list[str]:
    """Los argumentos de una llamada que empieza en ``texto[i] == '('``.

    Se parte por las comas de **nivel superior**: las comas de un objeto o
    de una lista no cortan el argumento.
    """
    argumentos: list[str] = []
    inicio = i + 1
    profundidad = 1
    # El ``(`` de la llamada ya está dentro: se empieza a leer DESPUÉS de
    # él (si no, el bloque se comería la llamada entera).
    i += 1
    while i < len(texto):
        caracter = texto[i]
        if caracter in "'\"`":
            i = _fin_de_cadena(texto, i)
            continue
        if caracter in "([{":
            i = _fin_de_bloque(texto, i, caracter, {"(": ")", "[": "]", "{": "}"}[caracter])
            continue
        if caracter in ")]}":
            profundidad -= 1
            if profundidad == 0:
                argumentos.append(texto[inicio:i])
                return argumentos
        elif caracter == "," and profundidad == 1:
            argumentos.append(texto[inicio:i])
            inicio = i + 1
        i += 1
    argumentos.append(texto[inicio:])
    return argumentos


def _trozos(texto: str, separadores: set[str]) -> list[str]:
    """El texto partido por los separadores de **nivel superior**."""
    partes: list[str] = []
    inicio = 0
    i = 0
    while i < len(texto):
        caracter = texto[i]
        if caracter in "'\"`":
            i = _fin_de_cadena(texto, i)
            continue
        if caracter in "([{":
            i = _fin_de_bloque(texto, i, caracter, {"(": ")", "[": "]", "{": "}"}[caracter])
            continue
        if caracter in separadores:
            partes.append(texto[inicio:i])
            inicio = i + 1
        i += 1
    partes.append(texto[inicio:])
    return partes


def _claves(fuente: str, separadores: set[str] | None = None) -> tuple[set[str], bool]:
    """(claves, hay_parte_ignorable) de un objeto literal ``{...}``.

    ``hay_parte_ignorable`` vale ``True`` si hay algo que no se puede
    leer de forma fiable (una propagación ``...x`` o una clave
    calculada): en ese caso la comprobación no puede ser completa.
    """
    fuente = fuente.strip()
    if not (fuente.startswith("{") and fuente.endswith("}")):
        return set(), True
    separadores = separadores or {","}
    claves: set[str] = set()
    ignorable = False
    for parte in _trozos(fuente[1:-1], separadores):
        parte = parte.strip()
        if not parte:
            continue
        if parte.startswith("..."):
            ignorable = True
            continue
        con_tipo = re.match(r"([A-Za-z_$][\w$]*)\s*:", parte)
        if con_tipo:
            claves.add(con_tipo.group(1))
            continue
        sin_tipo = re.match(r"([A-Za-z_$][\w$]*)\s*$", parte)
        if sin_tipo:
            claves.add(sin_tipo.group(1))
            continue
        ignorable = True
    return claves, ignorable


def _literal(argumento: str) -> str | None:
    """El contenido de un argumento que sea una cadena (o plantilla)."""
    argumento = argumento.strip()
    if not argumento or argumento[0] not in "'\"`":
        return None
    fin = _fin_de_cadena(argumento, 0)
    return argumento[1:fin - 1]


def _constante_base_url(texto: str) -> str | None:
    """El valor del ``baseURL`` del cliente."""
    coincidencia = RE_BASE_URL.search(texto)
    return coincidencia.group(1) if coincidencia else None


def _region_do_refresh(texto: str) -> str | None:
    """El cuerpo de ``doRefresh()`` en el cliente."""
    coincidencia = re.search(r"(?:function\s+doRefresh|doRefresh\s*[:=])", texto)
    if not coincidencia:
        return None
    inicio = texto.find("{", coincidencia.end())
    if inicio < 0:
        return None
    return texto[inicio:_fin_de_bloque(texto, inicio, "{", "}")]


@dataclass
class LlamadaPost:
    """Lo que se ve de una llamada ``axios.post``."""

    url: str
    cuerpo: str | None
    tipo_respuesta: str | None


def _analizar_post(region: str) -> LlamadaPost | None:
    """La llamada ``axios.post`` que hay dentro de ``region``."""
    coincidencia = re.search(r"\baxios\s*\.\s*post\b", region)
    if not coincidencia:
        return None
    i = coincidencia.end()
    tipo: str | None = None
    j = _saltar_espacios(region, i)
    if j < len(region) and region[j] == "<":
        fin = _fin_de_bloque(region, j, "<", ">")
        tipo = region[j + 1:fin - 1]
        i = fin
    j = _saltar_espacios(region, i)
    if j >= len(region) or region[j] != "(":
        return None
    argumentos = _argumentos(region, j)
    if not argumentos:
        return None
    url = _literal(argumentos[0])
    if url is None:
        return None
    cuerpo = argumentos[1].strip() if len(argumentos) > 1 else None
    return LlamadaPost(url=url, cuerpo=cuerpo, tipo_respuesta=tipo)


def _resolver_url(url: str, constantes: dict[str, str]) -> str | None:
    """Sustituye ``${baseURL}`` por su valor; ``None`` si hay algo raro."""
    desconocidas: list[str] = []

    def sustituir(encontrado: re.Match[str]) -> str:
        nombre = encontrado.group(1).strip()
        valor = constantes.get(nombre)
        if valor is None:
            desconocidas.append(nombre)
            return ""
        return valor

    resuelta = re.sub(r"\$\{([^}]*)\}", sustituir, url)
    return resuelta if not desconocidas else None


# ── Lector del backend (ast) ──────────────────────────────────────────────


def _nombre(nodo: ast.AST | None) -> str | None:
    """El nombre de un modelo, en la notación que sea."""
    if nodo is None:
        return None
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        return nodo.attr
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def _prefijo_de_router(modulo: ast.Module, variable: str) -> str:
    """El ``prefix=`` de ``APIRouter(...)`` de la variable indicada."""
    for nodo in ast.walk(modulo):
        if not isinstance(nodo, ast.Assign):
            continue
        if not any(isinstance(destino, ast.Name) and destino.id == variable
                   for destino in nodo.targets):
            continue
        if not isinstance(nodo.value, ast.Call):
            continue
        for palabra in nodo.value.keywords:
            if palabra.arg == "prefix":
                valor = _nombre(palabra.value)
                if valor:
                    return valor
    return ""


def _endpoint_refresh(modulo: ast.Module) -> dict[str, object] | None:
    """La función ``refresh`` del router: ruta, modelos y campos leídos."""
    for nodo in ast.walk(modulo):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if nodo.name != "refresh":
            continue
        for decorador in nodo.decorator_list:
            if not isinstance(decorador, ast.Call):
                continue
            funcion = decorador.func
            if not (isinstance(funcion, ast.Attribute) and funcion.attr == "post"):
                continue
            if not (isinstance(funcion.value, ast.Name) and funcion.value.id == "router"):
                continue
            ruta = ""
            if decorador.args:
                valor = _nombre(decorador.args[0])
                ruta = valor or ""
            modelo_respuesta = None
            for palabra in decorador.keywords:
                if palabra.arg == "response_model":
                    modelo_respuesta = _nombre(palabra.value)
            modelo_cuerpo = None
            for argumento in nodo.args.args:
                if argumento.arg == "payload":
                    modelo_cuerpo = _nombre(argumento.annotation)
            leidos: set[str] = set()
            for interior in ast.walk(nodo):
                if (isinstance(interior, ast.Attribute)
                        and isinstance(interior.value, ast.Name)
                        and interior.value.id == "payload"):
                    leidos.add(interior.attr)
            return {
                "ruta": ruta,
                "modelo_cuerpo": modelo_cuerpo,
                "modelo_respuesta": modelo_respuesta,
                "leidos": leidos,
            }
    return None


def _campos_del_modelo(ruta_schemas: Path, modelo: str) -> tuple[set[str], set[str]] | None:
    """(obligatorios, opcionales) del modelo; ``None`` si no existe.

    OJO: sólo se miran los campos **declarados** en el cuerpo de la clase.
    ``ORMModel`` (la base de los schemas) no declara ningún campo, así que
    no se pierde nada por no mirar las bases.
    """
    arbol = ast.parse(_leer(ruta_schemas))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ClassDef) or nodo.name != modelo:
            continue
        obligatorios: set[str] = set()
        opcionales: set[str] = set()
        for elemento in nodo.body:
            if not isinstance(elemento, ast.AnnAssign):
                continue
            if not isinstance(elemento.target, ast.Name):
                continue
            if elemento.value is None:
                obligatorios.add(elemento.target.id)
            else:
                opcionales.add(elemento.target.id)
        return obligatorios, opcionales
    return None


# ── El contrato, juntando los dos lados ──────────────────────────────────


def analizar(raiz: Path) -> Contrato:
    """Lee los dos lados y devuelve el contrato; si no puede, ``_NoSePudoError``."""
    for relativo in FICHEROS:
        if not (raiz / relativo).exists():
            raise _NoSePudoError(f"no se encuentra el fichero {relativo}")

    texto = _sin_comentarios(_leer(raiz / CLIENTE))
    base_url = _constante_base_url(texto)
    if not base_url:
        raise _NoSePudoError("no se ha encontrado el ``baseURL`` del cliente")
    region = _region_do_refresh(texto)
    if region is None:
        raise _NoSePudoError("no se ha encontrado ``doRefresh()`` en el cliente")
    llamada = _analizar_post(region)
    if llamada is None:
        raise _NoSePudoError("no se ha encontrado la llamada ``axios.post`` de ``doRefresh()``")
    url = _resolver_url(llamada.url, {"baseURL": base_url})
    if url is None:
        raise _NoSePudoError(f"no se ha podido resolver la URL del refresco ({llamada.url})")
    if llamada.cuerpo is None or not llamada.cuerpo.strip().startswith("{"):
        raise _NoSePudoError(
            "el cuerpo del refresco no es un objeto literal: no se puede comprobar"
        )
    claves_cuerpo, cuerpo_ignorable = _claves(llamada.cuerpo)
    if cuerpo_ignorable:
        raise _NoSePudoError(
            "el cuerpo del refresco tiene una parte que no se puede leer "
            "(propagación o clave calculada): no se puede comprobar"
        )

    campos_respuesta = set(RE_ACCESO_DATA.findall(region))
    if llamada.tipo_respuesta and llamada.tipo_respuesta.strip().startswith("{"):
        campos_tipo, _ = _claves(llamada.tipo_respuesta, {",", ";", "\n"})
        campos_respuesta |= campos_tipo
    elif not campos_respuesta:
        raise _NoSePudoError(
            "no se ha encontrado el tipo de la respuesta ni los campos que el "
            "cliente lee de ella: no se puede comprobar"
        )

    arbol_auth = ast.parse(_leer(raiz / AUTH))
    prefijo_router = _prefijo_de_router(arbol_auth, "router")
    endpoint = _endpoint_refresh(arbol_auth)
    if endpoint is None:
        raise _NoSePudoError("no se ha encontrado el endpoint ``refresh`` en el backend")
    modelo_cuerpo = endpoint["modelo_cuerpo"]
    modelo_respuesta = endpoint["modelo_respuesta"]
    if not modelo_cuerpo:
        raise _NoSePudoError("el endpoint ``refresh`` no declara el modelo del cuerpo")
    if not modelo_respuesta:
        raise _NoSePudoError("el endpoint ``refresh`` no declara ``response_model``")

    campos = _campos_del_modelo(raiz / SCHEMAS, str(modelo_cuerpo))
    if campos is None:
        raise _NoSePudoError(f"no se ha encontrado el modelo {modelo_cuerpo} en los schemas")
    obligatorios, opcionales = campos
    modelo_respuesta_campos = _campos_del_modelo(raiz / SCHEMAS, str(modelo_respuesta))
    if modelo_respuesta_campos is None:
        raise _NoSePudoError(
            f"no se ha encontrado el modelo {modelo_respuesta} en los schemas"
        )

    prefijo_api = _prefijo_de_router(ast.parse(_leer(raiz / API_V1)), "api_router")
    url_relativa = url[len(base_url):] if url.startswith(base_url) else url

    return Contrato(
        base_url=base_url,
        url_frontend=url,
        url_relativa=url_relativa,
        ruta_relativa_backend=f"{prefijo_router}{endpoint['ruta']}",
        prefijo_api=prefijo_api,
        modelo_cuerpo=str(modelo_cuerpo),
        modelo_respuesta=str(modelo_respuesta),
        obligatorios=obligatorios,
        opcionales=opcionales,
        campos_respuesta=campos_respuesta,
        campos_respuesta_backend=(
            set(modelo_respuesta_campos[0]) | set(modelo_respuesta_campos[1])
        ),
        claves_cuerpo=claves_cuerpo,
        leidos_por_el_backend=set(endpoint["leidos"]),  # type: ignore[arg-type]
    )


def _problemas(contrato: Contrato) -> list[str]:
    """Los desajustes entre los dos lados."""
    problemas: list[str] = []

    # R1: el backend exige campos que el cliente no manda -> 422.
    for campo in sorted(contrato.obligatorios - contrato.claves_cuerpo):
        problemas.append(
            f"[R1] el backend exige «{campo}» (obligatorio en "
            f"{contrato.modelo_cuerpo}) y el frontend no lo manda: "
            f"la respuesta sería 422"
        )

    # R1b: el cliente manda campos que el modelo no tiene -> el backend
    # leería un valor vacío (no un 422, un 401: la sesión moriría igual).
    conocidos = contrato.obligatorios | contrato.opcionales
    for campo in sorted(contrato.claves_cuerpo - conocidos):
        problemas.append(
            f"[R1b] el frontend manda «{campo}» pero "
            f"{contrato.modelo_cuerpo} no tiene ese campo: "
            f"el backend leería un valor vacío (401)"
        )

    # R1c: el endpoint tiene que leer alguno de los campos que se mandan.
    if contrato.claves_cuerpo and not (contrato.claves_cuerpo & contrato.leidos_por_el_backend):
        problemas.append(
            f"[R1c] el endpoint no lee ninguno de los campos que manda el "
            f"frontend ({', '.join(sorted(contrato.claves_cuerpo))})"
        )

    # R2: el cliente lee campos que el modelo de respuesta no tiene.
    for campo in sorted(contrato.campos_respuesta - contrato.campos_respuesta_backend):
        problemas.append(
            f"[R2] el frontend lee «{campo}» de la respuesta pero "
            f"{contrato.modelo_respuesta} no lo tiene"
        )

    # R3: la URL tiene que ser la del backend.
    if contrato.url_relativa != contrato.ruta_relativa_backend:
        problemas.append(
            f"[R3] el frontend llama a «{contrato.url_frontend}» y el backend "
            f"responde en «{contrato.prefijo_api}{contrato.ruta_relativa_backend}»"
        )
    if contrato.prefijo_api and contrato.base_url != contrato.prefijo_api:
        problemas.append(
            f"[R3] el ``baseURL`` del cliente es «{contrato.base_url}» y la API "
            f"se monta en «{contrato.prefijo_api}»"
        )

    return problemas


def verificar(raiz: Path) -> list[str]:
    """Los problemas del contrato en ``raiz`` (vacío = todo encaja)."""
    try:
        contrato = analizar(raiz)
    except _NoSePudoError as exc:
        return [f"[R0] {exc}"]
    return _problemas(contrato)


# ── La autoprueba ─────────────────────────────────────────────────────────


def _copiar(destino: Path) -> None:
    """Copia los ficheros que la puerta mira a ``destino``."""
    for relativo in FICHEROS:
        final = destino / relativo
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAIZ / relativo, final)


def _mutar_exigiendo_access_token(raiz: Path) -> None:
    """El modelo del body vuelve a exigir ``access_token`` (el defecto T-187)."""
    ruta = raiz / SCHEMAS
    texto = _leer(ruta)
    separador = "\r\n" if "\r\n" in texto else "\n"
    texto = texto.replace(
        '    refresh_token: str = ""',
        f'    access_token: str{separador}    refresh_token: str = ""',
    )
    _escribir(ruta, texto)


def _mutar_cuerpo_completo(raiz: Path) -> None:
    """El endpoint vuelve a pedir un ``TokenPair`` COMPLETO (el bug original)."""
    ruta = raiz / AUTH
    texto = _leer(ruta)
    texto = texto.replace("payload: TokenRefreshRequest", "payload: TokenPair")
    _escribir(ruta, texto)


def _mutar_sin_refresh_token(raiz: Path) -> None:
    """El frontend deja de mandar ``refresh_token`` en el body."""
    ruta = raiz / CLIENTE
    texto = _leer(ruta)
    texto = texto.replace("{ refresh_token: refresh }", "{ token: refresh }")
    _escribir(ruta, texto)


def _mutar_campo_renombrado(raiz: Path) -> None:
    """El modelo llama ``token`` al campo que el cliente manda."""
    ruta = raiz / SCHEMAS
    texto = _leer(ruta)
    texto = texto.replace('    refresh_token: str = ""', '    token: str = ""')
    _escribir(ruta, texto)


def _mutar_lectura_del_endpoint(raiz: Path) -> None:
    """El endpoint lee un campo que el frontend NO manda."""
    ruta = raiz / AUTH
    texto = _leer(ruta)
    texto = texto.replace(
        "decode_token(payload.refresh_token)",
        "decode_token(payload.access_token)",
    )
    _escribir(ruta, texto)


def _mutar_sin_expires_in(raiz: Path) -> None:
    """El modelo de respuesta pierde ``expires_in``."""
    ruta = raiz / SCHEMAS
    texto = _leer(ruta)
    texto = re.sub(r"[ \t]*expires_in: int\r?\n", "", texto)
    _escribir(ruta, texto)


#: (nombre, mutación, motivo por el que tiene que fallar).
CASOS_DE_MENTIRA: list[tuple[str, object, str]] = [
    (
        "el modelo del backend vuelve a exigir «access_token»",
        _mutar_exigiendo_access_token,
        "«access_token»",
    ),
    (
        "el endpoint vuelve a pedir un TokenPair completo",
        _mutar_cuerpo_completo,
        "«access_token»",
    ),
    (
        "el frontend deja de mandar «refresh_token»",
        _mutar_sin_refresh_token,
        "«token»",
    ),
    (
        "el modelo renombra el campo a «token»",
        _mutar_campo_renombrado,
        "«refresh_token»",
    ),
    (
        "el endpoint lee un campo que el frontend no manda",
        _mutar_lectura_del_endpoint,
        "[R1c]",
    ),
    (
        "el modelo de respuesta pierde «expires_in»",
        _mutar_sin_expires_in,
        "«expires_in»",
    ),
]


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira y callar con el bueno.

    POR QUÉ existe: una puerta que no puede demostrar que detecta lo que
    dice detectar no es una puerta (y así se ha encontrado una decena en
    este repo).

    OJO (T-135, regla del repo): los casos de mentira se montan **en una
    copia** del repo, en un directorio temporal. Si se pusieran en el sitio,
    al correr el CI en paralelo el job leería el código con el defecto
    puesto y el árbol quedaría sucio (pasó en este repo).
    """
    fallos = 0

    with tempfile.TemporaryDirectory(prefix="contrato_refresh_") as temporal:
        base = Path(temporal)

        # El árbol real tiene que pasar.
        problemas = verificar(RAIZ)
        if problemas:
            fallos += 1
            print("  FALLO: el árbol real ya tiene un desajuste")
            for problema in problemas:
                print(f"      {problema}")
        else:
            print("  OK: el árbol real encaja (el contrato del refresco cuadra)")

        # Y cada caso de mentira tiene que detectarse (en la COPIA).
        for indice, (nombre, mutacion, motivo) in enumerate(CASOS_DE_MENTIRA):
            raiz_caso = base / f"caso_{indice}"
            _copiar(raiz_caso)
            mutacion(raiz_caso)  # type: ignore[operator]
            problemas = verificar(raiz_caso)
            if not problemas:
                fallos += 1
                print(f"  FALLO: {nombre} NO se ha detectado")
            elif not any(motivo in problema for problema in problemas):
                fallos += 1
                print(f"  FALLO: {nombre} se ha detectado, pero no por el motivo esperado")
                for problema in problemas:
                    print(f"      {problema}")
            else:
                print(f"  OK: {nombre} se detecta")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el verificador del contrato del refresco sigue viendo.")
    return 0


# ── Presentación ──────────────────────────────────────────────────────────


def _resumen(contrato: Contrato) -> list[str]:
    """Las líneas del resumen del contrato."""

    def lista(valores: set[str]) -> str:
        return ", ".join(sorted(valores)) if valores else "(ninguno)"

    return [
        f"  baseURL del cliente:         {contrato.base_url}",
        f"  URL que llama el cliente:    {contrato.url_frontend}",
        f"  ruta del backend:            {contrato.prefijo_api}{contrato.ruta_relativa_backend}",
        f"  modelo del cuerpo:           {contrato.modelo_cuerpo}",
        f"  modelo de respuesta:         {contrato.modelo_respuesta}",
        f"  obligatorios del cuerpo:     {lista(contrato.obligatorios)}",
        f"  opcionales del cuerpo:       {lista(contrato.opcionales)}",
        f"  claves que manda el cliente: {lista(contrato.claves_cuerpo)}",
        f"  campos que lee el cliente:   {lista(contrato.campos_respuesta)}",
        f"  campos de la respuesta:      {lista(contrato.campos_respuesta_backend)}",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--autoprueba",
        action="store_true",
        help="Comprueba que el verificador sigue detectando el defecto",
    )
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    print("CONTRATO DE POST /auth/refresh")
    print("=" * 74)
    try:
        contrato = analizar(RAIZ)
    except _NoSePudoError as exc:
        print(f"FALLO: {exc}")
        return 1
    for linea in _resumen(contrato):
        print(linea)
    print()

    problemas = _problemas(contrato)
    if problemas:
        print(f"{len(problemas)} problema(s) en el contrato del refresco:")
        for problema in problemas:
            print(f"  {problema}")
        return 1
    print("OK: el cuerpo del refresco encaja: el frontend manda lo que el backend")
    print("    exige y lee lo que el backend devuelve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
