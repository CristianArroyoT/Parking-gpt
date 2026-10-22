#!/usr/bin/env python3
"""Puerta: las dependencias de PRODUCCIÓN no tienen vulnerabilidades conocidas.

POR QUÉ ESTA PUERTA EXISTE (2026-10-23)
--------------------------------------
El repo no miraba **nunca** las vulnerabilidades de sus dependencias. Se
descubrieron dos, midiendo contra el sistema en marcha:

1. **El backend tenía 68 avisos abiertos en Pillow 10.4.0** (OSV), y el
   código **abre las imágenes que suben los usuarios**
   (``app/services/incident_attachments.py``): una foto manipulada podía
   tumbar el servicio (bombas de descompresión, desbordamientos de búfer,
   bucles infinitos). El pin era ``pillow>=10.0,<11.0``: la mayor
   VERSION_MAYOR nunca ha estado libre de avisos.
2. **El frontend tenía 7 avisos ``high`` en el árbol de producción**
   (``npm audit --omit=dev``): ``vue``, ``axios``, ``postcss``,
   ``nanoid``, ``follow-redirects``, ``source-map-js`` y
   ``@vue/server-renderer``. Son los paquetes que se **envían al
   navegador**.

QUÉ MIDE ESTA PUERTA (y qué no)
-------------------------------
- **FATAL · backend**: las dependencias **directas** que declara
  ``backend/pyproject.toml``. Son las que elegimos nosotros: si una
  tiene un aviso, la decisión es nuestra y se arregla (subiendo la
  versión) o se justifica por escrito.
- **FATAL · frontend**: los paquetes del ``package-lock.json`` que **no**
  son de desarrollo (``dev`` ausente), directos **y** transitivos: es el
  mismo criterio que ``npm audit --omit=dev``, y el lockfile fija las
  versiones exactas que se envían al navegador.
- **INFORMATIVO · backend**: el resto del árbol transitivo (lo que
  arrastran fastapi, starlette, celery...). Se **informa** con el
  número de avisos y la versión que los arregla, pero no rompe la
  puerta: no son una decisión nuestra y el backend **no tiene
  lockfile** (las versiones dependen de cuándo se construyó la
  imagen). Medido el 2026-10-23: mirando el árbol transitivo entero la
  puerta daba **119 avisos** de los que sólo 69 eran de dependencias
  directas. Una puerta que grita de más es una puerta que nadie mira.

Las vulnerabilidades **de desarrollo** (vite, tailwind 3, eslint) se
informan con ``--incluir-dev``: su arreglo exige migraciones mayores
(tailwind 4, vite 8) que no se pueden hacer a ciegas, y no viajan al
cliente.

CÓMO FUNCIONA
-------------
Consulta **OSV** (la base de vulnerabilidades de código abierto que
alimenta ``pip-audit`` y ``npm audit``). Si OSV no responde, la puerta
devuelve el **código 3** ("no comprobado"), que **no** es verde: un
"verde" sin red sería una mentira.

Los avisos de OSV vienen duplicados (el mismo problema con un
identificador ``GHSA-…`` y otro ``PYSEC-…``): aquí se **agrupan por
alias** y se cuenta cada problema **una vez**.

Las excepciones están en ``tools/dependencias_aceptadas.json`` y cada
una necesita un motivo escrito y una prueba que la respalde. Una
excepción sin motivo es un fallo de la puerta.

USO
----
    python tools/verificar_dependencias.py            # la puerta
    python tools/verificar_dependencias.py --autoprueba
    python tools/verificar_dependencias.py --incluir-dev
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"

#: Todo correcto.
CODIGO_OK = 0
#: Hay vulnerabilidades sin justificar.
CODIGO_FALLA = 1
#: No se pudo comprobar (OSV no respondió): NO es verde.
CODIGO_NO_COMPROBADO = 3

ECO_PYPI = "PyPI"
ECO_NPM = "npm"


# ── Paquetes: qué se comprueba y con qué alcance ────────────────────────


def _normalizar(nombre: str) -> str:
    return nombre.strip().lower().replace("_", "-")


def _dependencias_directas(pyproject: Path) -> list[str]:
    """Las dependencias DIRECTAS que declara ``backend/pyproject.toml``.

    Se leen del fichero, no del entorno: lo que el proyecto declara es
    lo que hay que auditar, y el cierre transitivo se resuelve contra
    lo instalado.
    """
    import tomllib

    with open(pyproject, "rb") as f:
        datos = tomllib.load(f)
    proyecto = datos.get("project", {})
    directas = list(proyecto.get("dependencies", []))
    for extra in (proyecto.get("optional-dependencies") or {}).values():
        directas.extend(extra)
    nombres: list[str] = []
    for requisito in directas:
        limpio = requisito.split(";")[0].strip()
        for separador in ("[", "<", ">", "=", "!", "~", " "):
            limpio = limpio.split(separador)[0]
        if limpio:
            nombres.append(_normalizar(limpio))
    return sorted(set(nombres))


def _cierre_dependencias(directas: list[str]) -> list[tuple[str, str]]:
    """El árbol de dependencias del proyecto: directas + transitivas.

    POR QUÉ el cierre y no "todo lo instalado": el intérprete del host
    tiene **además** paquetes que no son del proyecto (pip, setuptools,
    herramientas del sistema). Medido el 2026-10-23: mirando todo lo
    instalado la puerta daba **260 avisos** de los que sólo 68 eran
    reales; el resto era ruido ajeno al proyecto.
    """
    from importlib import metadata

    vistos: set[str] = set()
    pendientes = list(directas)
    while pendientes:
        nombre = _normalizar(pendientes.pop())
        if nombre in vistos:
            continue
        try:
            dist = metadata.distribution(nombre)
        except metadata.PackageNotFoundError:
            continue
        vistos.add(nombre)
        for requisito in dist.requires or []:
            if ";" in requisito:  # marcadores de entorno (sys_platform, ...)
                continue
            limpio = requisito.split(";")[0].strip()
            for separador in ("[", "<", ">", "=", "!", "~", " "):
                limpio = limpio.split(separador)[0]
            if limpio:
                pendientes.append(limpio)
    salida: list[tuple[str, str]] = []
    for nombre in sorted(vistos):
        try:
            salida.append((nombre, metadata.version(nombre)))
        except metadata.PackageNotFoundError:  # pragma: no cover
            continue
    return salida


def _paquetes_produccion_frontend(lock: dict[str, Any]) -> list[tuple[str, str]]:
    """Paquetes de **producción** del lockfile v2/v3: ``(nombre, version)``.

    En el lockfile v3, un paquete que sólo se alcanza desde
    ``devDependencies`` lleva ``"dev": true``. Los que no lo llevan
    forman parte del árbol de producción (el mismo criterio que
    ``npm audit --omit=dev``).
    """
    paquetes = lock.get("packages")
    if isinstance(paquetes, dict):
        salida: list[tuple[str, str]] = []
        for ruta, meta in paquetes.items():
            if ruta == "" or not isinstance(meta, dict):
                continue
            if meta.get("dev"):
                continue
            nombre = meta.get("name") or ruta.split("node_modules/")[-1]
            version = meta.get("version")
            if version:
                salida.append((str(nombre).lower(), str(version)))
        return sorted(set(salida))

    def _recorrer(bloque: dict[str, Any], es_dev: bool) -> list[tuple[str, str]]:
        acc: list[tuple[str, str]] = []
        for nombre, meta in bloque.items():
            if not isinstance(meta, dict):
                continue
            version = meta.get("version")
            if version and not es_dev:
                acc.append((str(nombre).lower(), str(version)))
            if "dependencies" in meta:
                acc += _recorrer(meta["dependencies"], es_dev or bool(meta.get("dev")))
            if "optionalDependencies" in meta:
                acc += _recorrer(meta["optionalDependencies"], es_dev)
        return acc

    return sorted(set(_recorrer(lock.get("dependencies", {}), False)))


def _paquetes_desarrollo_frontend(lock: dict[str, Any]) -> list[tuple[str, str]]:
    """Paquetes de **desarrollo** del lockfile (informativos)."""
    salida: list[tuple[str, str]] = []
    for ruta, meta in (lock.get("packages") or {}).items():
        if ruta == "" or not isinstance(meta, dict):
            continue
        if not meta.get("dev"):
            continue
        version = meta.get("version")
        if version:
            nombre = meta.get("name") or ruta.split("node_modules/")[-1]
            salida.append((str(nombre).lower(), str(version)))
    return sorted(set(salida))


# ── Consulta a OSV ───────────────────────────────────────────────────────


def _post_json(url: str, payload: dict[str, Any], intentos: int = 3) -> dict[str, Any]:
    """POST a OSV con reintentos (un fallo puntual no es una puerta rota)."""
    ultimo_error: Exception | None = None
    for intento in range(intentos):
        try:
            peticion = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            ultimo_error = exc
            if intento + 1 < intentos:
                time.sleep(2 * (intento + 1))
    raise RuntimeError(f"no se pudo contactar con OSV: {ultimo_error}")


def consultar_osv(paquetes: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Devuelve los avisos de OSV para ``(ecosistema, nombre, version)``."""
    if not paquetes:
        return []
    consultas = [
        {"package": {"name": nombre, "ecosystem": eco}, "version": version}
        for eco, nombre, version in paquetes
    ]
    lote = _post_json(OSV_BATCH, {"queries": consultas})
    ids: set[str] = set()
    for resultado in lote.get("results", []):
        for aviso in resultado.get("vulns", []) or []:
            if isinstance(aviso, dict) and aviso.get("id"):
                ids.add(str(aviso["id"]))
    avisos: list[dict[str, Any]] = []
    for identificador in sorted(ids):
        try:
            with urllib.request.urlopen(f"{OSV_VULN}{identificador}", timeout=60) as r:
                avisos.append(json.loads(r.read().decode("utf-8")))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Un aviso que no se puede detallar se cuenta como detectado:
            # mejor señalar de más que dejar pasar uno.
            avisos.append({"id": identificador, "summary": "(detalle no disponible)"})
    return avisos


