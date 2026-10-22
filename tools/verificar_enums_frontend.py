"""Comprueba que el frontend conoce TODOS los valores de los enums del backend.

POR QUÉ (2026-10-22): el frontend replica a mano los enumeraciones del
backend, y lo hace en **muchos sitios**:

- ``layouts/AppLayout.vue`` y ``views/cliente/ProfileView.vue`` → el mapa
  de etiquetas de cada rol (dos copias del mismo mapa).
- ``views/admin/UsersView.vue`` → la lista de roles que el admin puede
  asignar.
- ``api/client.ts`` y ``api/gestorOps.ts`` → el tipo ``role`` (dos copias).
- ``views/cliente/TicketsView.vue`` → el tipo ``TicketStatus``.
- ``views/gestor/MovementsView.vue`` y ``views/cliente/TicketsView.vue`` →
  la función ``statusBadge()``, que **etiqueta cualquier estado
  desconocido como "Anulado"**.
- ``views/gestor/AlertsView.vue`` → el mapa de tipos de alerta.
- ``views/gestor/CamerasView.vue`` → el tipo de cámara y el sentido de la
  geocerca.

**Nada lo comparaba.** Hoy los dos lados coinciden, pero si el backend
añade un rol, un tipo de alerta o un estado de ticket:

- el mapa de etiquetas devuelve ``undefined`` y la pantalla muestra un
  hueco (o, en el caso de ``statusBadge``, **dice "Anulado"**, que es una
  afirmación falsa sobre el estado de un ticket);
- el desplegable de "asignar rol" del admin no ofrece el rol nuevo, así
  que el rol nuevo **no se puede asignar desde la interfaz**;
- y nada en el CI se entera, porque todas las puertas comparan cosas
  distintas.

Este script comprueba que, si el frontend conoce algún valor de un enum,
conoce **todos** sus valores.

Uso:
    python tools/verificar_enums_frontend.py
    python tools/verificar_enums_frontend.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENUMS = RAIZ / "backend" / "app" / "models" / "enums.py"
FRONTEND = RAIZ / "frontend" / "src"

#: Literales de cadena en el frontend.
RE_LITERAL = re.compile(r"'([a-z][a-z0-9_]{2,})'")

#: Claves de objeto sin comillas (``camera_offline: 'Cámara caída'``).
RE_CLAVE = re.compile(r"^\s*([a-z][a-z0-9_]{2,})\s*:", re.MULTILINE)


def _enums_del_backend() -> dict[str, set[str]]:
    """``{nombre_del_enum: {valores}}`` leídos del código del backend."""
    arbol = ast.parse(ENUMS.read_text(encoding="utf-8"))
    salida: dict[str, set[str]] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef):
            valores = set()
            for elemento in nodo.body:
                if (
                    isinstance(elemento, ast.Assign)
                    and isinstance(elemento.value, ast.Constant)
                    and isinstance(elemento.value.value, str)
                ):
                    valores.add(elemento.value.value)
            if valores:
                salida[nodo.name] = valores
    return salida


def _ficheros_del_frontend() -> list[Path]:
    return sorted(list(FRONTEND.rglob("*.ts")) + list(FRONTEND.rglob("*.vue")))


def _valores_conocidos(ficheros: list[Path]) -> dict[str, set[str]]:
    """``{valor: {ficheros donde aparece}}`` de los literales del frontend."""
    conocidos: dict[str, set[str]] = {}
    for fichero in ficheros:
        texto = fichero.read_text(encoding="utf-8")
        valores = set(RE_LITERAL.findall(texto)) | set(RE_CLAVE.findall(texto))
        for valor in valores:
            conocidos.setdefault(valor, set()).add(fichero.name)
    return conocidos


def _desajustes(
    enums: dict[str, set[str]], conocidos: dict[str, set[str]]
) -> list[tuple[str, str, str]]:
    """``(enum, valor que falta, donde se usa el enum)`` de cada hueco."""
    huecos: list[tuple[str, str, str]] = []
    for nombre, valores in sorted(enums.items()):
        presentes = [v for v in sorted(valores) if v in conocidos]
        if not presentes:
            # El frontend no usa este enum: no es problema suyo.
            continue
        faltan = [v for v in sorted(valores) if v not in conocidos]
        if not faltan:
            continue
        donde = ", ".join(
            sorted({fichero for valor in presentes for fichero in conocidos[valor]})
        )
        for valor in faltan:
            huecos.append((nombre, valor, donde))
    return huecos


def _autoprueba() -> int:
    """Comprueba que la puerta detecta un valor que el frontend no conoce.

    Se monta el caso de mentira a mano: un enum con un valor que el
    frontend no menciona tiene que salir; y si el frontend menciona
    todos, no tiene que salir nada.
    """
    fallos = 0

    # 1. Un enum con un valor ausente en el frontend -> hueco.
    enums = {"TicketStatus": {"activo", "cerrado", "anulado"}}
    conocidos = {"activo": {"a.ts"}, "cerrado": {"a.ts"}}
    huecos = _desajustes(enums, conocidos)
    if len(huecos) != 1 or huecos[0][1] != "anulado":
        print(f"  FALLO: un valor ausente no se ha detectado ({huecos})")
        fallos += 1
    else:
        print("  OK: un valor que el frontend no conoce se detecta")

    # 2. Si el frontend conoce todos, no hay hueco.
    conocidos = {"activo": {"a.ts"}, "cerrado": {"a.ts"}, "anulado": {"a.ts"}}
    huecos = _desajustes(enums, conocidos)
    if huecos:
        print(f"  FALLO: salen huecos donde no los hay: {huecos}")
        fallos += 1
    else:
        print("  OK: con todos los valores conocidos no sale ningún hueco")

    # 3. Un enum que el frontend no usa no es problema suyo.
    huecos = _desajustes({"NoLoUsa": {"x", "y"}}, {"otra": {"a.ts"}})
    if huecos:
        print(f"  FALLO: un enum que el frontend no usa genera huecos: {huecos}")
        fallos += 1
    else:
        print("  OK: un enum que el frontend no usa no genera huecos")

    # 4. Y el mensaje dice dónde se usa el enum, para que se sepa dónde
    #    tocar.
    huecos = _desajustes(enums, {"activo": {"a.ts"}})
    if not huecos or "a.ts" not in huecos[0][2]:
        print("  FALLO: el hueco no dice dónde se usa el enum")
        fallos += 1
    else:
        print("  OK: el hueco dice dónde se usa el enum")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de enums sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando valores ausentes")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    enums = _enums_del_backend()
    conocidos = _valores_conocidos(_ficheros_del_frontend())

    usados = [
        (nombre, valores) for nombre, valores in sorted(enums.items())
        if any(v in conocidos for v in valores)
    ]
    print(f"enums del backend:        {len(enums)}")
    print(f"enums que usa el frontend: {len(usados)}")

    huecos = _desajustes(enums, conocidos)
    if huecos:
        print(f"\nVALORES DE ENUM QUE EL FRONTEND NO CONOCE ({len(huecos)}):")
        for nombre, valor, donde in huecos:
            print(f"  - {nombre}.{valor}  (se usa en: {donde})")
        print("\nEl frontend tiene que poder mostrar CUALQUIER valor que el")
        print("backend pueda devolver: si no, la pantalla muestra un hueco,")
        print("y en el caso de statusBadge() diria 'Anulado' (que es falso).")
        return 1

    print("\nOK: el frontend conoce todos los valores de los enums que usa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
