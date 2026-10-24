"""Comprueba que el backup se lleva las fotos de los incidentes.

POR QUE esta puerta
-------------------
``infra/backup/backup.sh`` tiene el bloque de adjuntos (T-78), pero si
``ATTACHMENTS_DIR`` está vacío o no existe **avisa y sigue**: el backup
"sale bien" **sin las fotos**.

Y en el despliegue real no se le daba:

1. el ``cron`` documentado en ``infra/backup/README.md`` no lleva
   ``ATTACHMENTS_DIR``;
2. la ruta que el README exportaba (``/var/lib/solidapp/incident-attachments``)
   es la **dentro del contenedor**: desde el host (donde corre el cron) no
   existe.

Es decir: en una sucursal, el backup se hacia **sin las fotos** de los
incidentes. Al restaurar en otra maquina, la base de datos dice que las
fotos estan y los ficheros no (las descargas dan 404). Y son **datos
personales** (LOPDGDD).

QUE COMPRUEBA
-------------
- **B1**: existe un servicio ``backup`` en el compose;
- **B2**: ese servicio monta el **mismo** volumen de adjuntos que el
  backend (``incident_attachments``) en la ruta de los adjuntos;
- **B3**: define ``ATTACHMENTS_DIR`` con esa ruta (sin esto, el script
  avisa y sigue sin las fotos);
- **B4**: el ``cron`` del README ejecuta el servicio (``docker compose run
  --rm backup``) y no el script suelto.

Uso
---
    python tools/verificar_backup_adjuntos.py
    python tools/verificar_backup_adjuntos.py --autoprueba
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE = RAIZ / "docker-compose.yml"
README = RAIZ / "infra" / "backup" / "README.md"

#: La ruta de los adjuntos dentro del contenedor.
RUTA_ADJUNTOS = "/var/lib/solidapp/incident-attachments"


def _servicios(ruta: Path) -> dict[str, dict[str, object]]:
    """Extrae ``{servicio: {"environment": {...}, "volumes": [...]}}``.

    Parser propio (sin PyYAML, que no es dependencia del repo), como el de
    ``verificar_volumen_adjuntos.py``.
    """
    if not ruta.is_file():
        return {}
    servicios: dict[str, dict[str, object]] = {}
    servicio: str | None = None
    seccion: str | None = None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.strip().startswith("#"):
            continue
        sangria = len(linea) - len(linea.lstrip())
        if sangria == 2 and linea.rstrip().endswith(":"):
            servicio = linea.strip()[:-1]
            seccion = None
            servicios.setdefault(
                servicio, {"environment": {}, "volumes": [], "volumes_definido": False}
            )
            continue
        if sangria == 4 and ":" in linea:
            clave, _, resto = linea.strip().partition(":")
            clave = clave.strip()
            resto = resto.strip()
            if clave == "volumes":
                seccion = "volumes"
                if servicio is not None:
                    servicios[servicio]["volumes_definido"] = True
                    if resto.endswith("[]"):
                        lista = servicios[servicio]["volumes"]
                        assert isinstance(lista, list)
                        lista.clear()
                continue
            if clave == "environment":
                seccion = "environment"
                continue
            seccion = None
            continue
        if servicio is None:
            continue
        if seccion == "environment" and sangria >= 6 and ":" in linea:
            clave, _, valor = linea.strip().partition(":")
            entorno = servicios[servicio]["environment"]
            assert isinstance(entorno, dict)
            entorno[clave.strip()] = valor.strip().strip('"')
            continue
        if seccion == "volumes" and sangria >= 6 and linea.strip().startswith("-"):
            lista = servicios[servicio]["volumes"]
            assert isinstance(lista, list)
            lista.append(linea.strip()[1:].strip())
            continue
        if sangria <= 4:
            seccion = None
    return servicios


def comprobar(
    servicios: dict[str, dict[str, object]], readme: str
) -> list[str]:
    """Los problemas que encuentra."""
    problemas: list[str] = []

    backup = servicios.get("backup")
    if backup is None:
        return [
            "el compose no tiene un servicio `backup`: el backup se lanzaba "
            "desde el host, donde el directorio de adjuntos **no existe** "
            "(es la ruta del contenedor), asi que las fotos no se "
            "respaldaban (T-154)"
        ]

    entorno = backup.get("environment")
    assert isinstance(entorno, dict)
    ruta_adjuntos = str(entorno.get("ATTACHMENTS_DIR", ""))
    if ruta_adjuntos != RUTA_ADJUNTOS:
        problemas.append(
            f"el servicio `backup` no define ATTACHMENTS_DIR={RUTA_ADJUNTOS} "
            f"(dice {ruta_adjuntos!r}): el script avisaria y seguiria **sin "
            "las fotos** (T-154)"
        )

    lista = backup.get("volumes")
    assert isinstance(lista, list)
    monta_adjuntos = False
    for montaje in lista:
        partes = str(montaje).split(":")
        if len(partes) >= 2 and partes[1] == RUTA_ADJUNTOS:
            monta_adjuntos = True
            if not partes[0].startswith("incident_attachments"):
                problemas.append(
                    f"el servicio `backup` monta {partes[0]} en la ruta de los "
                    "adjuntos: tiene que ser el MISMO volumen que el backend "
                    "(T-141/T-154)"
                )
    if not monta_adjuntos:
        problemas.append(
            f"el servicio `backup` no monta el volumen de adjuntos en "
            f"{RUTA_ADJUNTOS}: el backup se haria sin las fotos (T-154)"
        )

    if "docker compose run --rm backup" not in readme:
        problemas.append(
            "el README no ejecuta el servicio `backup` (`docker compose run "
            "--rm backup`): el cron documentado lanzaba el script suelto, "
            "desde el host, sin el volumen de adjuntos (T-154)"
        )

    return problemas


# ── autoprueba: casos de mentira escritos a mano ────────────────────────
COMPOSE_BUENO = """services:
  backend:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
  backup:
    environment:
      ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments:ro
