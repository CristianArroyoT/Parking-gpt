"""Tests audit Fase 3B-parte-2 — tariffs (create_tariff, update_tariff, delete_tariff).

Sprint Fase 3B-parte-2 (2026-07-01). Cubre los 3 handlers del router
``app/api/v1/tariffs.py`` decorados con ``@audited``. create/update
requieren ``parking_context`` (gestor con membresía); delete está
restringido a admin.

Casos cubiertos:
  1. ``create_tariff`` admin 201 → audit con action=create_tariff.
  2. ``update_tariff`` admin 200 → audit con resource=tariffs/{id}.
  3. ``delete_tariff`` admin 204 → audit con resource=tariffs/{id}.
  4. ``create_tariff`` cliente 403 → NO crea audit.
"""
from __future__ import annotations

from datetime import datetime, timezone

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


def _tariff_payload(parking_id: int) -> dict:
    """Payload mínimo válido para ``POST /parkings/{id}/tariffs``.

    Schema ``TariffCreate`` (de ``app/schemas/pricing.py``) requiere
    ``parking_id`` en el body. El handler ahora (post-fix 3B-parte-2)
    lo toma de ``payload.parking_id`` directamente — antes había un
    doble-kwarg en ``Tariff(parking_id=parking_id, **payload.dump())``.
    """
    return {
        "parking_id": parking_id,
        "name": "Tarifa Test",
        "price_per_hour": 2.5,
        "price_per_fraction": 0.7,
        "fraction_minutes": 15,
        "max_daily": 25.0,
        "valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    }


def test_create_tariff_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin crea tarifa → audit con action=create_tariff, result=success."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-TAR")
    headers = _login_headers(client, admin.email, "admin12345")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    )
    assert response.status_code == 201, response.text

    row = assert_audit_log(
        db_session,
        action="create_tariff",
        user_id=admin.id,
        result="success",
    )
    assert row.resource is None


def test_update_tariff_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin modifica tarifa → audit con resource=tariffs/{id}."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-TAR-U")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    tariff_id = r.json()["id"]

    response = client.patch(
        f"/api/v1/parkings/{parking.id}/tariffs/{tariff_id}",
        json={"price_per_hour": 3.0, "name": "Tarifa Modificada"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert_audit_log(
        db_session,
        action="update_tariff",
        resource=f"tariffs/{tariff_id}",
        user_id=admin.id,
        result="success",
    )


def test_delete_tariff_creates_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Admin borra tarifa → audit con resource=tariffs/{id}."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-TAR-D")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    tariff_id = r.json()["id"]

    response = client.delete(
        f"/api/v1/parkings/{parking.id}/tariffs/{tariff_id}",
        headers=headers,
    )
    assert response.status_code == 204, response.text

    assert_audit_log(
        db_session,
        action="delete_tariff",
        resource=f"tariffs/{tariff_id}",
        user_id=admin.id,
        result="success",
    )


def test_create_tariff_cliente_403_no_audit_log(
    client: TestClient, db_session: Session
) -> None:
    """Cliente intenta crear tarifa → 403, NO crea audit."""
    cliente = _seed_cliente(db_session, email="cli-tar@test.es")
    parking = _seed_parking(db_session, code="P-TAR-FORB")
    headers = _login_headers(client, cliente.email, "cliente1234")

    response = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert_no_audit_log(db_session, action="create_tariff")