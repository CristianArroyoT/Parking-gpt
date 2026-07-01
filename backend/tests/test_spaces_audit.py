"""Tests audit Fase 3B-parte-2 — spaces (create_space, update_space).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 2 handlers del router
``app/api/v1/spaces.py`` decorados con ``@audited``. Acceso requiere
``parking_context`` (gestor con membresía en la sucursal o admin).

Casos cubiertos:
  1. ``create_space`` gestor en parking 201 → audit con action=create_space.
  2. ``update_space`` gestor en parking 200 → audit con resource=spaces/{id}.
  3. ``create_space`` cliente (sin parking_context) 403 → NO crea audit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import (
    _login_headers,
    _seed_cliente,
    _seed_gestor,
    _seed_membership,
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
)


def test_create_space_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Gestor autenticado en parking crea plaza → audit con action=create_space."""
    gestor = _seed_gestor(db_session, email="gestor-space@test.es")
    parking = _seed_parking(db_session, code="P-SPACE")
    _seed_membership(db_session, user=gestor, parking=parking)
    headers = _login_headers(client, gestor.email, "gestor1234")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/spaces",
        json={"lane": "A", "number": "01", "notes": "Plaza test"},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    row = assert_audit_log(
        db_session,
        action="create_space",
        user_id=gestor.id,
        result="success",
    )
    assert row.resource is None  # create_space no tiene resource_arg.


def test_update_space_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Gestor en parking modifica plaza → audit con resource=spaces/{id}."""
    gestor = _seed_gestor(db_session, email="gestor-upd@test.es")
    parking = _seed_parking(db_session, code="P-SPACE-UPD")
    _seed_membership(db_session, user=gestor, parking=parking)
    headers = _login_headers(client, gestor.email, "gestor1234")

    # Crear plaza primero.
    r = client.post(
        f"/api/v1/parkings/{parking.id}/spaces",
        json={"lane": "B", "number": "01"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    space_id = r.json()["id"]

    # Modificarla.
    response = client.patch(
        f"/api/v1/parkings/{parking.id}/spaces/{space_id}",
        json={"is_active": False, "notes": "Desactivada"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_space",
        resource=f"spaces/{space_id}",
        user_id=gestor.id,
        result="success",
    )


def test_create_space_cliente_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Cliente (sin parking_context) crea plaza → 403, NO crea audit."""
    cliente = _seed_cliente(db_session, email="cli-space@test.es")
    parking = _seed_parking(db_session, code="P-SPACE-FORB")
    headers = _login_headers(client, cliente.email, "cliente1234")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/spaces",
        json={"lane": "C", "number": "01"},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_space")