"""

COMPOSE_SIN_SERVICIO = """services:
  backend:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
"""

COMPOSE_SIN_ATTACHMENTS_DIR = """services:
  backup:
    environment:
      PGHOST: db
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments:ro
"""

COMPOSE_SIN_VOLUMEN = """services:
  backup:
    environment:
      ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./infra/backup:/opt/solidapp/backup:ro
"""

COMPOSE_CON_OTRO_VOLUMEN = """services:
  backup:
    environment:
      ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - otro_volumen:/var/lib/solidapp/incident-attachments:ro
"""

README_BUENO = "docker compose run --rm backup\n"


def _autoprueba() -> int:
    print("Autoprueba de la puerta del backup con adjuntos:")
    fallos = 0

    casos = [
        ("el compose no tiene servicio backup", COMPOSE_SIN_SERVICIO, README_BUENO,
         "no tiene un servicio `backup`"),
        ("el servicio no define ATTACHMENTS_DIR", COMPOSE_SIN_ATTACHMENTS_DIR,
         README_BUENO, "no define ATTACHMENTS_DIR"),
        ("el servicio no monta el volumen", COMPOSE_SIN_VOLUMEN, README_BUENO,
         "no monta el volumen de adjuntos"),
        ("el servicio monta otro volumen", COMPOSE_CON_OTRO_VOLUMEN, README_BUENO,
         "tiene que ser el MISMO volumen"),
        ("el cron no usa el servicio", COMPOSE_BUENO, "backup.sh\n",
         "no ejecuta el servicio `backup`"),
    ]
    for nombre, compose, readme, esperado in casos:
        with tempfile.TemporaryDirectory(prefix="backup_adjuntos_") as temporal:
            ruta = Path(temporal) / "docker-compose.yml"
            ruta.write_text(compose, encoding="utf-8")
            problemas = comprobar(_servicios(ruta), readme)
        if any(esperado in p for p in problemas):
            print(f"  OK: {nombre} -> {[p for p in problemas if esperado in p][0][:90]}")
        else:
            print(f"  FALLO: {nombre} no lo detecta (problemas: {problemas})")
            fallos += 1

    # Y el caso correcto no tiene que dar problemas.
    with tempfile.TemporaryDirectory(prefix="backup_adjuntos_") as temporal:
        ruta = Path(temporal) / "docker-compose.yml"
        ruta.write_text(COMPOSE_BUENO, encoding="utf-8")
        problemas = comprobar(_servicios(ruta), README_BUENO)
    if not problemas:
        print("  OK: el caso correcto no da problemas (la puerta no grita de mas)")
    else:
        print(f"  FALLO: el caso correcto dio {problemas}")
        fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta vigila que el backup lleve las fotos.")
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

    problemas = comprobar(
        _servicios(COMPOSE),
        README.read_text(encoding="utf-8") if README.is_file() else "",
    )
    if problemas:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nOK: el backup se lleva las fotos de los incidentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
