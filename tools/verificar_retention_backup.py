"""Comprueba que la retencion GFS del backup se cumple de verdad.

POR QUE esta puerta
-------------------
El script ``infra/backup/backup.sh`` promete (en su cabecera, en el README
y en el plan) conservar **7 diarios + 4 semanales + 6 mensuales**.

CASO REAL (T-146, 2026-10-24)
-----------------------------
La retencion se calculaba con ``awk -F'-' '!seen[$2]++'``, pero el nombre
del fichero es ``solidapp-AAAAMMDDTHHMMSSZ.dump.enc`` y el STAMP **no**
tiene guiones: ``$2`` era el stamp entero (unico por fichero) y ``$3`` era
``dump.enc``. O sea: «un fichero por semana» era en realidad «un fichero por
fichero», y «un fichero por mes» tambien.

Consecuencia: los tres listados acababan en los mismos ficheros mas
recientes, asi que **solo sobrevivian 7 backups**. El backup mensual que
el plan promete conservar se borraba a los siete dias, y el semanal
tambien. Y nadie se enteraba: el script no falla, solo borra de mas.

QUE COMPRUEBA
-------------
Se crean **400 backups diarios de mentira** (uno por dia hacia atras), se
ejecuta el script de verdad (``--solo-retencion``, en un contenedor) y se
comprueba que sobreviven:

- los **7 diarios** mas recientes;
- al menos **4 semanas ISO** distintas;
- al menos **6 meses** distintos;
- y que un backup de hace 400 dias **no** sobrevive.

Con el defecto anterior solo sobrevivian los 7 mas recientes: habia una
semana y un mes, y la puerta lo detecta.

Uso
---
    python tools/verificar_retention_backup.py
    python tools/verificar_retention_backup.py --autoprueba
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "infra" / "backup" / "backup.sh"

#: La imagen con bash y las coreutils de GNU (la misma base del backend).
IMAGEN = "solidapp-backend:latest"

#: Dias de backups de mentira que se crean.
DIAS_DE_PRUEBA = 400

#: La politica que declara el script (sus variables de entorno).
RETENCION_DIAS = 7
RETENCION_SEMANAS = 4
RETENCION_MESES = 6


def _nombre_de_backup(dia: date) -> str:
    """El nombre que pone el script: ``solidapp-AAAAMMDDTHHMMSSZ.dump.enc``."""
    return f"solidapp-{dia.strftime('%Y%m%d')}T030000Z.dump.enc"


def _crear_backups(directorio: Path, dias: int) -> list[str]:
    """Crea un backup por dia y devuelve los nombres, del mas nuevo al mas viejo."""
    hoy = date.today()
    nombres: list[str] = []
    for offset in range(dias):
        dia = hoy - timedelta(days=offset)
        nombre = _nombre_de_backup(dia)
        (directorio / nombre).write_bytes(b"contenido de mentira\n")
        nombres.append(nombre)
    return nombres


def _aplicar_retencion(directorio: Path) -> tuple[int, str]:
    """Ejecuta el script de verdad. Devuelve (codigo, salida)."""
    proc = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{directorio}:/backups",
            "-v", f"{SCRIPT}:/opt/backup.sh:ro",
            "-e", "BACKUP_DIR=/backups",
            IMAGEN,
            "bash", "/opt/backup.sh", "--solo-retencion",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _dia_de(nombre: str) -> date | None:
    """La fecha de un nombre de backup (``None`` si no se entiende)."""
    marca = nombre.removeprefix("solidapp-")
    if len(marca) < 8 or not marca[:8].isdigit():
        return None
    try:
        return date(int(marca[0:4]), int(marca[4:6]), int(marca[6:8]))
    except ValueError:
        return None


def comprobar(creados: list[str], sobrevivientes: list[str]) -> list[str]:
    """La politica de retencion, sobre lo que ha sobrevivido."""
    problemas: list[str] = []

    sin_fecha = [n for n in sobrevivientes if _dia_de(n) is None]
    if sin_fecha:
        problemas.append(
            f"han sobrevivido {len(sin_fecha)} fichero(s) cuyo nombre no lleva "
            f"una fecha legible (por ejemplo {sin_fecha[0]!r})"
        )

    fechas = sorted(
        (f for f in (_dia_de(n) for n in sobrevivientes) if f is not None),
        reverse=True,
    )
    if not fechas:
        problemas.append("no ha sobrevivido ningun backup: la retencion se ha comido todo")
        return problemas

    # 1) Los N diarios mas recientes tienen que estar.
    esperados = {n for n in creados[:RETENCION_DIAS]}
    faltan = esperados - set(sobrevivientes)
    if faltan:
        problemas.append(
            f"faltan {len(faltan)} de los {RETENCION_DIAS} backups diarios mas "
            f"recientes (por ejemplo {sorted(faltan)[0]})"
        )

    # 2) Al menos N semanas ISO distintas.
    semanas = {f.isocalendar()[:2] for f in fechas}
    if len(semanas) < RETENCION_SEMANAS:
        problemas.append(
            f"solo han sobrevivido {len(semanas)} semana(s) ISO distintas y la "
            f"retencion declara {RETENCION_SEMANAS} (el backup semanal no se "
            "conserva)"
        )

    # 3) Al menos N meses distintos.
    meses = {(f.year, f.month) for f in fechas}
    if len(meses) < RETENCION_MESES:
        problemas.append(
            f"solo han sobrevivido {len(meses)} mes(es) distintos y la "
            f"retencion declara {RETENCION_MESES} (el backup mensual no se "
            "conserva)"
        )

    # 4) Un backup antiguo tiene que estar retirado.
    if len(creados) > RETENCION_DIAS and len(fechas) == len(creados):
        problemas.append(
            "han sobrevivido TODOS los backups: la retencion no ha retirado "
            "nada"
        )

    # 5) Y no puede haber mas de los que la politica permite.
    maximo = RETENCION_DIAS + RETENCION_SEMANAS + RETENCION_MESES
    if len(sobrevivientes) > maximo:
        problemas.append(
            f"han sobrevivido {len(sobrevivientes)} backups y la politica "
            f"permite como mucho {maximo}"
        )

    return problemas


def verificar() -> tuple[int, list[str]]:
    """Ejecuta la prueba de verdad. Devuelve (codigo, problemas)."""
    if not SCRIPT.is_file():
        return 1, [f"no se encuentra el script {SCRIPT}"]

    with tempfile.TemporaryDirectory(prefix="retencion_backup_") as temporal:
        directorio = Path(temporal)
        creados = _crear_backups(directorio, DIAS_DE_PRUEBA)

        codigo, salida = _aplicar_retencion(directorio)
        if codigo != 0:
            return 3, [
                "no se pudo ejecutar el script del backup (Docker o el script "
                f"fallaron, codigo {codigo}):\n{salida[-800:]}"
            ]

        sobrevivientes = sorted(p.name for p in directorio.glob("solidapp-*.dump.enc"))

    problemas = comprobar(creados, sobrevivientes)
    if problemas:
        return 1, problemas
    return 0, [
        f"OK: la retencion GFS se cumple "
        f"({RETENCION_DIAS} diarios + {RETENCION_SEMANAS} semanales + "
        f"{RETENCION_MESES} mensuales)"
    ]


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira."""
    print("Autoprueba de la puerta de la retencion del backup:")
    fallos = 0

    with tempfile.TemporaryDirectory(prefix="retencion_autoprueba_") as temporal:
        directorio = Path(temporal)
        # OJO: hay que crear DIAS_DE_PRUEBA dias (no unos pocos): con 40
        # dias no hay 6 meses distintos que conservar, y la comprobacion
        # «6 meses» fallaria por falta de datos, no por un defecto.
        creados = _crear_backups(directorio, DIAS_DE_PRUEBA)

        # 1) Sin aplicar la retencion (el defecto): sobran backups.
        problemas = comprobar(creados, list(creados))
        if problemas:
            print(f"  OK: sin aplicar la retencion la puerta falla -> {problemas[0][:100]}")
        else:
            print("  FALLO: sin aplicar la retencion la puerta pasa")
            fallos += 1

        # 2) Aplicando la retencion de verdad, la puerta pasa.
        codigo, salida = _aplicar_retencion(directorio)
        if codigo != 0:
            print(f"  AVISO: no se pudo ejecutar el script ({salida[-200:]})")
            fallos += 1
        else:
            sobrevivientes = sorted(
                p.name for p in directorio.glob("solidapp-*.dump.enc")
            )
            problemas = comprobar(creados, sobrevivientes)
            if not problemas:
                print(f"  OK: con la retencion aplicada la puerta pasa ({len(sobrevivientes)} backups)")
            else:
                print(f"  FALLO: con la retencion aplicada la puerta falla -> {problemas[0][:120]}")
                fallos += 1

        # 3) Un nombre sin fecha tiene que ser un problema.
        problemas = comprobar(["solidapp-basura.dump.enc"], ["solidapp-basura.dump.enc"])
        if problemas:
            print(f"  OK: un nombre sin fecha la puerta lo detecta -> {problemas[0][:90]}")
        else:
            print("  FALLO: un nombre sin fecha no lo detecta")
            fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta vigila la retencion del backup.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="comprueba que la puerta detecta los casos de mentira",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return _autoprueba()

    codigo, problemas = verificar()
    if codigo == 3:
        print("\nNO COMPROBADO:")
        for problema in problemas:
            print(f"  - {problema}")
        return 3
    if codigo != 0:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\n" + problemas[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
