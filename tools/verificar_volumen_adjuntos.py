"""Comprueba que el backend, el worker y el beat comparten el volumen de
adjuntos.

POR QUÉ esta puerta
-------------------
Las fotos de los incidentes **no** van en la base de datos: van en un
volumen Docker, y en la BD sólo queda la metadata (T-21). La purga de
retención (90 días, LOPDGDD) la ejecuta el **worker**: borra las filas y
los ficheros.

El fallo (T-141, 2026-10-24): el ``backend`` montaba el volumen con
nombre ``incident_attachments``, pero el ``celery-worker`` y el
``celery-beat`` **no montaban ninguno**. Como el ``Dockerfile`` declara
``VOLUME ["/var/lib/solidapp/incident-attachments"]``, Docker les creaba
un volumen **anónimo** distinto a cada uno. Medido:

    # en el worker (con su volumen anonimo):
    RESULTADO DE LA PURGA: {'deleted': 4}      <-- exito aparente
    # en el volumen del backend:
    originales/56/56ec35a3...jpg                <-- el fichero sigue ahi
    originales/64/64078f24a...jpg

Es decir: la BD decia que las fotos ya no existian y los ficheros se
quedaban en el disco **para siempre**, sin que nadie se enterase. La
retencion no se cumplia.

QUE COMPRUEBA
-------------
- **V1**: los tres servicios montan ``/var/lib/solidapp/incident-attachments``.
- **V2**: los tres montan **el mismo** origen (el volumen con nombre). Si
  el worker usara otro, no veria lo que escribio el backend.
- **V3**: los tres definen ``INCIDENT_ATTACHMENTS_DIR`` con esa misma ruta
  (si no, cada proceso busca en su sitio).
- **V4**: el compose de **produccion** no quita ese volumen. Ojo: en
  compose, una lista **reemplaza** a la anterior, no se anade: si el
  compose de produccion declarase ``volumes:`` para el worker, perderia
  el de adjuntos.

Uso
---
    python tools/verificar_volumen_adjuntos.py
    python tools/verificar_volumen_adjuntos.py --autoprueba
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE_DEV = RAIZ / "docker-compose.yml"
COMPOSE_PROD = RAIZ / "docker-compose.prod.yml"

#: Donde vive el volumen de los adjuntos (dentro del contenedor).
RUTA_ADJUNTOS = "/var/lib/solidapp/incident-attachments"

#: Los servicios que tienen que compartirlo.
SERVICIOS = ("backend", "celery-worker", "celery-beat")


def _servicios(ruta: Path) -> dict[str, dict[str, object]]:
    """Extrae ``{servicio: {"environment": {...}, "volumes": [...]}}``.

    Parser propio (sin PyYAML, que no es dependencia del repo), como el
    de ``verificar_compose_produccion.py``.
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
        # Cualquier clave de servicio (sangria 4) abre su seccion. OJO:
        # ``healthcheck: !override`` y ``volumes: !override []`` no terminan
        # en ":", asi que hay que mirar la clave, no el final de la linea.
        if sangria == 4 and ":" in linea:
            clave, _, resto = linea.strip().partition(":")
            clave = clave.strip()
            resto = resto.strip()
            if clave == "volumes":
                seccion = "volumes"
                if servicio is not None:
                    servicios[servicio]["volumes_definido"] = True
                    if resto.endswith("[]"):
                        # ``volumes: !override []``: lista explicita y VACIA.
                        # En compose una lista REEMPLAZA a la anterior.
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


def _origen_de(montaje: str) -> tuple[str, str]:
    """``origen:destino[:opciones]`` → ``(origen, destino)``."""
    partes = montaje.split(":")
    if len(partes) == 1:
        return partes[0], partes[0]
    return partes[0], partes[1]


def _montajes_de(servicios: dict[str, dict[str, object]], nombre: str) -> list[str]:
    servicio = servicios.get(nombre)
    if not servicio:
        return []
    lista = servicio.get("volumes")
    if not isinstance(lista, list):
        return []
    return [str(item) for item in lista]


def _entorno_de(servicios: dict[str, dict[str, object]], nombre: str) -> dict[str, str]:
    servicio = servicios.get(nombre)
    if not servicio:
        return {}
    entorno = servicio.get("environment")
    if not isinstance(entorno, dict):
        return {}
    return {str(k): str(v) for k, v in entorno.items()}


