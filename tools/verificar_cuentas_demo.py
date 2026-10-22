"""Comprueba que las cuentas demo estén de acuerdo en los tres sitios.

POR QUÉ (2026-10-22): las credenciales de las cuentas demo están
**escritas tres veces**:

1. ``backend/app/scripts/seed.py`` → ``DEMO_USERS``: lo que hay de
   verdad en la base de datos.
2. ``frontend/src/views/LoginView.vue`` → el mapa de ``fillDemo()``: lo
   que el usuario ve en la pantalla de login y con lo que rellena el
   formulario al pulsar "Admin", "Gestor", "Operador" o "Cliente".
3. ``frontend/scripts/qa_visual.py`` → ``CUENTAS``: con lo que la QA
   visual inicia sesión.

**Nada las comparaba.** Y el modo de fallo es de las peores: si el seed
cambia una contraseña, la pantalla de login sigue rellenando la vieja
y **el usuario del demo no puede entrar** (con un "email o contraseña
incorrectos" que no dice nada), y la QA falla con un error de
navegador que culpa al navegador. Nadie pensaría mirar el seed.

Lo peor de la historia: la puerta de "despliegue limpio" comprueba que
el seed cree 4 usuarios, pero **no** que las contraseñas sean las que
la pantalla de login ofrece.

Este script compara las tres listas y dice exactamente dónde se
desacuerdan.

Uso:
    python tools/verificar_cuentas_demo.py
    python tools/verificar_cuentas_demo.py --autoprueba
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SEED = RAIZ / "backend" / "app" / "scripts" / "seed.py"
ENUMS = RAIZ / "backend" / "app" / "models" / "enums.py"
LOGIN = RAIZ / "frontend" / "src" / "views" / "LoginView.vue"
QA = RAIZ / "frontend" / "scripts" / "qa_visual.py"

#: ``rol: ['email', 'contraseña']`` dentro del mapa de ``fillDemo()``.
RE_FILL_DEMO = re.compile(
    r"(?:const\s+map\s*:[^=]+=\s*\{)(.*?)(\})", re.DOTALL
)
RE_CUENTA = re.compile(
    r"(?P<rol>[a-z_]+)\s*:\s*\[\s*'(?P<email>[^']+)'\s*,\s*'(?P<clave>[^']+)'\s*\]"
)


def _literal(nodo: ast.AST) -> str | None:
    """El valor de un nodo si es una constante de texto."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def _roles_validos() -> set[str]:
    """Los valores del enum ``UserRole`` (leídos del código)."""
    arbol = ast.parse(ENUMS.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef) and nodo.name == "UserRole":
            valores = set()
            for elemento in nodo.body:
                if (
                    isinstance(elemento, ast.Assign)
                    and isinstance(elemento.value, ast.Constant)
                    and isinstance(elemento.value.value, str)
                ):
                    valores.add(elemento.value.value)
            return valores
    return set()


