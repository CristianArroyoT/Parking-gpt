"""Prueba inversa del T-179: sin el arreglo, la pantalla de RBAC por sucursal falla.

QUÉ COMPRUEBA
-------------
La QA ``frontend/scripts/qa_membresias_rbac.py`` demuestra, con un navegador
de verdad, que el admin puede listar, añadir, cambiar el rol y quitar las
membresías de un usuario, y que un 422 del backend se muestra con **su**
mensaje.

Si la QA pasara con el defecto puesto, no demostraría nada. Por eso esta
prueba **vuelve a poner el defecto** (sobre una copia, en un directorio
temporal) y exige que la QA **falle por el motivo correcto**:

1. **El cambio de rol no se envía al backend**: la pantalla actualiza el
   desplegable, pero el ``PATCH`` no sale. La QA tiene que decir que el rol
   no se guardó (o que no llegó el PATCH).
2. **El error del backend no se muestra**: la pantalla enseña un mensaje
   genérico en vez del que dice la API. La QA tiene que decir que el 422 no
   se muestra con el mensaje del backend.

OJO: hay que **reiniciar el frontend** tras quitar (o restaurar) el arreglo:
con el bind mount, el HMR de Vite no siempre aplica y se mide el bundle
viejo (falso positivo: la QA pasaría con el defecto puesto).

OJO: el fichero se modifica **en el repositorio** (es la forma de que el
contenedor sirva el defecto), pero se **restaura al final** y se comprueba
que queda idéntico a como estaba.

Uso:
    python frontend/scripts/qa_membresias_rbac_inversa.py

Códigos de salida: 0 correcto · 1 fallo.
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
FICHERO = RAIZ / "frontend" / "src" / "views" / "admin" / "UsersView.vue"
COPIA = Path(r"D:\tmp\_copias_t179")
COPIA.mkdir(parents=True, exist_ok=True)

# ── Defecto 1: el cambio de rol no llega al backend ──────────────────────
VIEJO_PATCH = """    await updateMembershipRole(panelUser.value.id, m.id, valor as MembershipRole)
"""
SIN_PATCH = """    // DEFECTO (T-179): el cambio de rol no se envia al backend.
"""

# ── Defecto 2: el error del backend no se muestra ─────────────────────────
VIEJO_ERROR = """function extraerError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string }
    const detail = anyErr.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => (typeof d === 'string' ? d : ((d as { msg?: string })?.msg ?? '')))
        .filter((m) => m !== '')
      if (msgs.length) return msgs.join(' · ')
    }
    if (anyErr.message) return anyErr.message
  }
  return fallback
}
"""
SIN_ERROR = """function extraerError(err: unknown, fallback: string): string {
  // DEFECTO (T-179): el error del backend no se muestra, solo el generico.
  void err
  return fallback
}
"""

#: (etiqueta, bloque a quitar, bloque del defecto, motivos validos de fallo)
DEFECTOS = (
    (
        "cambio de rol sin enviar",
        VIEJO_PATCH,
        SIN_PATCH,
        ("no se envió el cambio de rol", "no se guardó"),
    ),
    (
        "error generico en vez del del backend",
        VIEJO_ERROR,
        SIN_ERROR,
        ("no se muestra con el mensaje del backend",),
    ),
)


def reiniciar_frontend() -> None:
    """Reinicia el frontend y espera a que vuelva a servir.

    OJO (AGENTS.md): al arrancar, Vite **reoptimiza** las dependencias y
    el dev-server se reinicia otra vez. Por eso, después de que responda,
    se espera un margen antes de medir: si no, la QA mide un servidor a
    medio arrancar.
    """
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
                    print("  frontend arriba (margen de 25 s para que Vite termine)")
                    time.sleep(25)
                    return
        except Exception:
            time.sleep(3)
    print("AVISO: el frontend no respondio tras el reinicio.")


def escribir(texto: str) -> None:
    with open(FICHERO, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def main() -> int:
    with open(FICHERO, "r", encoding="utf-8", newline="") as f:
        texto_original = f.read()
    nl = "\r\n" if "\r\n" in texto_original else "\n"

    for etiqueta, viejo, nuevo, motivos in DEFECTOS:
        bloque = viejo.replace("\n", nl)
        if texto_original.count(bloque) != 1:
            print(
                f"ERROR ({etiqueta}): el bloque aparece "
                f"{texto_original.count(bloque)} veces (se esperaba 1)."
            )
            return 1

    shutil.copy2(FICHERO, COPIA / FICHERO.name)
    try:
        for etiqueta, viejo, nuevo, motivos in DEFECTOS:
            bloque = viejo.replace("\n", nl)
            texto = texto_original.replace(bloque, nuevo.replace("\n", nl))
            escribir(texto)
            print(f"  puesto el defecto: {etiqueta}")

            print("  reiniciando el frontend...")
            reiniciar_frontend()

            proc = subprocess.run(
                [sys.executable, "frontend/scripts/qa_membresias_rbac.py"],
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
            if not any(motivo in salida for motivo in motivos):
                print("*** AVISO: fallo por otro motivo: la prueba no vale.")
                return 1
            print(f"OK: sin el arreglo, la QA falla por el motivo correcto ({etiqueta}).")

            # Se vuelve al fichero original antes del siguiente defecto.
            escribir(texto_original)
    finally:
        shutil.copy2(COPIA / FICHERO.name, FICHERO)
        with open(FICHERO, "r", encoding="utf-8", newline="") as f:
            restaurado = f.read() == texto_original
        print(f"restaurado: frontend/src/views/admin/UsersView.vue (identico: {restaurado})")
        print("  reiniciando el frontend...")
        reiniciar_frontend()
    return 0


if __name__ == "__main__":
    sys.exit(main())
