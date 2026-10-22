"""T-79: crear incidentes y subir adjuntos tienen rate-limit por endpoint.

POR QUÉ (2026-10-22): los endpoints que más recursos consumen del
backend —crear un incidente (fila en la BD) y subir sus fotos (hasta 3
ficheros de 10 MB, que al generar la miniatura se descomprimen enteros:
150 MB por foto de 50 MP)— NO pasaban por el ``EndpointRateLimiter``: los
scopes existentes eran ``users_*``, ``vehicles_*``, ``parkings_*``,
``tariffs_*``, ``cameras_*`` y ``geofences_*``. O sea que un **operador**
autenticado (el rol con menos permisos) podía crear incidentes y subir
fotos **sin límite de peticiones**.

Con el arreglo, los dos endpoints pasan por
``enforce_endpoint_rate_limit`` (la función única de T-69) y el límite es
el general por defecto (30 por minuto y actor): de sobra para el flujo
real (una entrada de coche = un incidente) y corta el abuso.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.parking import Parking, ParkingSpace
from app.models.user import ParkingMembership, User
from app.core.security import hash_password


def _patched_limit(monkeypatch: pytest.MonkeyPatch, max_attempts: int) -> None:
    """Parchea el limite por endpoint (el binding vive en su modulo)."""
    from app.core import config as cfg_mod
    from app.services import endpoint_rate_limit as erl_mod

    def _patched():
        real = cfg_mod.get_settings()
        field_names = (
            list(real.model_fields.keys())
            if hasattr(real, "model_fields")
            else [a for a in dir(real) if not a.startswith("_")]
        )
        data = {name: getattr(real, name) for name in field_names}
        data["endpoint_rate_limit_max_attempts"] = max_attempts
        return SimpleNamespace(**data)

    monkeypatch.setattr(erl_mod, "get_settings", _patched)


def _seed(db: Session) -> tuple[Parking, ParkingSpace, User]:
    """Un parking, una plaza y un operador (el rol con menos permisos)."""
    operador = User(
        email="operador-rl@test.es", full_name="Operador",
        role=UserRole.OPERADOR, hashed_password=hash_password("oper12345"),
    )
    parking = Parking(code="P-RL", name="RL", address="x", city="y")
    db.add_all([operador, parking])
    db.flush()
    # Sin la membresia, el endpoint responde 403 ("no tiene acceso a esta
    # sucursal") antes de llegar al rate-limit.
    db.add(ParkingMembership(user_id=operador.id, parking_id=parking.id))
    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    db.add(space)
    db.commit()
    db.refresh(parking)
    db.refresh(space)
    return parking, space, operador


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_crear_incidente_tiene_rate_limit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-79: a partir de N, crear incidentes el operador recibe 429."""
    _patched_limit(monkeypatch, max_attempts=2)
    parking, space, operador = _seed(db_session)
    headers = _login(client, operador.email, "oper12345")

    cuerpo = {
        "kind": "space_broken",
        "parking_space_id": space.id,
        "reason": "physical_damage",
        "notes": "hueco en el suelo",
    }
    for i in range(2):
        r = client.post(
            f"/api/v1/incidents/parkings/{parking.id}", headers=headers, json=cuerpo
        )
        # El alta es idempotente: la segunda vez la plaza ya esta averiada
        # y responde 200 con {"noop": true}. Lo que se comprueba es que NO
        # da 429.
        assert r.status_code in (200, 201), f"intento {i}: {r.status_code} {r.text}"
        assert r.status_code != 429, f"intento {i}: {r.text}"

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}", headers=headers, json=cuerpo
    )
    assert r.status_code == 429, (
        f"crear incidentes no esta limitado: {r.status_code} {r.text}"
    )
    assert "Demasiadas" in r.text


def test_el_rate_limit_de_incidentes_es_por_actor(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El bloqueo es por actor: otro operador de la misma sucursal no topa."""
    _patched_limit(monkeypatch, max_attempts=1)
    parking, space, operador = _seed(db_session)
    otro = User(
        email="operador-rl-2@test.es", full_name="Otro operador",
        role=UserRole.OPERADOR, hashed_password=hash_password("oper12345"),
    )
    db_session.add(otro)
    db_session.flush()
    db_session.add(ParkingMembership(user_id=otro.id, parking_id=parking.id))
    db_session.commit()

    cuerpo = {
        "kind": "space_broken",
        "parking_space_id": space.id,
        "reason": "physical_damage",
        "notes": "hueco en el suelo",
    }
    headers_1 = _login(client, operador.email, "oper12345")
    headers_2 = _login(client, otro.email, "oper12345")

    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}", headers=headers_1, json=cuerpo
    )
    assert r.status_code == 201, r.text
    # El segundo actor tiene su propio bucket: no le bloquea el del otro.
    r = client.post(
        f"/api/v1/incidents/parkings/{parking.id}", headers=headers_2, json=cuerpo
    )
    # La plaza ya esta averiada (la puso el primer actor), asi que el
    # alta es un noop: lo que importa es que NO sea 429.
    assert r.status_code in (200, 201), (
        f"el rate-limit se compartio entre actores: {r.status_code} {r.text}"
    )
    assert r.status_code != 429, "el rate-limit se compartio entre actores"
