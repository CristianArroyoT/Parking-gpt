"""Regresión del sondeo de heartbeat EN PARALELO (T-13+4).

Antes, ``probe_heartbeats`` sondeaba las cámaras de una en una con un
``asyncio.run()`` por cámara. Con 50 cámaras y 5 s de timeout por cámara la
ronda tardaba hasta ~250 s y **monopolizaba un slot del pool** de Celery:
el ``celery inspect ping`` del healthcheck no se respondía en 10 s, el
contenedor pasaba a *unhealthy* y en Swarm/K8s el worker se reiniciaba en
bucle sin llegar a terminar la ronda.

El test es determinista: la tercera cámara sólo termina su probe si las
tres se estaban sondeando **a la vez**. Con el bucle secuencial, el
primer probe se quedaría esperando un evento que nadie puede activar
porque las otras dos cámaras aún no han empezado → timeout → falla.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.parking import Camera, Parking
from app.models.user import User


@pytest.fixture()
def camaras(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> list[Camera]:
    """Tres cámaras activas en una sucursal, todas con URL sondeable."""
    parking = Parking(code="P-PAR", name="Paralelo", address="C 1", city="Madrid")
    db_session.add(parking)
    db_session.commit()

    usuario = User(
        email="paralelo@test.es",
        full_name="Paralelo",
        role=UserRole.ADMIN,
        hashed_password=hash_password("paralelo1234"),
    )
    db_session.add(usuario)
    db_session.commit()

    lista = []
    for i in range(3):
        cam = Camera(
            parking_id=parking.id,
            code=f"CAM-PAR-{i}",
            name=f"Cámara {i}",
            rtsp_url=f"rtsp://paralelo-{i}.invalid/stream",
            fps=10,
            is_active=True,
        )
        db_session.add(cam)
        lista.append(cam)
    db_session.commit()
    for cam in lista:
        db_session.refresh(cam)
    return lista


def test_el_sondeo_de_heartbeat_es_paralelo(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, camaras: list[Camera]
) -> None:
    """Las tres cámaras se sondean a la vez, no una detrás de otra."""
    from app.workers import tasks as tasks_mod

    arrancadas = 0
    todas_arrancadas = asyncio.Event()

    async def _probe_simulado(cam: Camera) -> bool:
        nonlocal arrancadas
        arrancadas += 1
        if arrancadas == len(camaras):
            todas_arrancadas.set()
        # Si el sondeo fuera secuencial, este primer probe esperaría un
        # evento que no puede llegar: se quedaría colgado hasta el timeout.
        await asyncio.wait_for(todas_arrancadas.wait(), timeout=3)
        return True

    monkeypatch.setattr(tasks_mod, "probe_camera", _probe_simulado)
    monkeypatch.setattr(tasks_mod, "record_camera_offline", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    resultado = tasks_mod.probe_heartbeats()

    assert arrancadas == len(camaras)
    assert resultado["ok"] == len(camaras), (
        "las cámaras no se sondearon en paralelo: la ronda tardaría lo mismo "
        "que la suma de los timeouts"
    )
