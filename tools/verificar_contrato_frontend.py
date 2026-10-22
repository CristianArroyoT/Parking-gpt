"""Comprueba que el frontend llama a endpoints que existen.

POR QUÉ (2026-10-22): el frontend tiene su propio cliente HTTP
(``frontend/src/api/``) y la QA visual sólo recorre 21 pantallas. Un
endpoint mal escrito, o una ruta que el backend renombró, se esconde
hasta que un usuario llega a esa pantalla. Este verificador compara, de
forma estática, **cada ruta que el cliente pide** con **las rutas que
el backend expone**.

No sustituye a la QA (una llamada puede existir y aun así fallar en
tiempo de ejecución), pero encuentra lo que la QA no ve: endpoints que
el backend **no** tiene, o con el método equivocado.

Uso:
    python tools/verificar_contrato_frontend.py
    python tools/verificar_contrato_frontend.py --detalle
    python tools/verificar_contrato_frontend.py --autoprueba
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
API_FRONTEND = RAIZ / "frontend" / "src" / "api"
VISTAS = RAIZ / "frontend" / "src" / "views"

#: ``http.get('/ruta')`` o ``http.post<Algo>(`/ruta/${id}`)``.
#: La ruta puede estar en la línea siguiente (por eso se usa ``\s*``, que
#: también salta los saltos de línea).
RELLAMADA = re.compile(
    r"http\.(get|post|put|patch|delete)\s*(?:<[^;]{0,200}?>)?\s*\(\s*"
    r"[`'\"]\s*([^`'\"]+?)\s*[`'\"]",
    re.DOTALL,
)

#: ``${variable}`` dentro de una plantilla de JS.
RE_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")


def _forma(ruta: str) -> str:
    """La ruta con los parámetros normalizados a ``{}``.

    Se normalizan los dos lados: el frontend escribe ``${parkingId}`` y
    el backend ``{parking_id}``. Los dos se quedan en ``{}``.

    La **query string** se quita antes de comparar: ``/alerts?type=x``
    y ``/alerts`` son la misma ruta para el backend (los query params
    no forman parte del camino).
    """
    ruta = ruta.split("?", 1)[0]
    ruta = RE_PLACEHOLDER.sub("{}", ruta)
    return re.sub(r"\{[^}]*\}", "{}", ruta)


def _rutas_del_backend() -> set[tuple[str, str]]:
    """(método, ruta) de todo lo que expone el backend."""
    rutas: set[tuple[str, str]] = set()
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        for metodo, ruta, _quien, _modulo in extraer_de_modulo(fichero):
            rutas.add((metodo.upper(), _forma(ruta)))
    # Los endpoints de salud los define ``create_app``, fuera de los routers.
    rutas.add(("GET", "/health"))
    rutas.add(("GET", "/health/ready"))
    return rutas


def _llamadas_del_frontend() -> list[tuple[str, str, str]]:
    """(método, ruta, fichero) de cada llamada HTTP del cliente.

    Se miran **dos** sitios, y los dos hacen falta:

      * los módulos de ``frontend/src/api/`` (39 llamadas), que son el
        cliente HTTP propiamente dicho;
      * las **vistas**, que hacen unas 40 llamadas más con
        ``http.get(...)`` escrito a mano, sin pasar por los módulos.

    Mirar sólo los módulos dejaría fuera de la comprobación casi la
    mitad del cliente.
    """
    encontradas: list[tuple[str, str, str]] = []
    for fichero in sorted(API_FRONTEND.glob("*.ts")):
        texto = fichero.read_text(encoding="utf-8")
        for metodo, ruta in RELLAMADA.findall(texto):
            encontradas.append((metodo.upper(), _forma(ruta), fichero.name))
    for fichero in sorted(VISTAS.rglob("*.vue")):
        texto = fichero.read_text(encoding="utf-8")
        for metodo, ruta in RELLAMADA.findall(texto):
            encontradas.append((metodo.upper(), _forma(ruta), f"vistas/{fichero.name}"))
    return encontradas


def _problemas(
    llamadas: list[tuple[str, str, str]], backend: set[tuple[str, str]]
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str, str]]]:
    """(rutas inexistentes, rutas con el método equivocado)."""
    por_metodo: dict[str, set[str]] = {}
    for metodo, ruta in backend:
        por_metodo.setdefault(metodo, set()).add(ruta)
    cualquiera = {ruta for _m, ruta in backend}

    sin_ruta: list[tuple[str, str, str]] = []
    sin_metodo: list[tuple[str, str, str, str]] = []
    for metodo, ruta, fichero in llamadas:
        # El cliente habla en rutas relativas: el prefijo lo pone axios.
        completa = ruta if ruta.startswith("/api/v1") else "/api/v1" + ruta
        if completa in por_metodo.get(metodo, set()):
            continue
        if completa in cualquiera:
            sin_metodo.append((metodo, ruta, fichero, completa))
            continue
        sin_ruta.append((metodo, ruta, fichero))
    return sin_ruta, sin_metodo


def _autoprueba() -> int:
    """Comprueba que el verificador SIGUE detectando un desajuste.

    Una puerta que no se puede ver fallar no es una puerta: si el
    emparejador de rutas dejara de casar **de más**, todo el cliente
    parecería correcto y la puerta pasaría en vacío.
    """
    backend = _rutas_del_backend()
    llamadas = _llamadas_del_frontend()
    fallos = 0

    sin_ruta, sin_metodo = _problemas(llamadas, backend)
    if sin_ruta or sin_metodo:
        fallos += 1
        print("  FALLO: el cliente real ya tiene un desajuste")
    else:
        print(f"  OK: el cliente real encaja ({len(llamadas)} llamadas)")

    # 1. Una ruta que el backend NO tiene tiene que detectarse.
    inventada = ("GET", "/api/v1/no-existe/xyz", "prueba.ts")
    sin_ruta, _ = _problemas([inventada], backend)
    if not sin_ruta:
        fallos += 1
        print("  FALLO: una ruta inexistente NO se ha detectado")
    else:
        print("  OK: una ruta que el backend no tiene se detecta")

    # 2. Una ruta que existe pero con otro metodo, tambien.
    if backend:
        metodo_real, ruta_real = sorted(backend)[0]
        otro = "POST" if metodo_real != "POST" else "GET"
        mal = (otro, ruta_real, "prueba.ts")
        _sin_ruta, sin_metodo = _problemas([mal], backend)
        if not sin_metodo:
            fallos += 1
            print("  FALLO: un metodo equivocado NO se ha detectado")
        else:
            print(f"  OK: un metodo equivocado se detecta ({otro} {ruta_real})")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: el verificador de contrato sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que el verificador sigue detectando desajustes")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    backend = _rutas_del_backend()
    llamadas = _llamadas_del_frontend()

    print(f"endpoints del backend:  {len(backend)}")
    print(f"llamadas del frontend:  {len(llamadas)}")

    sin_ruta, sin_metodo = _problemas(llamadas, backend)

    if sin_metodo:
        print(f"\nLa ruta existe pero con OTRO metodo ({len(sin_metodo)}):")
        for metodo, ruta, fichero, completa in sin_metodo:
            metodos = ", ".join(sorted(m for m, r in backend if r == completa))
            print(f"  {metodo:6} {ruta:44} [{fichero}] -> el backend usa {metodos}")

    if sin_ruta:
        print(f"\nRUTAS QUE EL BACKEND NO TIENE ({len(sin_ruta)}):")
        for metodo, ruta, fichero in sin_ruta:
            print(f"  {metodo:6} {ruta:44} [{fichero}]")

    if args.detalle:
        print("\nLlamadas que si existen:")
        for metodo, ruta, fichero in llamadas:
            if (metodo, ruta, fichero) not in sin_ruta:
                print(f"  {metodo:6} {ruta:44} [{fichero}]")

    if sin_ruta or sin_metodo:
        print(f"\n{len(sin_ruta)} ruta(s) inexistente(s) y "
              f"{len(sin_metodo)} con el metodo equivocado.")
        return 1
    print("\nOK: el frontend llama a endpoints que existen, con el metodo correcto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
