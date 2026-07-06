"""Tests del rate-limit aplicado en Sprint R5 (2026-07-06).

Cubre los 3 routers extendidos: ``parkings``, ``tariffs``, ``cameras``
(POST y PATCH cada uno = 6 endpoints nuevos con rate-limit). Se usa
el mismo helper ``_force_endpoint_settings`` que ya parchea
``endpoint_rate_limit_max_attempts`` a un valor bajo para forzar el
bloqueo en pocos intentos.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.parking import Parking
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_parking,
    assert_audit_log,
)


def _seed_parkings(db: Session, codes: list[str]) -> list[int]:
    """Sembrar N parkings directamente en BD.

    Se usa en los tests de DELETE para evitar que las siembras POST
    disparen el rate-limit del scope ``parkings_create`` (cada test
    ya parchea ``max_attempts=2``; sembrar vía POST necesitaría un
    parche más laxo para no chocar con el bucket).
    """
    ids: list[int] = []
    for code in codes:
        p = Parking(code=code, name=f"Test {code}",
                    address="Calle Test 1", city="Madrid")
        db.add(p)
        db.commit()
        db.refresh(p)
        ids.append(p.id)
    return ids


# ── helpers ────────────────────────────────────────────────────────────

def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def _force_endpoint_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_attempts: int,
    window_seconds: int = 60,
) -> None:
    """Parchea ``get_settings`` en el módulo donde está bindeado."""
    from app.services import endpoint_rate_limit as erl_mod
    from app.core import config as cfg_mod

    def _patched():
        real = cfg_mod.get_settings()
        field_names = (
            list(real.model_fields.keys())
            if hasattr(real, "model_fields")
            else [a for a in dir(real) if not a.startswith("_")]
        )
        data = {name: getattr(real, name) for name in field_names}
        data["endpoint_rate_limit_max_attempts"] = max_attempts
        data["endpoint_rate_limit_window_seconds"] = window_seconds
        return SimpleNamespace(**data)

    monkeypatch.setattr(erl_mod, "get_settings", _patched)


def _parking_payload(code: str) -> dict:
    return {
        "code": code, "name": f"Sucursal {code}",
        "address": "Calle 1", "city": "Madrid",
    }


def _tariff_payload(parking_id: int) -> dict:
    return {
        "parking_id": parking_id,
        "name": "Tarifa estándar",
        "price_per_hour": 1.5,
        "price_per_fraction": 0.05,
        "valid_from": "2026-01-01T00:00:00+00:00",
    }


def _camera_payload(code: str) -> dict:
    return {
        "code": code, "name": f"Cámara {code}",
        "rtsp_url": "rtsp://test.invalid/x", "fps": 10,
    }


# ── parkings ───────────────────────────────────────────────────────────

def test_create_parking_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /parkings`` admin: ``max_attempts + 1`` → 429."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(2):
        r = client.post(
            "/api/v1/parkings",
            json=_parking_payload(f"P-R5-{i}"),
            headers=headers,
        )
        assert r.status_code == 201, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        "/api/v1/parkings",
        json=_parking_payload("P-R5-99"),
        headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


def test_update_parking_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PATCH /parkings/{id}`` admin: tras N updates → 429."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-UPD")
    headers = _login_headers(client, admin.email, "admin12345")

    for _ in range(2):
        r = client.patch(
            f"/api/v1/parkings/{parking.id}",
            json={"name": "Renombrada"},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    r = client.patch(
        f"/api/v1/parkings/{parking.id}",
        json={"name": "Otra vez"},
        headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


# ── tariffs ────────────────────────────────────────────────────────────

def test_create_tariff_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /parkings/{id}/tariffs`` → 429 tras N intentos."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-TAR")
    headers = _login_headers(client, admin.email, "admin12345")

    for _ in range(2):
        r = client.post(
            f"/api/v1/parkings/{parking.id}/tariffs",
            json=_tariff_payload(parking.id),
            headers=headers,
        )
        assert r.status_code == 201, r.text

    r = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


def test_update_tariff_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PATCH /parkings/{id}/tariffs/{tid}`` → 429 tras N updates."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-TAR-UPD")
    headers = _login_headers(client, admin.email, "admin12345")

    created = client.post(
        f"/api/v1/parkings/{parking.id}/tariffs",
        json=_tariff_payload(parking.id),
        headers=headers,
    ).json()
    tariff_id = created["id"]

    # Bucket ``tariffs_update`` empieza en 0. Con ``max_attempts=2``
    # el primer PATCH deja count=1 (≤2), el segundo count=2 (≤2) y el
    # tercero count=3 (>2) → 429. Los scopes ``tariffs_create`` y
    # ``tariffs_update`` son independientes, así que el create previo
    # no contamina este bucket.
    for i in range(2):
        r = client.patch(
            f"/api/v1/parkings/{parking.id}/tariffs/{tariff_id}",
            json={"price_per_hour": 2.0 + i * 0.1},
            headers=headers,
        )
        assert r.status_code == 200, f"patch {i}: {r.status_code} {r.text}"

    r = client.patch(
        f"/api/v1/parkings/{parking.id}/tariffs/{tariff_id}",
        json={"price_per_hour": 2.9},
        headers=headers,
    )
    assert r.status_code == 429, (
        f"esperaba 429 tras 3 patches, obtuve {r.status_code}: {r.text}"
    )


# ── cameras ────────────────────────────────────────────────────────────

def test_create_camera_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /parkings/{id}/cameras`` admin → 429 tras N creates."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-CAM")
    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(2):
        r = client.post(
            f"/api/v1/parkings/{parking.id}/cameras",
            json=_camera_payload(f"CAM-R5-{i}"),
            headers=headers,
        )
        assert r.status_code == 201, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json=_camera_payload("CAM-R5-99"),
        headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


def test_update_camera_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PATCH /parkings/{id}/cameras/{cid}`` admin → 429 tras N updates."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-CAM-UPD")
    headers = _login_headers(client, admin.email, "admin12345")

    created = client.post(
        f"/api/v1/parkings/{parking.id}/cameras",
        json=_camera_payload("CAM-R5-UPD"),
        headers=headers,
    ).json()
    camera_id = created["id"]

    for i in range(2):
        r = client.patch(
            f"/api/v1/parkings/{parking.id}/cameras/{camera_id}",
            json={"fps": 10 + i},
            headers=headers,
        )
        assert r.status_code == 200, f"update {i}: {r.status_code} {r.text}"

    r = client.patch(
        f"/api/v1/parkings/{parking.id}/cameras/{camera_id}",
        json={"fps": 99},
        headers=headers,
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}: {r.text}"


# ── audit log ──────────────────────────────────────────────────────────

def test_r5_rate_limit_audit_log(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloqueo en cualquiera de los 3 routers escribe audit_log
    ``action=rate_limited_endpoint`` con ``payload.scope`` correcto."""
    _force_endpoint_settings(monkeypatch, max_attempts=1)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-AUDIT")
    headers = _login_headers(client, admin.email, "admin12345")

    # Saturar parkings_create con 2 POST.
    client.post(
        "/api/v1/parkings",
        json=_parking_payload("P-R5-AUDIT-1"),
        headers=headers,
    )
    client.post(
        "/api/v1/parkings",
        json=_parking_payload("P-R5-AUDIT-2"),
        headers=headers,
    )

    row = assert_audit_log(
        db_session,
        action="rate_limited_endpoint",
        user_id=admin.id,
        result="failure",
    )
    assert row.payload is not None
    assert row.payload["scope"] == "parkings_create"
    assert row.payload["bucket"].startswith("rl:parkings_create:")