# ── Agrupación por alias (el mismo problema con dos identificadores) ────


def _grupos_por_alias(avisos: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Agrupa los avisos que son **el mismo problema**.

    OSV publica el mismo fallo dos veces (p. ej. ``GHSA-3qf3-8w2g-rqmx`` y
    ``PYSEC-2026-4298``). Cada aviso lista a los otros como alias, pero no
    siempre en los dos sentidos: por eso se agrupan por **componentes
    conexas** (unión por Find) y no por "el primero que aparezca".

    Sin esto, un problema con dos identificadores se contaba dos veces y
    la excepción escrita para uno no cubría al otro.
    """
    padre: dict[str, str] = {}

    def _buscar(nodo: str) -> str:
        padre.setdefault(nodo, nodo)
        while padre[nodo] != nodo:
            padre[nodo] = padre[padre[nodo]]
            nodo = padre[nodo]
        return nodo

    def _unir(a: str, b: str) -> None:
        ra, rb = _buscar(a), _buscar(b)
        if ra != rb:
            padre[rb] = ra

    for aviso in avisos:
        identificador = str(aviso.get("id", ""))
        if not identificador:
            continue
        _buscar(identificador)
        for alias in aviso.get("aliases") or []:
            _unir(identificador, str(alias))

    grupos: dict[str, list[dict[str, Any]]] = {}
    for aviso in avisos:
        identificador = str(aviso.get("id", ""))
        if not identificador:
            continue
        raiz = _buscar(identificador)
        grupos.setdefault(raiz, []).append(aviso)
    return grupos


def _canonico(grupo: list[dict[str, Any]]) -> str:
    """Identificador único del problema: el GHSA si lo hay."""
    identificadores = {str(a.get("id", "")) for a in grupo}
    for alias in grupo:
        identificadores |= {str(x) for x in (alias.get("aliases") or [])}
    ghsa = sorted(i for i in identificadores if i.startswith("GHSA-"))
    return ghsa[0] if ghsa else sorted(identificadores)[0]


def _versiones_arregladas(aviso: dict[str, Any]) -> list[str]:
    fijadas: list[str] = []
    for afectado in aviso.get("affected", []) or []:
        for rango in afectado.get("ranges", []) or []:
            for evento in rango.get("events", []) or []:
                if "fixed" in evento:
                    fijadas.append(str(evento["fixed"]))
    return sorted(set(fijadas))


# ── Excepciones ──────────────────────────────────────────────────────────


def cargar_aceptadas(ruta: Path | None = None) -> dict[str, dict[str, Any]]:
    """Excepciones declaradas (paquete + id de aviso → motivo y prueba)."""
    ruta = ruta or (RAIZ / "tools" / "dependencias_aceptadas.json")
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    aceptadas: dict[str, dict[str, Any]] = {}
    for entrada in datos.get("aceptadas", []):
        clave = f"{_normalizar(str(entrada.get('paquete', '')))}::{entrada.get('aviso', '')}"
        aceptadas[clave] = entrada
    return aceptadas


def _motivo_vacio(entrada: dict[str, Any]) -> bool:
    """Una excepción sin motivo (o sin prueba) no es una excepción."""
    return not str(entrada.get("motivo", "")).strip() or not str(
        entrada.get("prueba", "")
    ).strip()


# ── Lógica de la puerta (pura: la autoprueba la puede ejercitar sin red) ─


def evaluar(
    fatales: list[tuple[str, str, str]],
    avisos: list[dict[str, Any]],
    aceptadas: dict[str, dict[str, Any]],
    informativos: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Cruza los avisos con las excepciones y decide el veredicto.

    ``fatales`` e ``informativos`` son tripletas
    ``(ecosistema, nombre, version)``.
    """
    indices: dict[str, list[tuple[str, str, str]]] = {}
    for eco, nombre, version in fatales + list(informativos or []):
        indices.setdefault(_normalizar(nombre), []).append((eco, nombre, version))

    # Un aviso por problema (agrupado por alias, en los dos sentidos).
    por_problema: dict[str, dict[str, Any]] = {}
    for grupo in _grupos_por_alias(avisos).values():
        clave = _canonico(grupo)
        if clave not in por_problema:
            por_problema[clave] = {
                "id": clave,
                "resumen": grupo[0].get("summary", ""),
                "arreglado": [],
                "afectados": set(),
            }
        entrada = por_problema[clave]
        for aviso in grupo:
            for afectado in aviso.get("affected", []) or []:
                nombre = _normalizar(str(afectado.get("package", {}).get("name", "")))
                if nombre in indices:
                    for eco, n, v in indices[nombre]:
                        entrada["afectados"].add((eco, n, v))
            if not entrada["arreglado"]:
                entrada["arreglado"] = _versiones_arregladas(aviso)

    fallos: list[dict[str, Any]] = []
    aceptados: list[dict[str, Any]] = []
    sin_motivo: list[dict[str, Any]] = []
    informativos_salida: list[dict[str, Any]] = []

    for clave, problema in por_problema.items():
        afectados = sorted(problema["afectados"])
        if not afectados:
            continue
        es_fatal = any((e, n, v) in fatales for e, n, v in afectados)
        if not es_fatal:
            for _eco, nombre, version in afectados:
                informativos_salida.append(
                    {
                        "paquete": nombre,
                        "version": version,
                        "aviso": clave,
                        "resumen": problema["resumen"],
                        "arreglado": problema["arreglado"],
                    }
                )
            continue
        paquete = afectados[0][1]
        entrada = aceptadas.get(f"{_normalizar(paquete)}::{clave}")
        if entrada is None:
            fallos.append(
                {
                    "aviso": clave,
                    "resumen": problema["resumen"],
                    "paquetes": sorted({f"{n}=={v}" for _e, n, v in afectados}),
                    "arreglado": problema["arreglado"],
                }
            )
        elif _motivo_vacio(entrada):
            sin_motivo.append(
                {"aviso": clave, "paquete": paquete, "motivo": entrada.get("motivo", "")}
            )
        else:
            aceptados.append(
                {
                    "aviso": clave,
                    "paquete": paquete,
                    "motivo": entrada["motivo"],
                    "prueba": entrada["prueba"],
                }
            )
    return {
        "fallos": fallos,
        "aceptados": aceptados,
        "sin_motivo": sin_motivo,
        "informativos": informativos_salida,
        "comprobados": len(fatales),
    }


# ── Autoprueba (casos de mentira escritos a mano) ────────────────────────


def _autoprueba() -> int:
    """Comprueba que la puerta detecta lo que dice detectar.

    Los casos de mentira están escritos **a mano** aquí: son la tercera
    fuente. Si la puerta comparase el repositorio contra sí mismo, los
    dos podrían mentir a la vez.
    """
    fallos: list[str] = []

    aviso_mentira = {
        "id": "GHSA-0000-0000-0000",
        "summary": "Paquete de mentira con vulnerabilidad de mentira",
        "affected": [{"package": {"name": "paquete-de-mentira", "ecosystem": "PyPI"}}],
    }
    veredicto = evaluar(
        [("PyPI", "paquete-de-mentira", "1.0.0")], [aviso_mentira], {},
    )
    if not veredicto["fallos"]:
        fallos.append("caso 1: una vulnerabilidad real no se ha detectado")
    elif veredicto["fallos"][0]["aviso"] != "GHSA-0000-0000-0000":
        fallos.append("caso 1: el aviso detectado no es el que se puso")

    # ── Caso 2: el mismo aviso con una excepción SIN motivo ──
    veredicto = evaluar(
        [("PyPI", "paquete-de-mentira", "1.0.0")],
        [aviso_mentira],
        {"paquete-de-mentira::GHSA-0000-0000-0000": {"motivo": "  ", "prueba": ""}},
    )
    if not veredicto["sin_motivo"]:
        fallos.append("caso 2: una excepción sin motivo no se ha detectado")
    if veredicto["fallos"]:
        fallos.append("caso 2: la excepción sin motivo no debería fallar la puerta")

    # ── Caso 3: la excepción con motivo SÍ se acepta ──
    veredicto = evaluar(
        [("PyPI", "paquete-de-mentira", "1.0.0")],
        [aviso_mentira],
        {
            "paquete-de-mentira::GHSA-0000-0000-0000": {
                "motivo": "no es alcanzable: los algoritmos se restringen",
                "prueba": "tests/test_login_hardening.py",
            }
        },
    )
    if veredicto["fallos"]:
        fallos.append("caso 3: una excepción justificada no debería fallar la puerta")
    if not veredicto["aceptados"]:
        fallos.append("caso 3: la excepción justificada no se ha registrado")

    # ── Caso 4: un aviso que NO afecta a los paquetes comprobados ──
    veredicto = evaluar([("PyPI", "otro-paquete", "2.0.0")], [aviso_mentira], {})
    if veredicto["fallos"]:
        fallos.append("caso 4: la puerta ha acusado a un paquete que no comprueba")

    # ── Caso 5: el alcance (producción vs desarrollo) ──
    lock_mentira = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app", "dependencies": {"axios": "^1.0.0"}},
            "node_modules/axios": {"version": "1.0.0"},
            "node_modules/vite": {"version": "5.0.0", "dev": True},
            "node_modules/eslint": {"version": "9.0.0", "dev": True},
        },
    }
    produccion = {n for n, _v in _paquetes_produccion_frontend(lock_mentira)}
    desarrollo = {n for n, _v in _paquetes_desarrollo_frontend(lock_mentira)}
    if "axios" not in produccion:
        fallos.append("caso 5: una dependencia de producción no se ha visto")
    if "vite" in produccion or "eslint" in produccion:
        fallos.append("caso 5: una dependencia de desarrollo se ha colado en producción")
    if "vite" not in desarrollo or "eslint" not in desarrollo:
        fallos.append("caso 5: las dependencias de desarrollo no se han visto")

    # ── Caso 6: el mismo problema con dos identificadores se cuenta una vez ──
    gemelo = {
        "id": "PYSEC-2026-9999",
        "summary": "El mismo problema, otro identificador",
        "aliases": ["GHSA-1111-2222-3333"],
        "affected": [{"package": {"name": "paquete-de-mentira", "ecosystem": "PyPI"}}],
    }
    aviso_mentira["aliases"] = ["PYSEC-2026-9999"]
    veredicto = evaluar(
        [("PyPI", "paquete-de-mentira", "1.0.0")], [aviso_mentira, gemelo], {},
    )
    if len(veredicto["fallos"]) != 1:
        fallos.append(
            f"caso 6: dos identificadores del mismo problema se han contado "
            f"{len(veredicto['fallos'])} veces (debería ser 1)"
        )

    # ── Caso 7: lo transitivo no rompe la puerta, pero se informa ──
    aviso_transitivo = {
        "id": "GHSA-4444-4444-4444",
        "summary": "Aviso de una dependencia transitiva",
        "affected": [{"package": {"name": "transitivo", "ecosystem": "PyPI"}}],
    }
    veredicto = evaluar(
        [("PyPI", "directo", "1.0.0")],
        [aviso_transitivo],
        {},
        informativos=[("PyPI", "transitivo", "1.0.0")],
    )
    if veredicto["fallos"]:
        fallos.append("caso 7: un aviso de una dependencia transitiva ha roto la puerta")
    if not veredicto["informativos"]:
        fallos.append("caso 7: un aviso transitivo no se ha informado")

    if fallos:
        print("AUTOPRUEBA FALLIDA:")
        for f in fallos:
            print(" -", f)
        return CODIGO_FALLA
    print("autoprueba de verificar_dependencias.py: OK (7 casos)")
    return CODIGO_OK


