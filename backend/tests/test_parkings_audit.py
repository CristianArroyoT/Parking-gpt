"""Tests audit Fase 3B-parte-2 — parkings (create_parking, update_parking, delete_parking).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 3 handlers del router
``app/api/v1/parkings.py`` decorados con ``@audited``. Verifica que cada
operación CRUD admin-only deja una fila en ``audit_logs`` con la action
correcta y ``user_id`` propagado desde el JWT, y que un RBAC failure
(gestor autenticado intentando mutar) NO crea audit (porque el decorador
``audited`` sólo cubre el cuerpo del handler, no la resolución de
``Depends``).

Casos cubiertos:
  1. ``create_parking`` admin 201 → audit con action=create_parking.
  2. ``update_parking`` admin 200 → audit con action=update_parking +
     resource="parkings/{id}".
  3. ``delete_parking`` admin 204 → audit con action=delete_parking +
     resource="parkings/{id}".
  4. ``create_parking`` gestor 403 → NO crea audit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_gestor,
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
)


def test_create_parking_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea parking → audit con action=create_parking, result=success."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.post(
        "/api/v1/parkings",
        json={
            "code": "P-NEW-1",
            "name": "Sucursal Audit",
            "address": "Calle Audit 1",
            "city": "Madrid",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    parking_id = response.json()["id"]

    row = assert_audit_log(
        db_session,
        action="create_parking",
        user_id=admin.id,
        result="success",
    )
    assert row.resource is None  # create_parking no tiene resource_arg.
    assert row.duration_ms is not None
    assert row.duration_ms >= 0


def test_update_parking_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin modifica parking → audit con action=update_parking + resource populado."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-UP-1")
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.patch(
        f"/api/v1/parkings/{parking.id}",
        json={"name": "Sucursal Renombrada"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_parking",
        resource=f"parkings/{parking.id}",
        user_id=admin.id,
        result="success",
    )


def test_delete_parking_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin borra parking → audit con action=delete_parking + resource."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-DEL-1")
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.delete(
        f"/api/v1/parkings/{parking.id}",
        headers=headers,
    )
    assert response.status_code == 204, response.text

    assert_audit_log(
        db_session,
        action="delete_parking",
        resource=f"parkings/{parking.id}",
        user_id=admin.id,
        result="success",
    )


def test_create_parking_gestor_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Gestor intenta crear parking → 403, NO se crea audit (decorator post-dep)."""
    gestor = _seed_gestor(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")

    response = client.post(
        "/api/v1/parkings",
        json={
            "code": "P-NO-PERM",
            "name": "No debería crearse",
            "address": "Calle X",
            "city": "Madrid",
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_parking")