"""Tests de la API del cliente final (T-24 · PWA del cliente).

Cubre ``backend/app/api/v1/cliente.py``:

- ``GET /api/v1/cliente/plazas``: la plaza ocupada **ahora mismo** por
  sus vehículos (ticket activo) con su etiqueta legible, el nombre de la
  sucursal y el aviso de avería.
- ``GET /api/v1/cliente/tickets``: sólo los tickets de sus vehículos,
  con el flag ``pending_payment`` y el filtro ``solo_pendientes``.

Lo que **no** se prueba aquí (lo cubren otros ficheros de test):
- ``GET /users/me/vehicles`` y ``GET /users/me/tickets`` → ``tests/test_user_vehicles.py`` (T-19).
- ``GET /plans/me`` → ``tests/test_plans.py`` (T-18).

Estrategia: TestClient + SQLite en memoria + StaticPool, mismo patrón
que ``test_ticket_manual.py``.

Nota sobre el montaje del router
--------------------------------
El router ``cliente`` todavía NO está registrado en
``app/api/v1/__init__.py`` (lo registra la sesión principal), así que
aquí se monta a mano sobre la app de test. Cuando se registre, este
fichero seguirá funcionando igual (FastAPI tolera el doble montaje y
manda el primer registro).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1.cliente import router as cliente_router
from app.core.db import get_db
from app.core.security import hash_password
from app.main import create_app
from app.models.enums import TicketStatus, UserRole, VehicleRole
from app.models.parking import Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser


@pytest.fixture()
def cliente_client(db_session):
    """App de test con el router ``/cliente`` montado a mano."""
    app = create_app()
    app.include_router(cliente_router, prefix="/api/v1")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client


def _seed(db):
    """Sembrar el escenario mínimo del panel del cliente."""
    ahora = datetime.now(timezone.utc)
    cliente = User(
        email="cliente@test.es",
        full_name="Cliente",
        role=UserRole.CLIENTE,
        hashed_password=hash_password("cli12345"),
    )
    otro = User(
        email="otro@test.es",
        full_name="Otro cliente",
        role=UserRole.CLIENTE,
        hashed_password=hash_password("otro12345"),
    )
    gestor = User(
        email="gestor@test.es",
        full_name="Gestor",
        role=UserRole.GESTOR,
        hashed_password=hash_password("gestor12345"),
    )
    parking = Parking(code="P-C", name="Parking Centro", address="Calle Mayor 1", city="Madrid")
    db.add_all([cliente, otro, gestor, parking])
    db.flush()

    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-07")
    db.add(space)

    vehiculo = Vehicle(plate="1234ABC", brand="Seat", model="Ibiza", color="rojo")
    vehiculo_otro = Vehicle(plate="9999XYZ", brand="Renault")
    db.add_all([vehiculo, vehiculo_otro])
    db.flush()

    db.add(VehicleUser(
        vehicle_id=vehiculo.id, user_id=cliente.id, role=VehicleRole.PROPIETARIO,
    ))
    db.add(VehicleUser(
        vehicle_id=vehiculo_otro.id, user_id=otro.id, role=VehicleRole.PROPIETARIO,
    ))

    # Coche dentro ahora mismo → plaza ocupada.
    db.add(Ticket(
        parking_id=parking.id, vehicle_id=vehiculo.id, parking_space_id=space.id,
        status=TicketStatus.ACTIVO, entry_at=ahora - timedelta(hours=2),
    ))
    # Cerrado sin método de pago → pendiente de pago (9 € de deuda).
    db.add(Ticket(
        parking_id=parking.id, vehicle_id=vehiculo.id,
        status=TicketStatus.CERRADO,
        entry_at=ahora - timedelta(days=3), exit_at=ahora - timedelta(days=2),
        amount=10.0, discount=1.0, total=9.0,
    ))
    # Cerrado y cobrado → no pendiente.
    db.add(Ticket(
        parking_id=parking.id, vehicle_id=vehiculo.id,
        status=TicketStatus.CERRADO, payment_method="efectivo",
        entry_at=ahora - timedelta(days=10), exit_at=ahora - timedelta(days=9),
        amount=5.0, discount=0.0, total=5.0,
    ))
    # Ticket de OTRO cliente: no debe aparecer nunca.
    db.add(Ticket(
        parking_id=parking.id, vehicle_id=vehiculo_otro.id,
        status=TicketStatus.CERRADO,
        entry_at=ahora - timedelta(days=1), exit_at=ahora - timedelta(hours=23),
        amount=99.0, discount=0.0, total=99.0,
    ))

    db.commit()
    return {
        "cliente": cliente, "otro": otro, "gestor": gestor,
        "parking": parking, "space": space, "vehiculo": vehiculo,
        "vehiculo_otro": vehiculo_otro,
    }


def _login(cliente_client: TestClient, email: str, password: str) -> dict[str, str]:
    r = cliente_client.post(
        "/api/v1/auth/login", json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_plazas_devuelve_la_plaza_actual(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)
    headers = _login(cliente_client, "cliente@test.es", "cli12345")

    r = cliente_client.get("/api/v1/cliente/plazas", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["plate"] == "1234ABC"
    assert body[0]["space_label"] == "A-07"
    assert body[0]["lane"] == "A"
    assert body[0]["parking_name"] == "Parking Centro"
    assert body[0]["is_broken"] is False


def test_plazas_avisa_de_plaza_averiada(cliente_client: TestClient, db_session) -> None:
    datos = _seed(db_session)
    datos["space"].is_broken = True
    db_session.commit()

    headers = _login(cliente_client, "cliente@test.es", "cli12345")
    r = cliente_client.get("/api/v1/cliente/plazas", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()[0]["is_broken"] is True


def test_plazas_vacio_si_no_hay_coche_dentro(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)
    headers = _login(cliente_client, "otro@test.es", "otro12345")

    r = cliente_client.get("/api/v1/cliente/plazas", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_tickets_solo_los_propios(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)
    headers = _login(cliente_client, "cliente@test.es", "cli12345")

    r = cliente_client.get("/api/v1/cliente/tickets", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    assert {t["plate"] for t in body} == {"1234ABC"}
    assert all(t["total"] != 99.0 for t in body)
    # Enriquecidos: nombre de sucursal y etiqueta de plaza.
    assert body[0]["parking_name"] == "Parking Centro"


def test_tickets_pendientes_de_pago(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)
    headers = _login(cliente_client, "cliente@test.es", "cli12345")

    r = cliente_client.get(
        "/api/v1/cliente/tickets", params={"solo_pendientes": True}, headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    pendiente = body[0]
    assert pendiente["pending_payment"] is True
    assert pendiente["total"] == 9.0
    assert pendiente["discount"] == 1.0
    assert pendiente["payment_method"] is None
    assert pendiente["days_pending"] == 2


def test_ticket_cobrado_no_esta_pendiente(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)
    headers = _login(cliente_client, "cliente@test.es", "cli12345")

    r = cliente_client.get("/api/v1/cliente/tickets", headers=headers)
    assert r.status_code == 200, r.text
    cobrados = [t for t in r.json() if t["payment_method"] == "efectivo"]
    assert len(cobrados) == 1
    assert cobrados[0]["pending_payment"] is False


def test_gestor_no_ve_datos_del_cliente(cliente_client: TestClient, db_session) -> None:
    """El router no filtra por rol: filtra por ``user_id``. Un gestor ve
    su propio panel (vacío), nunca el del cliente."""
    _seed(db_session)
    headers = _login(cliente_client, "gestor@test.es", "gestor12345")

    plazas = cliente_client.get("/api/v1/cliente/plazas", headers=headers)
    assert plazas.status_code == 200, plazas.text
    assert plazas.json() == []

    tickets = cliente_client.get("/api/v1/cliente/tickets", headers=headers)
    assert tickets.status_code == 200, tickets.text
    assert tickets.json() == []


def test_sin_token_401(cliente_client: TestClient, db_session) -> None:
    _seed(db_session)

    for ruta in ("/plazas", "/tickets"):
        r = cliente_client.get(f"/api/v1/cliente{ruta}")
        assert r.status_code == 401, f"{ruta} -> {r.status_code}"


def test_vehiculo_como_conductor_tambien_cuenta(cliente_client: TestClient, db_session) -> None:
    """Un vehículo compartido (el usuario es ``conductor``) también es
    suyo para la app: la plaza y los tickets se muestran igual."""
    datos = _seed(db_session)
    db_session.add(VehicleUser(
        vehicle_id=datos["vehiculo_otro"].id,
        user_id=datos["cliente"].id,
        role=VehicleRole.CONDUCTOR,
    ))
    db_session.commit()

    headers = _login(cliente_client, "cliente@test.es", "cli12345")
    r = cliente_client.get("/api/v1/cliente/tickets", headers=headers)
    assert r.status_code == 200, r.text
    # 3 tickets propios + 1 del vehículo compartido.
    assert len(r.json()) == 4
    assert {t["plate"] for t in r.json()} == {"1234ABC", "9999XYZ"}
