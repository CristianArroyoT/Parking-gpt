"""Tests audit Fase 3B-parte-2 — cameras (create_camera, update_camera).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 2 handlers del router
``app/api/v1/cameras.py`` decorados con ``@audited``. Acceso requiere
``parking_context``. NO cubre ``/geofences`` (instrumentado en Fase 3A)
ni ``/health`` (sólo lectura).

Casos cubiertos:
  1. ``create_camera`` admin 201 → audit con action=create_camera.
  2. ``update_camera`` admin 200 → audit con resource=cameras/{id}.
  3. ``create_camera`` cliente 403 → NO crea audit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
)


def test_create_camera_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea cámara → audit con action=create_camera, result=success."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-CAM")
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-A1",
            "name": "Cámara entrada A",
            "rtsp_url": "rtsp://test.invalid/stream1",
            "lane_hint": "A",
            "fps": 10,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    camera_id = response.json()["id"]

    row = assert_audit_log(
        db_session,
        action="create_camera",
        user_id=admin.id,
        result="success",
    )
    assert row.resource is None  # create_camera no tiene resource_arg.


def test_update_camera_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin modifica cámara → audit con resource=cameras/{id}."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-CAM-UPD")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-U1",
            "name": "Cámara a actualizar",
            "rtsp_url": "rtsp://test.invalid/stream2",
            "fps": 10,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    camera_id = r.json()["id"]

    response = client.patch(
        f"/api/v1/parkings/{parking.id}/cameras/{camera_id}",
        json={"fps": 15, "is_active": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_camera",
        resource=f"cameras/{camera_id}",
        user_id=admin.id,
        result="success",
    )


def test_create_camera_cliente_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Cliente intenta crear cámara → 403, NO crea audit."""
    cliente = _seed_cliente(db_session, email="cli-cam@test.es")
    parking = _seed_parking(db_session, code="P-CAM-FORB")
    headers = _login_headers(client, cliente.email, "cliente1234")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-X",
            "name": "Sin Permiso",
            "rtsp_url": "rtsp://test.invalid/stream-x",
            "fps": 10,
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_camera")