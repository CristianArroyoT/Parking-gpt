"""Estado de salud del repositorio en un solo comando.

POR QUÉ (2026-10-21): el CI remoto **no puede correr** —la cuenta de
GitHub tiene el pago pendiente y GitHub rechaza los jobs antes de
asignarles un runner (los 4 jobs mueren en 2-5 s con 0 pasos). El
último run que llegó a ejecutar algo fue el del 2026-07-07: más de tres
meses sin que el CI validara nada, con 87 commits de ``main`` sin
pasar por esa red.

Mientras eso siga así, la única forma de saber si el repo está sano es
**este script**: corre todas las comprobaciones (medidores, puertas
del pipeline, QA visual y el CI replicado en local) y devuelve un
veredicto y un código de salida, igual que haría el CI.

Uso:
    python tools/verificar_repo.py              # comprobaciones rapidas (~2 min)
    python tools/verificar_repo.py --completo   # + CI local y QA visual (~40 min)

Códigos de salida: 0 si todo está bien, 1 si algo falla.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# La consola de Windows es cp1252: sin esto, imprimir un resumen con
# acentos rompe la puerta (UnicodeEncodeError) o lo degrada. Receta del
# AGENTS.md.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: Fichero de informe de carga que se usa como referencia del SLO.
INFORME_SLO = RAIZ / "backend" / "locust" / "reports" / "2026-10-21-revalidacion.json"

#: Anchos de la QA visual.
ANCHOS_QA = (414, 768, 1024, 1232, 1440)


class Comprobacion:
    """Una comprobación: nombre, orden y cómo resumir su salida."""

    def __init__(self, nombre: str, comando: list[str], patron: str | None = None,
                 peso: str = "rapido", cwd: Path | None = None,
                 env_extra: dict | None = None, timeout: int = 1800):
        self.nombre = nombre
        self.comando = comando
        self.patron = patron
        self.peso = peso
        self.cwd = cwd or RAIZ
        self.env_extra = env_extra or {}
        self.timeout = timeout


def _comprobaciones() -> list[Comprobacion]:
    py = sys.executable
    return [
        Comprobacion(
            "Texto versionado sin corrupcion",
            [py, "tools/escanear_texto.py", "--tracked"],
            patron=r"(\(\d+ problema\(s\)\))",
        ),
        Comprobacion(
            "Sin secretos (arbol e historial)",
            [py, "tools/escanear_secretos.py", "--historial"],
            patron=r"(OK: no hay secretos.*)",
        ),
        Comprobacion(
            "El inventario de la API coincide con el codigo",
            [py, "tools/verificar_api_doc.py"],
            patron=r"(El inventario coincide con el codigo.*)",
        ),
        Comprobacion(
            "Cobertura: todo endpoint con test",
            [py, "tools/cobertura_api.py"],
            patron=r"(SIN ningun test: +\d+)",
        ),
        Comprobacion(
            "Esquemas Create/Update simetricos",
            [py, "tools/revisar_esquemas.py"],
            patron=r"(OK: los campos validados.*)",
        ),
        Comprobacion(
            "El frontend llama a endpoints que existen",
            [py, "tools/verificar_contrato_frontend.py"],
            patron=r"(OK: el frontend llama a endpoints.*)",
        ),
        Comprobacion(
            "El guard de rol del frontend coincide con el RBAC",
            [py, "tools/verificar_roles_frontend.py"],
            patron=r"(OK: ninguna pantalla llama a un endpoint.*)",
        ),
        Comprobacion(
            "El seed, el login y la QA usan las mismas cuentas demo",
            [py, "tools/verificar_cuentas_demo.py"],
            patron=r"(OK: el seed, la pantalla de login.*)",
        ),
        Comprobacion(
            "La QA visual recorre todas las pantallas del router",
            [py, "tools/verificar_cobertura_frontend.py"],
            patron=r"(OK: la QA visual recorre todas las pantallas.*)",
        ),
        Comprobacion(
            "El frontend conoce todos los valores de los enums",
            [py, "tools/verificar_enums_frontend.py"],
            patron=r"(OK: el frontend conoce todos los valores.*)",
        ),
        Comprobacion(
            "Las tareas de Celery se ejecutan de verdad",
            [py, "tools/verificar_tareas_celery.py"],
            patron=r"(OK: toda tarea sin ejecutar tiene su motivo.*)",
        ),
        Comprobacion(
            "Los ajustes muertos del backend tienen su motivo",
            [py, "tools/verificar_ajustes_muertos.py"],
            patron=r"(OK: todo ajuste muerto tiene su motivo.*)",
        ),
        Comprobacion(
            "Modelos y migraciones coinciden",
            [
                "docker", "exec",
                "-e", "DATABASE_URL=postgresql+psycopg://parking:parking@db:5432/parking",
                "parking-backend-1", "alembic", "check",
            ],
            patron=r"(No new upgrade operations detected.*)",
        ),
        Comprobacion(
            "SLO de carga",
            [py, "backend/locust/check_slo.py", "--report", str(INFORME_SLO)],
            patron=r"(SLO CUMPLIDO: \d+ reglas OK.*)",
        ),
        Comprobacion(
            "El PWA es instalable y arranca sin red",
            [py, "frontend/scripts/qa_pwa.py"],
            patron=r"(PWA OK:.*)",
            timeout=600,
        ),
        Comprobacion(
            "El servidor de produccion admite los cuerpos que el backend acepta",
            [py, "tools/verificar_nginx_body_size.py"],
            patron=r"(OK: nginx admite.*)",
        ),
        Comprobacion(
            "El contexto de build de la imagen de produccion esta limpio",
            [py, "tools/verificar_contexto_build.py"],
            patron=r"(OK: el contexto de build.*)",
        ),
        Comprobacion(
            "El rate-limit por endpoint tiene una sola implementacion",
            [py, "tools/verificar_rate_limit_unico.py"],
            patron=r"(OK: el rate-limit por endpoint.*)",
        ),
        Comprobacion(
            "El lockfile esta sincronizado con el package.json",
            [py, "tools/verificar_lockfile.py"],
            patron=r"(OK: el package-lock.json.*)",
        ),
        Comprobacion(
            "Las puertas se prueban a si mismas",
            [py, "tools/autopruebas.py", "--estricto"],
            patron=r"(\d+ autopruebas? pasan.*)",
            timeout=600,
        ),
        Comprobacion(
            "Simulacro de restauracion de backups",
            [py, "tools/verificar_backup.py"],
            patron=r"(SIMULACRO CORRECTO.*)",
            timeout=900,
        ),
        Comprobacion(
            "CI local (los 4 jobs del workflow)",
            [py, "tools/ejecutar_ci_local.py", "--all"],
            patron=r"(Todos los jobs pasan en local.*)",
            peso="completo",
            timeout=3600,
        ),
        Comprobacion(
            "QA visual en los 5 anchos",
            [
                py, "frontend/scripts/qa_visual.py",
                "--salida", "D:/tmp/qa-verify",
                "--anchos", ",".join(str(a) for a in ANCHOS_QA),
            ],
            patron=r"(Capturas e informe en .*)",
            peso="completo",
            timeout=1800,
        ),
    ]


def _consola(texto: str) -> str:
    """Texto que la consola de Windows puede imprimir (cp1252)."""
    codificacion = getattr(sys.stdout, "encoding", None) or "utf-8"
    return texto.encode(codificacion, "replace").decode(codificacion, "replace")


def _decodificar(bruto: bytes) -> str:
    """Decodifica la salida de un subproceso sin perder acentos.

    UTF-8 primero (es lo que escriben los subprocesos de este repo, con
    ``PYTHONIOENCODING=utf-8``) y, si los bytes no son UTF-8 válido, se
    recurre a cp1252 (la codificación de la consola de Windows). Sin el
    fallback, un subproceso que escribiera en cp1252 devolvía las tildes
    como U+FFFD.
    """
    if not bruto:
        return ""
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("cp1252", "replace")


def _resumir(salida: str, patron: str | None) -> str:
    """Una línea con el resultado de la comprobación."""
    if not patron:
        lineas = [x.strip() for x in salida.splitlines() if x.strip()]
        return lineas[-1][:110] if lineas else "(sin salida)"
    encontrados = re.findall(patron, salida)
    if not encontrados:
        lineas = [x.strip() for x in salida.splitlines() if x.strip()]
        return (lineas[-1][:110] if lineas else "(sin salida)")
    valor = encontrados[-1]
    if isinstance(valor, tuple):
        valor = valor[0] if valor[0] else valor[-1]
    return str(valor)[:110]


def _ejecutar(c: Comprobacion) -> tuple[bool, str, float]:
    inicio = time.time()
    import os

    # OJO (T-70): sin esto, el subproceso escribe su salida en la
    # codificacion de la consola de Windows (cp1252) y al decodificarla
    # como UTF-8 los bytes de los acentos salian como U+FFFD: el print
    # reventaba con UnicodeEncodeError y la puerta del repo se caia en
    # Windows en cuanto una comprobacion devolvia un resumen con tildes.
    entorno = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        **c.env_extra,
    }
    try:
        proceso = subprocess.run(
            c.comando, cwd=str(c.cwd), env=entorno, check=False,
            capture_output=True,
            timeout=c.timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"se paso del limite de {c.timeout} s", time.time() - inicio
    except FileNotFoundError as exc:
        return False, f"no se encontro {exc.filename}", time.time() - inicio

    salida = _decodificar((proceso.stdout or b"") + (proceso.stderr or b""))
    resumen = _resumir(salida, c.patron)
    return proceso.returncode == 0, resumen, time.time() - inicio


def _stack_arriba() -> tuple[bool, str]:
    """¿Está el stack de Docker levantado y respondiendo?

    Sin esto, las comprobaciones pesadas (QA visual, CI local) fallarían
    con errores confusos (el navegador no encuentra la app, el backend no
    arranca) en vez de decir "levanta el stack".
    """
    import os
    import urllib.error
    import urllib.request

    try:
        proceso = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}} {{.State}}"],
            cwd=str(RAIZ),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
            capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"no se pudo consultar docker: {exc}"
    if proceso.returncode != 0:
        return False, "docker compose ps falló"
    lineas = [x for x in (proceso.stdout or "").splitlines() if x.strip()]
    if not lineas:
        return False, "no hay ningun servicio levantado (docker compose up -d)"
    if not any("running" in x or "Up" in x for x in lineas):
        return False, "los servicios no estan en marcha"

    try:
        with urllib.request.urlopen("http://localhost:8000/health/ready", timeout=15) as r:
            if r.status != 200:
                return False, f"/health/ready devolvio {r.status}"
    except urllib.error.URLError as exc:
        return False, f"el backend no responde en el puerto 8000 ({exc.reason})"
    except Exception as exc:  # noqa: BLE001
        return False, f"el backend no responde en el puerto 8000 ({exc})"
    return True, ""


def _autoprueba() -> int:
    """Comprueba que ESTA puerta detecta un fallo.

    Es la puerta de todas las puertas: si dejara de contar los fallos,
    todo lo demás dejaría de importar. Se ejecuta con una comprobación
    inyectada que falla siempre y se comprueba que sale con código 1.
    """
    print("AUTOPRUEBA DE LA PUERTA DEL REPO")
    print("=" * 78)
    comprobacion_rota = Comprobacion(
        "comprobacion de mentira (debe fallar)",
        [sys.executable, "-c", "raise SystemExit(3)"],
        patron=r"(.*)",
    )
    # T-70: un resumen con tildes (o con un caracter que cp1252 no
    # tiene) no puede tumbar la puerta al imprimirlo.
    comprobacion_con_acentos = Comprobacion(
        "comprobacion con acentos (debe pasar)",
        [
            sys.executable,
            "-c",
            "print('OK: revisi\u00f3n con acentos: implementaci\u00f3n y c\u00f3digo')",
        ],
        patron=r"(OK: revisi.*)",
    )
    ok_acentos, resumen_acentos, _s = _ejecutar(comprobacion_con_acentos)
    if not ok_acentos:
        print(f"  FALLO: una comprobacion con acentes no se ha leido bien ({resumen_acentos[:60]})")
        return 1
    try:
        _consola(f"[OK  ] con acentos: {resumen_acentos}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FALLO: imprimir un resumen con acentes revienta: {exc}")
        return 1
    print("  OK: un resumen con acentes se lee y se imprime sin romperse")

    ok, resumen, _segundos = _ejecutar(comprobacion_rota)
    if ok:
        print("  FALLO: una comprobacion que falla no se ha detectado")
        return 1
    print(f"  OK: una comprobacion que falla se detecta (resumen: {resumen[:60]})")

    # Y la comprobacion buena, para comprobar que no se marca como FALLO
    # lo que pasa.
    comprobacion_buena = Comprobacion(
        "comprobacion de mentira (debe pasar)",
        [sys.executable, "-c", "print('todo bien')"],
        patron=r"(todo bien)",
    )
    ok, _resumen, _segundos = _ejecutar(comprobacion_buena)
    if not ok:
        print("  FALLO: una comprobacion que pasa se ha marcado como fallo")
        return 1
    print("  OK: una comprobacion que pasa no se marca como fallo")
    print("Autoprueba correcta: la puerta detecta los fallos.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--completo", action="store_true",
                    help="Anade el CI local y la QA visual en los cinco anchos")
    ap.add_argument("--autoprueba", action="store_true",
                    help="Comprueba que esta puerta detecta un fallo")
    args = ap.parse_args()

    if args.autoprueba:
        return _autoprueba()

    print("ESTADO DEL REPOSITORIO solidAPP")
    print("=" * 78)
    fallos = 0
    stack_comprobado = False
    for c in _comprobaciones():
        if c.peso == "completo" and not args.completo:
            continue
        if c.peso == "completo" and not stack_comprobado:
            stack_comprobado = True
            arriba, motivo = _stack_arriba()
            if not arriba:
                print(f"[AVISO] El stack no parece operativo: {motivo}", flush=True)
                print("        (docker compose up -d) — las comprobaciones "
                      "pesadas pueden fallar por eso, no por el codigo.", flush=True)
        ok, resumen, segundos = _ejecutar(c)
        marca = "OK  " if ok else "FALLO"
        if not ok:
            fallos += 1
        # T-70: ``_consola`` quita lo que la consola de Windows no puede
        # imprimir. Sin él, un resumen con un caracter fuera de cp1252
        # tumbaba la puerta entera.
        print(
            _consola(f"[{marca}] {c.nombre:<44} {segundos:6.1f} s  {resumen}"),
            flush=True,
        )

    # El CI remoto no se puede ejecutar: se informa, no cuenta como fallo.
    codigo, _salida = 0, ""
    import os

    try:
        proceso = subprocess.run(
            [sys.executable, "tools/estado_ci.py"],
            cwd=str(RAIZ),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
            capture_output=True, encoding="utf-8", errors="replace", timeout=300,
        )
        codigo = proceso.returncode
    except Exception:  # noqa: BLE001 — informational
        codigo = -1
    if codigo == 0:
        print("[OK  ] CI remoto en main                              en verde", flush=True)
    elif codigo == 2:
        print("[AVISO] CI remoto en main                              rechazado por la cuenta (facturacion)", flush=True)
    elif codigo == 3:
        print("[AVISO] CI remoto en main                              todavia en curso (no se puede afirmar)", flush=True)
    elif codigo == 4:
        print("[AVISO] CI remoto en main                              el run no cubre todos los jobs del workflow", flush=True)
    else:
        print("[AVISO] CI remoto en main                              en rojo o sin comprobar", flush=True)

    print("=" * 78)
    if fallos:
        print(f"{fallos} comprobacion(es) en FALLO.")
        return 1
    print("Todo en verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
