"""Tests del filtro de matrículas del camino del OCR (T-52, 2026-10-22).

El OCR devuelve TEXTO, no matrículas. Con el vídeo de QA del repo (que
lleva el rótulo "SOLIDAPP QA — CAM 01" y el timestamp "t=105.0s frame=2625"
**quemados en la imagen**), el OCR devolvió la "matrícula"
``t=105.0sframe=2625``.

Estos tests comprueban dos cosas:

1. La regla ``parece_matricula`` acepta las matrículas legítimas
   (formato español actual, antiguo y diplomático) y rechaza el texto
   quemado.
2. Un hit que no es una matrícula **no crea vehículo ni ticket** (lo
   más importante: ``vehicles.plate`` es UNIQUE, así que una basura
   corta se quedaría **para siempre** en la base).
"""
from __future__ import annotations

import pytest

from app.schemas.plate import PlateHit
from app.services.ingest_service import (
    IngestStatus,
    process_plate_hit,
)
from app.services.plates import (
    normalizar_matricula,
    parece_matricula,
)
# La fixture ``ingest_env`` parchea ``ingest_service.SessionLocal`` para
# que el servicio escriba en la BD de test, y ``_setup_with_geofence``
# crea parking + plaza + cámara + geocerca. Se importan aquí (pytest
# registra los fixtures importados como fixtures del módulo).
from tests.test_ingest_service import (  # noqa: F401
    _setup_with_geofence,
    ingest_env as ingest_env,
)

#: Lecturas que NO son matrículas, con lo que las produjo de verdad.
#:
#: OJO: ``"HD 1080P"`` **no** está en la lista, y es a propósito: tiene
#: exactamente la misma forma que una matrícula antigua ("M 1234 A") o
#: diplomática ("E 1234 A"), así que **ningún formato las distingue**.
#: Ese caso se filtra en la práctica por el cruce con la geocerca (el
#: rótulo quemado está en una esquina, fuera del rectángulo pintado) y
#: por el umbral de confianza. Documentado, no escondido.
NO_MATRICULAS = [
    "t=105.0sframe",        # el timestamp quemado del vídeo de QA
    "t=1.0s",               # lo mismo, más corto
    "CAM 01",               # el rótulo de la esquina
    "SOLIDAPP",             # el nombre de la marca
    "2026-10-22",           # una fecha
    "P1-A-01",              # el nombre de una plaza
    "00:00:12",             # la hora de un rótulo
]

#: Matrículas que SÍ deben aceptarse.
SI_MATRICULAS = [
    "1234ABC",   # formato español actual
    "1234AB",
    "1234B",     # antiguo (4 dígitos + letra de provincia)
    "E1234",     # diplomática
    "M1234A",
    "5555LOW",   # el de los datos de prueba del repo
    "9999ZZZ",
    "ABC123",   # formato alemán (3 letras + 3 dígitos)
    " 1234ABC ",  # con espacios alrededor
    "1234-ABC",   # con guion
]


@pytest.mark.parametrize("texto", NO_MATRICULAS)
def test_texto_que_no_es_matricula_se_rechaza(texto: str) -> None:
    """El texto quemado en la imagen no pasa por matrícula."""
    assert not parece_matricula(texto), f"{texto!r} no debería ser matrícula"


@pytest.mark.parametrize("texto", SI_MATRICULAS)
def test_matricula_legitima_se_acepta(texto: str) -> None:
    """Las matrículas reales pasan, con o sin separadores."""
    assert parece_matricula(texto), f"{texto!r} debería ser matrícula"


def test_normalizar_quita_separadores_y_pasa_a_mayusculas() -> None:
    assert normalizar_matricula(" 1234-abc ") == "1234ABC"


def test_un_hit_que_no_es_matricula_no_crea_vehiculo_ni_ticket(ingest_env) -> None:
    """El caso grave: una basura NO puede quedarse en la base para siempre.

    ``vehicles.plate`` es UNIQUE: si un texto cualquiera se aceptara, se
    crearía un vehículo fantasma permanente, y si la geocerca estuviera
    pintada encima, un ticket.
    """
    from app.models.ticket import Ticket
    from app.models.vehicle import Vehicle

    _parking, _space, camera = _setup_with_geofence(ingest_env)
    antes_vehiculos = ingest_env.query(Vehicle).count()
    antes_tickets = ingest_env.query(Ticket).count()

    hit = PlateHit(
        plate="CAM 01",
        confidence=0.97,
        bbox=[10, 10, 200, 200],
    )
    resultado = process_plate_hit(hit, camera)

    assert resultado.status == IngestStatus.SKIPPED_NOT_A_PLATE
    assert resultado.vehicle_id is None
    assert resultado.ticket_id is None
    assert ingest_env.query(Vehicle).count() == antes_vehiculos
    assert ingest_env.query(Ticket).count() == antes_tickets


def test_el_esquema_ya_rechaza_el_timestamp_mas_largo() -> None:
    """El caso que se vio de verdad: 19 caracteres no llegan ni a la base.

    El texto quemado del vídeo de QA mide 19 ("t=105.0sframe=2625") y
    el esquema (``max_length=16``) lo rechaza antes de llegar al
    servicio. Por eso el caso grave es el de un rótulo **corto**: ése sí
    pasaba.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PlateHit(plate="t=105.0sframe=2625", confidence=0.97, bbox=[1, 2, 3, 4])


def test_una_matricula_de_verdad_si_crea_vehiculo(ingest_env) -> None:
    """El filtro no puede comerse las matrículas buenas."""
    from app.models.vehicle import Vehicle

    _parking, _space, camera = _setup_with_geofence(ingest_env)
    hit = PlateHit(plate="1234ABC", confidence=0.97, bbox=[10, 10, 200, 200])
    resultado = process_plate_hit(hit, camera)

    assert resultado.status != IngestStatus.SKIPPED_NOT_A_PLATE
    assert ingest_env.query(Vehicle).count() == 1
    assert ingest_env.query(Vehicle).one().plate == "1234ABC"
