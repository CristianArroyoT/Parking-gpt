"""Tests del endpoint de geocercas con `direction` (sprint UI Dirección Cámara).

Estrategia: TestClient + SQLite en memoria + StaticPool, mismo patrón que
``test_incidents_api.py`` y ``test_alert_api.py``. El sprint 4dc5960 dejó
el modelo y `ingest_service` con `direction`, pero no añadió tests del
endpoint. Estos 5 tests cubren el gap:

  1. POST sin `direction` → default `entry` (back-compat con migración 0005).
  2. POST con `direction="exit"` → persiste el valor.
  3. PATCH `direction` → cambia el valor, devuelve 200.
  4. PATCH parcial sin tocar `direction` → el campo se preserva.
  5. GET lista expone `direction` en cada geocerca.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking, ParkingSpace
from app.models.user import User


def _seed(db) -> tuple[Parking, ParkingSpace, Camera, User]:
    admin = User(
        email="admin@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    parking = Parking(code="P-G", name="Geofence test", address="x", city="y")
    db.add_all([admin, parking])
    db.flush()
    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    cam = Camera(
        parking_id=parking.id, code="CAM-1", name="Test",
        rtsp_url="rtsp://demo/test",
    )
    db.add_all([space, cam])
    db.commit()
    db.refresh(parking); db.refresh(space); db.refresh(cam)
    return parking, space, cam, admin


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_create_geofence_default_direction_is_entry(
    client: TestClient, db_session
) -> None:
    """POST sin direction recibe el default 'entry' (back-compat)."""
    parking, space, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
        json={"parking_space_id": space.id, "x": 0, "y": 0, "w": 100, "h": 100},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["direction"] == "entry"

    fence = db_session.get(CameraGeofence, body["id"])
    assert fence is not None
    assert fence.direction == "entry"


def test_create_geofence_with_exit_direction(
    client: TestClient, db_session
) -> None:
    """POST con direction='exit' persiste el valor explícito."""
    parking, space, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
        json={
            "parking_space_id": space.id, "x": 0, "y": 0, "w": 100, "h": 100,
            "direction": "exit",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "exit"


def test_update_geofence_direction(client: TestClient, db_session) -> None:
    """PATCH direction cambia el valor y devuelve 200."""
    parking, space, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    create = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
        json={"parking_space_id": space.id, "x": 0, "y": 0, "w": 100, "h": 100},
    )
    assert create.status_code == 201
    fence_id = create.json()["id"]

    r = client.patch(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences/{fence_id}",
        headers=headers,
        json={"direction": "exit"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "exit"

    db_session.expire_all()
    fence = db_session.get(CameraGeofence, fence_id)
    assert fence is not None
    assert fence.direction == "exit"


def test_update_geofence_partial_preserves_direction(
    client: TestClient, db_session
) -> None:
    """PATCH sin tocar direction preserva el valor existente."""
    parking, space, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    create = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
        json={
            "parking_space_id": space.id, "x": 0, "y": 0, "w": 100, "h": 100,
            "direction": "exit",
        },
    )
    assert create.status_code == 201
    fence_id = create.json()["id"]

    r = client.patch(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences/{fence_id}",
        headers=headers,
        json={"confidence_threshold": 0.92},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confidence_threshold"] == 0.92
    assert body["direction"] == "exit"


def test_list_geofences_exposes_direction(client: TestClient, db_session) -> None:
    """GET lista expone direction en cada geocerca."""
    parking, space, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
        json={
            "parking_space_id": space.id, "x": 0, "y": 0, "w": 100, "h": 100,
            "direction": "exit",
        },
    )

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/geofences",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["direction"] == "exit"