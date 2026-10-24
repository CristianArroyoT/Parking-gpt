"""Prueba inversa del T-139: sin el arreglo, el login se traga el error
(el toast dice «Bienvenido», deja los tokens y no muestra nada).

OJO: hay que **reiniciar el frontend** tras quitar o restaurar el
arreglo (con el bind mount, el HMR de Vite no siempre aplica y se mide
el bundle viejo).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(r"D:\Parking")
FICHERO = RAIZ / "frontend" / "src" / "stores" / "auth.ts"
COPIA = Path(r"D:\tmp\_copias_t139")
COPIA.mkdir(parents=True, exist_ok=True)

VIEJO = """      try {
        await fetchMe()
      } catch (err: unknown) {
        // T-139 (2026-10-24): si el perfil no se pudo cargar, la sesion
        // no sirve (un token sin usuario no pasa el guard). Se limpian
        // los tokens y el error sube al login, que lo muestra: antes
        // decia «Bienvenido» y echaba al usuario al formulario sin
        // ningun error visible.
        clearTokens()
        sessionStorage.removeItem(EMAIL_KEY)
        email.value = null
        throw err
      }
"""
NUEVO = """      await fetchMe()
"""

VIEJO_FETCH = """  async function fetchMe(): Promise<void> {
    // T-139 (2026-10-24): este catch se tragaba CUALQUIER error y
    // dejaba el login a medias (token guardado, perfil vacio) con un
    // comentario que describia un comportamiento que no existia: el
    // guard comprueba `user !== null`, asi que sin perfil echaba al
    // usuario al login. Ahora el error se propaga.
    const { data } = await http.get<User>('/users/me')
    user.value = data
  }
"""
NUEVO_FETCH = """  async function fetchMe(): Promise<void> {
    try {
      const { data } = await http.get<User>('/users/me')
      user.value = data
    } catch {
      // /users/me no existe aún: el store queda sin perfil pero autenticado
      // (los tokens siguen siendo válidos). El guard del router acepta esto.
    }
  }
"""


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


texto_original = FICHERO.read_text(encoding="utf-8")
nl = "\r\n" if "\r\n" in texto_original else "\n"
for etiqueta, viejo, nuevo in (
    ("login", VIEJO, NUEVO),
    ("fetchMe", VIEJO_FETCH, NUEVO_FETCH),
):
    bloque = viejo.replace("\n", nl)
    if texto_original.count(bloque) != 1:
        print(f"ERROR ({etiqueta}): el bloque aparece {texto_original.count(bloque)} veces.")
        sys.exit(1)

shutil.copy2(FICHERO, COPIA / FICHERO.name)
try:
    texto = texto_original
    for viejo, nuevo in ((VIEJO, NUEVO), (VIEJO_FETCH, NUEVO_FETCH)):
        texto = texto.replace(viejo.replace("\n", nl), nuevo.replace("\n", nl))
    FICHERO.write_text(texto, encoding="utf-8", newline="")
    print("  quitado el arreglo de auth.ts")

    print("  reiniciando el frontend...")
    reiniciar_frontend()

    proc = subprocess.run(
        [sys.executable, "frontend/scripts/qa_login_error.py"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    salida = (proc.stdout or "") + (proc.stderr or "")
    print("\nSalida de la QA con el defecto:")
    print(salida.strip()[:800])
    print(f"\ncodigo de salida: {proc.returncode}")
    if proc.returncode == 0:
        print("*** FALLO: la QA pasa sin el arreglo: no demuestra nada.")
        sys.exit(1)
    if "sin mostrar ningun error" not in salida and "dejo los tokens" not in salida:
        print("*** AVISO: fallo por otro motivo: la prueba no vale.")
        sys.exit(1)
    print("OK: sin el arreglo, la QA falla por el motivo correcto.")
finally:
    shutil.copy2(COPIA / FICHERO.name, FICHERO)
    print("restaurado: frontend/src/stores/auth.ts")
    print("  reiniciando el frontend...")
    reiniciar_frontend()
