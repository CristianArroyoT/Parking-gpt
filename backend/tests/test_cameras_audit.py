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


# ── Sprint Fase 4: Camera.kind (surveillance | gate) ─────────────────

def test_create_camera_default_kind_is_surveillance(
    client: TestClient, db_session: Session,
) -> None:
    """Crear cámara sin ``kind`` explícito → la respuesta trae
    ``kind="surveillance"`` (back-compat con cámaras pre-Fase 4)."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-KIND-DEF")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-DEF",
            "name": "Cámara por defecto",
            "rtsp_url": "rtsp://test.invalid/default",
            "fps": 10,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "surveillance"


def test_create_camera_with_kind_gate(
    client: TestClient, db_session: Session,
) -> None:
    """Crear cámara con ``kind=gate`` (portería) → la respuesta lo refleja."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-KIND-GATE")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-GATE-1",
            "name": "Cámara portería entrada",
            "rtsp_url": "rtsp://test.invalid/gate-in",
            "fps": 15,
            "kind": "gate",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "gate"

    # GET lista también expone el kind.
    r2 = client.get(
        f"/api/v1/parkings/{parking.id}/cameras",
        headers=headers,
    )
    assert r2.status_code == 200
    cameras = r2.json()
    assert any(c["code"] == "CAM-GATE-1" and c["kind"] == "gate" for c in cameras)


def test_update_camera_kind(
    client: TestClient, db_session: Session,
) -> None:
    """PATCH de cámara cambiando ``surveillance`` → ``gate``."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-KIND-UPD")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json={
            "code": "CAM-UPD-K",
            "name": "Cámara a recategorizar",
            "rtsp_url": "rtsp://test.invalid/recategorize",
            "fps": 10,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    camera_id = r.json()["id"]
    assert r.json()["kind"] == "surveillance"

    r2 = client.patch(
        f"/api/v1/parkings/{parking.id}/cameras/{camera_id}",
        json={"kind": "gate"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["kind"] == "gate"