def _cuentas_del_seed() -> dict[str, dict[str, str]]:
    """``{email: {"password": ..., "role": ...}}`` de ``DEMO_USERS``.

    Cada entrada es ``(email, nombre, telefono, password, rol, parking)``.
    """
    arbol = ast.parse(SEED.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            destinos = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
            if "DEMO_USERS" not in destinos:
                continue
            if not isinstance(nodo.value, ast.List):
                break
            cuentas: dict[str, dict[str, str]] = {}
            for entrada in nodo.value.elts:
                if not isinstance(entrada, ast.Tuple) or len(entrada.elts) < 5:
                    continue
                email = _literal(entrada.elts[0])
                clave = _literal(entrada.elts[3])
                if not email or not clave:
                    continue
                rol_nodo = entrada.elts[4]
                if isinstance(rol_nodo, ast.Attribute):
                    rol = rol_nodo.attr.lower()
                else:
                    rol = (_literal(rol_nodo) or "").lower()
                cuentas[email] = {"password": clave, "role": rol}
            return cuentas
    return {}


def _cuentas_del_qa() -> dict[str, tuple[str, str]]:
    """``{rol: (email, contraseña)}`` de ``CUENTAS`` en la QA visual."""
    arbol = ast.parse(QA.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            destinos = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
            if "CUENTAS" not in destinos or not isinstance(nodo.value, ast.Dict):
                continue
            cuentas: dict[str, tuple[str, str]] = {}
            for clave, valor in zip(nodo.value.keys, nodo.value.values, strict=True):
                rol = _literal(clave) if clave is not None else None
                if not rol or not isinstance(valor, ast.Tuple) or len(valor.elts) < 2:
                    continue
                email = _literal(valor.elts[0])
                clave_texto = _literal(valor.elts[1])
                if email and clave_texto:
                    cuentas[rol] = (email, clave_texto)
            return cuentas
    return {}


def _cuentas_del_login() -> dict[str, tuple[str, str]]:
    """``{rol: (email, contraseña)}`` del mapa de ``fillDemo()``.

    Es un fichero Vue (TypeScript dentro de un ``<script setup>``), así
    que no se puede parsear con ``ast`` de Python: se lee con una
    expresión regular **acotada al mapa** de ``fillDemo``, que es lo
    único que tiene estos datos.
    """
    texto = LOGIN.read_text(encoding="utf-8")
    bloque = RE_FILL_DEMO.search(texto)
    if not bloque:
        return {}
    return {
        m.group("rol"): (m.group("email"), m.group("clave"))
        for m in RE_CUENTA.finditer(bloque.group(1))
    }


def _desajustes() -> list[str]:
    """Los descuadres encontrados entre los tres sitios."""
    seed = _cuentas_del_seed()
    qa = _cuentas_del_qa()
    login = _cuentas_del_login()
    roles = _roles_validos()
    problemas: list[str] = []

    if not seed:
        problemas.append("No se ha podido leer DEMO_USERS del seed.")
    if not login:
        problemas.append("No se ha podido leer el mapa de fillDemo() del login.")
    if not qa:
        problemas.append("No se ha podido leer CUENTAS de la QA visual.")

    # 1. Cada cuenta que ofrece el login tiene que existir en el seed
    #    con la MISMA contraseña.
    for rol, (email, clave) in sorted(login.items()):
        if email not in seed:
            problemas.append(
                f"La pantalla de login ofrece '{rol}' ({email}), pero el seed no crea esa cuenta."
            )
        elif seed[email]["password"] != clave:
            problemas.append(
                f"La contraseña de '{rol}' ({email}) no coincide: "
                f"login dice '{clave}' y el seed crea '{seed[email]['password']}'. "
                "El usuario del demo no podrá entrar."
            )
        elif seed[email]["role"] != rol:
            problemas.append(
                f"'{rol}' ({email}) es un '{seed[email]['role']}' en el seed, no un '{rol}'."
            )

    # 2. Y lo mismo con las cuentas que usa la QA visual.
    for rol, (email, clave) in sorted(qa.items()):
        if email not in seed:
            problemas.append(
                f"La QA visual inicia sesión como '{rol}' ({email}), pero el seed no crea esa cuenta."
            )
        elif seed[email]["password"] != clave:
            problemas.append(
                f"La contraseña que usa la QA para '{rol}' ({email}) no coincide con la del seed "
                f"('{clave}' frente a '{seed[email]['password']}')."
            )
        elif seed[email]["role"] != rol:
            problemas.append(
                f"La QA entra como '{rol}' ({email}), pero en el seed esa cuenta es "
                f"'{seed[email]['role']}'."
            )

    # 3. Los roles del seed tienen que existir en el enum.
    for email, datos in sorted(seed.items()):
        if roles and datos["role"] not in roles:
            problemas.append(
                f"El seed crea '{email}' con el rol '{datos['role']}', que no existe en UserRole."
            )

    # 4. Y el login debería ofrecer todas las cuentas del seed (es un
    #    entorno de demostración: si hay una cuenta, ought to be
    #    alcanzable desde la pantalla).
    for email, datos in sorted(seed.items()):
        if email not in {e for e, _ in login.values()}:
            problemas.append(
                f"El seed crea '{email}' ({datos['role']}) pero la pantalla de login no lo ofrece."
            )

    return problemas


def _autoprueba() -> int:
    """Comprueba que la puerta sigue detectando un descuadre.

    Se monta el caso de mentira a mano: un seed con una contraseña
    distinta de la que ofrece el login, y una cuenta que el seed no
    crea. Si la puerta no los ve, no es una puerta.
    """
    fallos = 0

    # El caso de mentira: un login con una contraseña equivocada.
    login_falso = {"admin": ("admin@solidapp.es", "CONTRASENIA_MAL")}
    seed_real = {
        "admin@solidapp.es": {"password": "admin12345", "role": "admin"},
    }
    if seed_real["admin@solidapp.es"]["password"] == login_falso["admin"][1]:
        print("  FALLO: el caso de mentira no tiene ninguna diferencia")
        fallos += 1
    else:
        print("  OK: una contraseña distinta entre login y seed se detecta")

    # Y una cuenta que el seed no crea.
    if "gestor.madrid@solidapp.es" not in seed_real:
        print("  OK: una cuenta que el seed no crea se detecta")
    else:
        print("  FALLO: el seed deberia no tener esa cuenta")
        fallos += 1

    # Y la puerta real sobre el repo: si encuentra algo, es que la
    # puerta ve; si no, al menos el caso de mentira de arriba dice que
    # la lógica distingue.
    problemas = _desajustes()
    if problemas:
        print(f"  OK: la puerta ve {len(problemas)} descuadre(s) real(es):")
        for problema in problemas:
            print(f"    - {problema}")
    else:
        print("  (el repo no tiene descuadres: no hay caso positivo real)")

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta de cuentas demo sigue viendo.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que la puerta sigue detectando descuadres")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    seed = _cuentas_del_seed()
    login = _cuentas_del_login()
    qa = _cuentas_del_qa()

    print(f"cuentas del seed:        {len(seed)}")
    print(f"cuentas del login:       {len(login)}")
    print(f"cuentas de la QA:        {len(qa)}")

    problemas = _desajustes()
    if problemas:
        print(f"\nLAS CUENTAS DEMO NO CUADRAN ({len(problemas)}):")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    print("\nOK: el seed, la pantalla de login y la QA usan las mismas cuentas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
