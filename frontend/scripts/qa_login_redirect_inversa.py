"""Prueba inversa del T-165: sin el arreglo, el destino del login no se valida.

QUÉ COMPRUEBA
-------------
Sin el arreglo, el ``redirect`` de la query se pasa tal cual a
``router.push()``. Con eso pasan dos cosas (las dos las detecta la QA
``frontend/scripts/qa_login_redirect.py``):

1. ``?redirect=//example.com`` deja al usuario en una URL que contiene el
   valor malicioso (``http://127.0.0.1:5173//example.com``);
2. ``?redirect=/mapa&redirect=/otro`` llega como **array**: el ``push``
   falla, su rechazo se queda sin gestionar y el usuario **se queda en el
   formulario de login** (con la sesión iniciada y sin ver el mensaje de
   bienvenida).

Si la QA pasara con el defecto puesto, no demostraría nada: por eso esta
prueba la ejecuta **con el defecto** y exige que **falle**.

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el arreglo
(con el bind mount, el HMR de Vite no siempre aplica y se mide el bundle
viejo).

OJO (rate-limit): ``POST /auth/login`` admite 10 intentos por IP cada 5
minutos (y cuenta también los exitosos), así que esta prueba hace 2
inicios de sesión: no la lances 5 veces seguidas.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent.parent
FICHERO = RAIZ / "frontend" / "src" / "views" / "LoginView.vue"
COPIA = Path(r"D:\tmp\_copias_t165")
COPIA.mkdir(parents=True, exist_ok=True)

#: El bloque con la función de validación (se quita entero: el defecto
#: es que esa validación no existe).
VIEJO_FUNCION = """/**
 * El destino tras el login, **validado** (T-165).
 *
 * OJO: el valor viene de la query, o sea de quien construya el enlace.
 * Medido el 2026-10-24 con un navegador de verdad:
 * ``?redirect=//ejemplo.com`` deja al usuario en
 * ``http://127.0.0.1:5173//ejemplo.com`` (una ruta interna que no
 * existe). **No** es una redirección abierta (vue-router 4 trata esos
 * valores como rutas del propio host), pero el destino tiene que ser
 * una ruta interna de verdad.
 *
 * Y con ``?redirect=/a&redirect=/b`` la query llega como **array**: el
 * cast ``as string`` no lo convertía, el ``push`` fallaba y su rechazo
 * se quedaba sin gestionar (el login había funcionado, pero el usuario
 * se quedaba en el formulario, sin ver el mensaje de bienvenida).
 */
function destinoSeguro(): string {
  const valor = route.query.redirect
  if (typeof valor !== 'string') return '/'
  if (!valor.startsWith('/')) return '/'
  // ``//host`` y ``/\\host`` se interpretan como protocolo-relativo.
  if (valor.startsWith('//') || valor.startsWith('/\\\\')) return '/'
  return valor
}

"""

NUEVO_FUNCION = ""

#: El ``push`` sin validar y sin esperar (el defecto del T-165).
VIEJO_PUSH = """    await auth.login(email.value, password.value)
    ui.pushToast('success', 'Bienvenido a solidAPP')
    // El `await` va dentro del `try`: si la navegación falla, lo
    // captura el catch de siempre (antes el rechazo se perdía).
    await router.push(destinoSeguro())
"""

NUEVO_PUSH = """    await auth.login(email.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    ui.pushToast('success', 'Bienvenido a solidAPP')
    router.push(redirect)
"""

#: Lo que la QA tiene que decir cuando el defecto está puesto.
MARCAS = (
    "la URL contiene el valor malicioso",
    "se ha quedado en el formulario de login",
)


def reiniciar_frontend() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "frontend"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    fin = time.time() + 180
    while time.time() < fin:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5173/login", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(3)
    print("AVISO: el frontend no respondio tras el reinicio.")


def main() -> int:
    texto_original = FICHERO.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in texto_original else "\n"

    for etiqueta, viejo in (("funcion", VIEJO_FUNCION), ("push", VIEJO_PUSH)):
        bloque = viejo.replace("\n", nl)
        if texto_original.count(bloque) != 1:
            print(
                f"ERROR ({etiqueta}): el bloque aparece "
                f"{texto_original.count(bloque)} veces (se esperaba 1)."
            )
            return 1

    shutil.copy2(FICHERO, COPIA / FICHERO.name)
    try:
        texto = texto_original
        for viejo, nuevo in ((VIEJO_FUNCION, NUEVO_FUNCION), (VIEJO_PUSH, NUEVO_PUSH)):
            texto = texto.replace(viejo.replace("\n", nl), nuevo.replace("\n", nl))
        FICHERO.write_text(texto, encoding="utf-8", newline="")
        print("  quitado el arreglo de LoginView.vue")

        print("  reiniciando el frontend...")
        reiniciar_frontend()

        proc = subprocess.run(
            [sys.executable, "frontend/scripts/qa_login_redirect.py"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        salida = (proc.stdout or "") + (proc.stderr or "")
        print("\nSalida de la QA con el defecto:")
        print(salida.strip()[:1200])
        print(f"\ncodigo de salida: {proc.returncode}")

        if proc.returncode == 0:
            print("*** FALLO: la QA pasa sin el arreglo: no demuestra nada.")
            return 1
        if not any(marca in salida for marca in MARCAS):
            print("*** AVISO: fallo por otro motivo: la prueba no vale.")
            return 1
        print("OK: sin el arreglo, la QA falla por el motivo correcto.")
        return 0
    finally:
        shutil.copy2(COPIA / FICHERO.name, FICHERO)
        restaurado = FICHERO.read_text(encoding="utf-8") == texto_original
        print(f"restaurado: frontend/src/views/LoginView.vue (identico: {restaurado})")
        print("  reiniciando el frontend...")
        reiniciar_frontend()


if __name__ == "__main__":
    sys.exit(main())