# ── DELETE follow-up (2026-07-06) ────────────────────────────────────
# Push security review encontró que el rate-limit del Sprint R5 sólo
# cubría POST/PATCH. Aplicamos paridad a los 3 handlers DELETE
# destructivos del mismo grupo de routers: un bucle de borrados
# degrada la operación igual que un bucle de parches. Cada test sigue
# el mismo patrón (max_attempts=2, ``max_attempts + 1`` → 429).


def test_delete_parking_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DELETE /parkings/{id}`` admin: tras N borrados → 429."""
    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    # Sembrar en BD directa: evita que las siembras POST disparen
    # el bucket ``parkings_create`` (ya parcheado a max_attempts=2).
    ids = _seed_parkings(db_session, ["P-R5-DEL-0", "P-R5-DEL-1", "P-R5-DEL-2"])

    for i in range(2):
        r = client.delete(f"/api/v1/parkings/{ids[i]}", headers=headers)
        assert r.status_code == 204, f"delete {i}: {r.status_code} {r.text}"

    r = client.delete(f"/api/v1/parkings/{ids[2]}", headers=headers)
    assert r.status_code == 429, (
        f"esperaba 429 tras 3 deletes, obtuve {r.status_code}: {r.text}"
    )


def test_delete_tariff_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DELETE /parkings/{id}/tariffs/{tid}`` admin → 429 tras N."""
    from app.models.pricing import Tariff

    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-TDEL")
    headers = _login_headers(client, admin.email, "admin12345")

    # Sembrar 3 tarifas en BD directa por la misma razón del test anterior.
    from datetime import datetime, timedelta, timezone
    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tariff_ids: list[int] = []
    for i in range(3):
        t = Tariff(
            parking_id=parking.id, name=f"tarifa-{i}",
            price_per_hour=1.5, price_per_fraction=0.05,
            valid_from=valid_from + timedelta(minutes=i),
        )
        db_session.add(t)
        db_session.commit()
        db_session.refresh(t)
        tariff_ids.append(t.id)

    for i in range(2):
        r = client.delete(
            f"/api/v1/parkings/{parking.id}/tariffs/{tariff_ids[i]}",
            headers=headers,
        )
        assert r.status_code == 204, f"delete {i}: {r.status_code} {r.text}"

    r = client.delete(
        f"/api/v1/parkings/{parking.id}/tariffs/{tariff_ids[2]}",
        headers=headers,
    )
    assert r.status_code == 429, (
        f"esperaba 429, obtuve {r.status_code}: {r.text}"
    )