# ── Programa principal ───────────────────────────────────────────────────


def _recolectar(raiz: Path, incluir_dev: bool) -> tuple[list, list, list]:
    """Devuelve ``(fatales, informativos, todos)`` como tripletas."""
    fatales: list[tuple[str, str, str]] = []
    informativos: list[tuple[str, str, str]] = []
    pyproject = raiz / "backend" / "pyproject.toml"
    if pyproject.exists():
        directas = set(_dependencias_directas(pyproject))
        cierre = _cierre_dependencias(sorted(directas))
        for nombre, version in cierre:
            tripleta = (ECO_PYPI, nombre, version)
            if nombre in directas:
                fatales.append(tripleta)
            else:
                informativos.append(tripleta)
    lock_path = raiz / "frontend" / "package-lock.json"
    if lock_path.exists():
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
        for nombre, version in _paquetes_produccion_frontend(lock):
            fatales.append((ECO_NPM, nombre, version))
        if incluir_dev:
            for nombre, version in _paquetes_desarrollo_frontend(lock):
                informativos.append((ECO_NPM, nombre, version))
    return sorted(set(fatales)), sorted(set(informativos)), sorted(set(fatales + informativos))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Puerta de dependencias vulnerables")
    parser.add_argument("--autoprueba", action="store_true", help="comprueba la puerta")
    parser.add_argument("--raiz", default=str(RAIZ), help="raíz del repositorio")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.add_argument(
        "--incluir-dev",
        action="store_true",
        help="informa también de las dependencias de desarrollo",
    )
    args = parser.parse_args(argv)

    if args.autoprueba:
        return _autoprueba()

    raiz = Path(args.raiz)
    fatales, informativos, todos = _recolectar(raiz, args.incluir_dev)
    if not todos:
        print("verificar_dependencias: no hay paquetes que comprobar", file=sys.stderr)
        return CODIGO_NO_COMPROBADO

    try:
        avisos = consultar_osv(todos)
    except RuntimeError as exc:
        print(f"verificar_dependencias: {exc}", file=sys.stderr)
        print("verificar_dependencias: NO COMPROBADO (no es verde)", file=sys.stderr)
        return CODIGO_NO_COMPROBADO

    aceptadas = cargar_aceptadas()
    veredicto = evaluar(fatales, avisos, aceptadas, informativos)

    if args.json:
        print(json.dumps(veredicto, ensure_ascii=False, indent=2))
    else:
        print(f"dependencias comprobadas (alcance fatal): {veredicto['comprobados']}")
        print(
            f"problemas con vulnerabilidad en el alcance fatal: "
            f"{len(veredicto['fallos']) + len(veredicto['aceptados'])}"
        )
        for aceptado in veredicto["aceptados"]:
            print(
                f"  [aceptado] {aceptado['paquete']} · {aceptado['aviso']}: "
                f"{aceptado['motivo']} (prueba: {aceptado['prueba']})"
            )
        for fallo in veredicto["fallos"]:
            arreglado = ", ".join(fallo["arreglado"]) if fallo["arreglado"] else "sin versión arreglada"
            print(
                f"  [FALLA] {', '.join(fallo['paquetes'])} · {fallo['aviso']}: "
                f"{fallo['resumen']} (arreglado en {arreglado})"
            )
        for sin in veredicto["sin_motivo"]:
            print(
                f"  [FALLA] {sin['paquete']} · {sin['aviso']}: la excepción no "
                "tiene motivo ni prueba"
            )
        if veredicto["informativos"]:
            print("")
            print("informativo (no rompe la puerta):")
            vistos: dict[str, dict[str, Any]] = {}
            for info in veredicto["informativos"]:
                clave = f"{info['paquete']}=={info['version']}"
                if clave not in vistos:
                    vistos[clave] = {**info, "avisos": set()}
                vistos[clave]["avisos"].add(info["aviso"])
            for clave, info in sorted(vistos.items()):
                arreglado = ", ".join(info["arreglado"]) if info["arreglado"] else "sin versión arreglada"
                print(
                    f"  - {clave}: {len(info['avisos'])} aviso/s "
                    f"(arreglado en {arreglado})"
                )

    if veredicto["fallos"] or veredicto["sin_motivo"]:
        return CODIGO_FALLA
    return CODIGO_OK


if __name__ == "__main__":
    sys.exit(main())
