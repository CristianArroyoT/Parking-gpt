"""Tests del cliente vehicle-detector y del endpoint POST /cameras/{id}/detect-vehicles.

Réplica del patrón de ``test_ocr_client.py`` con ``httpx.MockTransport`` para
no hablar con la red y poder cubrir timeout, JSON inválido, status no-200.

Los tests del endpoint usan TestClient + db_session (fixture de conftest.py).
El cliente singleton se resetea con ``reset_vehicle_detector_client()`` para
que cada test inyecte su propio MockTransport vía monkeypatch.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.parking import Camera
from app.services.vehicle_detector.client import (
    VehicleDetectorClient,
    reset_vehicle_detector_client,
)
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_parking,
)


def _make_client(handler) -> VehicleDetectorClient:
    """Crea un cliente que NO habla con la red: usa MockTransport."""
    return VehicleDetectorClient(
        base_url="http://test-vd",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
    )


def _run(coro):
    """Helper: ejecuta una coroutina en un event loop desde un test sync."""
    return asyncio.run(coro)


def _seed_camera(db: Session, parking_id: int, code: str = "CAM-VD") -> Camera:
    cam = Camera(
        parking_id=parking_id, code=code,
        name=f"Cámara {code}", rtsp_url="rtsp://demo.invalid/x", fps=10,
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


# ── Tests del cliente ──────────────────────────────────────────────────────


def test_detect_empty_list_when_service_returns_empty() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    detections = _run(client.detect(b"\xff\xd8\xff\xe0fake-jpeg-bytes"))
    assert detections == []


def test_detect_returns_empty_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=_request)

    client = _make_client(handler)
    # Importante: NO debe propagar la excepción.
    detections = _run(client.detect(b"frame"))
    assert detections == []


def test_detect_parses_one_detection_correctly() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["has_body"] = bool(request.content)
        return httpx.Response(
            200,
            json=[
                {
                    "class_name": "car",
                    "confidence": 0.92,
                    "bbox": [120, 240, 80, 60],
                }
            ],
        )

    client = _make_client(handler)
    detections = _run(client.detect(b"\xff\xd8\xff\xe0fake"))

    assert captured["method"] == "POST"
    assert captured["path"] == "/detect"
    assert captured["has_body"] is True

    assert len(detections) == 1
    assert detections[0].class_name == "car"
    assert detections[0].confidence == pytest.approx(0.92)
    assert detections[0].bbox == [120, 240, 80, 60]


def test_detect_returns_empty_on_non_200() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="YOLO engine loading")

    client = _make_client(handler)
    detections = _run(client.detect(b"frame"))
    assert detections == []


def test_detect_skips_malformed_detections() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                # válida
                {"class_name": "car", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
                # confidence fuera de rango → descartada por Pydantic
                {"class_name": "truck", "confidence": 1.5, "bbox": [0, 0, 1, 1]},
                # bbox de tamaño incorrecto → descartada
                {"class_name": "bus", "confidence": 0.5, "bbox": [0, 0]},
            ],
        )

    client = _make_client(handler)
    detections = _run(client.detect(b"frame"))
    assert len(detections) == 1
    assert detections[0].class_name == "car"


def test_detect_returns_empty_on_non_json_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _make_client(handler)
    detections = _run(client.detect(b"frame"))
    assert detections == []


# ── Tests del endpoint ─────────────────────────────────────────────────────


def test_endpoint_returns_404_when_camera_not_in_parking(
    client: TestClient, db_session: Session,
) -> None:
    """Cámara de OTRO parking → 404 (defensa contra IDs cruzados)."""
    admin = _seed_admin(db_session)
    parking_a = _seed_parking(db_session, code="P-VD-A")
    parking_b = _seed_parking(db_session, code="P-VD-B")
    _seed_camera(db_session, parking_b.id, code="CAM-VD-B")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking_a.id}/cameras/1/detect-vehicles",
        json={"image": "data:image/jpeg;base64,ZmFrZQ=="},
        headers=headers,
    )
    assert r.status_code == 404


def test_endpoint_returns_400_on_invalid_base64(
    client: TestClient, db_session: Session,
) -> None:
    """dataURL con base64 corrupto → 400 (decodificación falla)."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-VD-400")
    _seed_camera(db_session, parking.id, code="CAM-VD-400")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/1/detect-vehicles",
        json={"image": "data:image/jpeg;base64,@@@not-base64@@@"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "Imagen no válida" in r.text


def test_endpoint_returns_200_empty_when_service_unavailable(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Si el servicio vehicle-detector está caído, el cliente devuelve [] y
    el endpoint responde 200 OK con detections=[] (caller decide qué hacer)."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-VD-DOWN")
    _seed_camera(db_session, parking.id, code="CAM-VD-DOWN")
    headers = _login_headers(client, admin.email, "admin12345")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=_request)

    reset_vehicle_detector_client()
    test_client = VehicleDetectorClient(
        base_url="http://test-vd",
        timeout=1.0,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.api.v1.cameras.get_vehicle_detector_client",
        lambda: test_client,
    )

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/1/detect-vehicles",
        json={"image": "data:image/jpeg;base64,ZmFrZQ=="},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() == {"detections": []}


def test_endpoint_returns_200_with_detections(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Happy path: el servicio responde con 2 detecciones y el endpoint las
    devuelve tal cual al frontend."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-VD-OK")
    _seed_camera(db_session, parking.id, code="CAM-VD-OK")
    headers = _login_headers(client, admin.email, "admin12345")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"class_name": "car", "confidence": 0.91, "bbox": [120, 240, 80, 60]},
                {"class_name": "car", "confidence": 0.78, "bbox": [320, 250, 75, 55]},
            ],
        )

    reset_vehicle_detector_client()
    test_client = VehicleDetectorClient(
        base_url="http://test-vd",
        timeout=1.0,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.api.v1.cameras.get_vehicle_detector_client",
        lambda: test_client,
    )

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/1/detect-vehicles",
        json={"image": "data:image/jpeg;base64,ZmFrZQ=="},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["detections"]) == 2
    assert body["detections"][0]["class_name"] == "car"
    assert body["detections"][0]["bbox"] == [120, 240, 80, 60]


def test_endpoint_requires_auth(
    client: TestClient, db_session: Session,
) -> None:
    """Sin Authorization → 401 (RBAC del router)."""
    parking = _seed_parking(db_session, code="P-VD-401")
    _seed_camera(db_session, parking.id, code="CAM-VD-401")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/1/detect-vehicles",
        json={"image": "data:image/jpeg;base64,ZmFrZQ=="},
    )
    assert r.status_code == 401