def comprobar(
    servicios_dev: dict[str, dict[str, object]],
    servicios_prod: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    """Los problemas que encuentra en el compose."""
    problemas: list[str] = []

    if not servicios_dev:
        return ["no se encuentra docker-compose.yml (o no se ha podido leer)"]

    origenes: dict[str, str] = {}
    for nombre in SERVICIOS:
        montajes = _montajes_de(servicios_dev, nombre)
        destino = None
        origen = None
        for montaje in montajes:
            candidato_origen, candidato_destino = _origen_de(montaje)
            if candidato_destino == RUTA_ADJUNTOS:
                origen = candidato_origen
                destino = candidato_destino
                break
        if destino is None:
            problemas.append(
                f"{nombre}: no monta `{RUTA_ADJUNTOS}`: el worker (y el beat) "
                "no verian los ficheros que escribe el backend (T-141)"
            )
            continue
        origenes[nombre] = origen or ""

        entorno = _entorno_de(servicios_dev, nombre)
        ruta = entorno.get("INCIDENT_ATTACHMENTS_DIR")
        if ruta is None:
            problemas.append(
                f"{nombre}: no define INCIDENT_ATTACHMENTS_DIR: cada proceso "
                "buscaria los adjuntos en su sitio"
            )
        elif ruta.rstrip("/") != RUTA_ADJUNTOS:
            problemas.append(
                f"{nombre}: INCIDENT_ATTACHMENTS_DIR es {ruta!r} y el volumen "
                f"está en {RUTA_ADJUNTOS!r}: el proceso miraria en un sitio "
                "donde no hay nada"
            )

    # V2: los tres tienen que montar **el mismo** volumen.
    distintos = set(origenes.values())
    if len(distintos) > 1:
        detalle = ", ".join(f"{k}={v}" for k, v in sorted(origenes.items()))
        problemas.append(
            f"los servicios no comparten el volumen de adjuntos ({detalle}): "
            "el worker no veria lo que escribio el backend (T-141)"
        )

    # V4: el compose de produccion no puede quitar el volumen (las listas se
    # REEMPLAZAN en compose, no se anaden).
    if servicios_prod:
        for nombre in SERVICIOS:
            servicio = servicios_prod.get(nombre)
            if not servicio:
                continue
            if not servicio.get("volumes_definido"):
                continue  # no lo redefine: hereda el del compose de desarrollo
            montajes = _montajes_de(servicios_prod, nombre)
            if not any(_origen_de(m)[1] == RUTA_ADJUNTOS for m in montajes):
                problemas.append(
                    f"docker-compose.prod.yml: {nombre} redefine `volumes:` sin "
                    f"`{RUTA_ADJUNTOS}`: en compose una lista REEMPLAZA a la "
                    "anterior, asi que en la sucursal el worker no veria los "
                    "adjuntos (T-141)"
                )

    return problemas


# ── autoprueba: casos de mentira escritos a mano ────────────────────────

COMPOSE_BUENO = """services:
  backend:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./backend:/app
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-worker:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./backend:/app
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-beat:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./backend:/app
      - incident_attachments:/var/lib/solidapp/incident-attachments
"""

# El defecto real: el worker no monta el volumen.
COMPOSE_SIN_VOLUMEN_EN_EL_WORKER = """services:
  backend:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-worker:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./backend:/app
  celery-beat:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - ./backend:/app
"""

# Otro volumen distinto: el worker no ve lo que escribio el backend.
COMPOSE_CON_VOLUMEN_DISTINTO = """services:
  backend:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-worker:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - otro_volumen:/var/lib/solidapp/incident-attachments
  celery-beat:
    environment:
      INCIDENT_ATTACHMENTS_DIR: /var/lib/solidapp/incident-attachments
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
"""

# Sin la variable de entorno: el proceso busca en otro sitio.
COMPOSE_SIN_VARIABLE = """services:
  backend:
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-worker:
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
  celery-beat:
    volumes:
      - incident_attachments:/var/lib/solidapp/incident-attachments
"""

# El compose de produccion quita el volumen (las listas se reemplazan).
PROD_SIN_VOLUMEN = """services:
  celery-worker:
    volumes: !override []
"""


def _autoprueba() -> int:
    """La puerta tiene que detectar los casos de mentira y callar con el bueno."""
    fallos = 0
    with tempfile.TemporaryDirectory(prefix="volumen_adjuntos_") as temporal:
        raiz = Path(temporal)
        compose = raiz / "docker-compose.yml"
        prod = raiz / "docker-compose.prod.yml"

        casos = [
            ("el worker no monta el volumen", COMPOSE_SIN_VOLUMEN_EN_EL_WORKER, None,
             "no monta"),
            ("el worker monta OTRO volumen", COMPOSE_CON_VOLUMEN_DISTINTO, None,
             "no comparten el volumen"),
            ("falta INCIDENT_ATTACHMENTS_DIR", COMPOSE_SIN_VARIABLE, None,
             "no define INCIDENT_ATTACHMENTS_DIR"),
            ("produccion quita el volumen", COMPOSE_BUENO, PROD_SIN_VOLUMEN,
             "redefine `volumes:`"),
        ]
        for nombre, dev, prod_texto, esperado in casos:
            compose.write_text(dev, encoding="utf-8")
            if prod_texto is not None:
                prod.write_text(prod_texto, encoding="utf-8")
            elif prod.exists():
                prod.unlink()
            problemas = comprobar(
                _servicios(compose), _servicios(prod) if prod.exists() else None
            )
            if any(esperado in p for p in problemas):
                print(f"  OK: {nombre} -> {[p for p in problemas if esperado in p][0][:100]}")
            else:
                print(f"  FALLO: {nombre} no lo detecta (problemas: {problemas})")
                fallos += 1

        # Y el caso correcto no tiene que dar problemas.
        compose.write_text(COMPOSE_BUENO, encoding="utf-8")
        if prod.exists():
            prod.unlink()
        problemas = comprobar(_servicios(compose))
        if not problemas:
            print("  OK: el caso correcto no da problemas (la puerta no grita de mas)")
        else:
            print(f"  FALLO: el caso correcto dio {problemas}")
            fallos += 1

    if fallos:
        print(f"Autoprueba FALLIDA: {fallos} caso(s).")
        return 1
    print("Autoprueba correcta: la puerta vigila el volumen de adjuntos.")
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
        _servicios(COMPOSE_DEV),
        _servicios(COMPOSE_PROD) if COMPOSE_PROD.is_file() else None,
    )
    if problemas:
        print(f"\n{len(problemas)} problema(s):\n")
        for problema in problemas:
            print(f"  - {problema}")
        return 1
    print("\nOK: el backend, el worker y el beat comparten el volumen de adjuntos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