def test_delete_geofence_blocks_after_max_attempts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DELETE /parkings/{id}/cameras/{cid}/geofences/{fid}`` → 429.

    El scope ``geofences_delete`` tiene bucket independiente de
    ``geofences_create`` (que no se invoca aquí; creamos las geocercas
    por BD directamente para mantener el test centrado en el DELETE).
    """
    from app.models.geofence import CameraGeofence
    from app.models.parking import Camera
    from app.models.user import ParkingMembership

    _force_endpoint_settings(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-R5-GDEL")
    headers = _login_headers(client, admin.email, "admin12345")

    # Membership admin → parking (admin pasa por parking_context pero
    # añadimos membresía por uniformidad con el resto de tests).
    db_session.add(ParkingMembership(
        user_id=admin.id, parking_id=parking.id,
    ))
    db_session.commit()

    # Sembrar plaza + cámara + 3 geocercas en BD. Cada geocerca necesita
    # su propia ``parking_space_id`` por la UniqueConstraint del modelo.
    from app.models.parking import ParkingSpace
    camera = Camera(
        parking_id=parking.id, code="CAM-R5-GDEL",
        name="Cámara test", rtsp_url="rtsp://test.invalid/x", fps=10,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)

    fence_ids: list[int] = []
    for i in range(3):
        sp = ParkingSpace(parking_id=parking.id, lane="A", number=f"{i + 1}",
                          is_active=True)
        db_session.add(sp)
        db_session.commit()
        db_session.refresh(sp)
        f = CameraGeofence(
            camera_id=camera.id, parking_space_id=sp.id,
            x=0, y=i * 10.0, w=20.0, h=20.0,
        )
        db_session.add(f)
        db_session.commit()
        db_session.refresh(f)
        fence_ids.append(f.id)

    for i in range(2):
        r = client.delete(
            f"/api/v1/parkings/{parking.id}/cameras/{camera.id}/geofences/{fence_ids[i]}",
            headers=headers,
        )
        assert r.status_code == 204, f"delete {i}: {r.status_code} {r.text}"

    r = client.delete(
        f"/api/v1/parkings/{parking.id}/cameras/{camera.id}/geofences/{fence_ids[2]}",
        headers=headers,
    )
    assert r.status_code == 429, (
        f"esperaba 429, obtuve {r.status_code}: {r.text}"
    )


def test_delete_followup_audit_log(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloqueo de DELETE escribe audit con ``payload.scope``
    correcto (verifica ``parkings_delete``)."""
    _force_endpoint_settings(monkeypatch, max_attempts=1)
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    ids = _seed_parkings(db_session, ["P-R5-DAUD-0", "P-R5-DAUD-1"])

    # 1º delete OK (count=1 ≤ max_attempts=1), 2º delete (count=2 > 1) → 429.
    assert client.delete(f"/api/v1/parkings/{ids[0]}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/parkings/{ids[1]}", headers=headers).status_code == 429

    row = assert_audit_log(
        db_session,
        action="rate_limited_endpoint",
        user_id=admin.id,
        result="failure",
    )
    assert row.payload["scope"] == "parkings_delete"
    assert row.payload["bucket"].startswith("rl:parkings_delete:")