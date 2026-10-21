"""Tests del router de placas (OCR).

Estos dos endpoints eran los **unicos sin ningun test** de los 99 de
la API (medido con ``tools/cobertura_api.py``):

  GET  /api/v1/parkings/{parking_id}/plates-detected
  POST /api/v1/parkings/{parking_id}/cameras/{camera_id}/plates

Lo que se comprueba:

  1. Sin token → 401.
  2. Un usuario sin membresía en la sucursal → 403 (parking_context).
  3. El listado devuelve las matriculas de ESA sucursal, ordenadas de
     la más reciente a la más antigua.
  4. ``camera_id`` filtra por cámara.
  5. ``limit`` se valida (0 y 501 → 422; el defecto es 50 y el tope
     500).
  6. No se filtran matriculas de otra sucursal.
  7. El POST responde 404 si la cámara no es de esa sucursal.
  8. El POST persiste una fila por hit y devuelve el resultado de la
     ingesta (sin geocerca, el hit se skipea).
  9. Un bbox que no son 4 enteros → 422.
 10. El POST exige membresía (403 sin ella).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import pytest

from app.core.security import hash_password
from app.models.enums import CameraKind, UserRole
from app.models.parking import Camera, Parking
from app.models.plates_detected import PlatesDetected
from app.models.user import ParkingMembership, User


def _seed(db: Session) -> tuple[Parking, Parking, User, User, User, Camera, Camera]:
    """Crea dos sucursales, tres usuarios y dos cámaras (una por sucursal)."""
    admin = User(
        email="admin@plates.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )
    gestor = User(
        email="gestor@plates.es",
        full_name="Gestor",
        role=UserRole.GESTOR,
        hashed_password=hash_password("gestor12345"),
    )
    otro = User(
        email="otro@plates.es",
        full_name="Otro gestor",
        role=UserRole.GESTOR,
        hashed_password=hash_password("otro12345"),
    )
    parking = Parking(code="P-PLATES", name="Sucursal con permiso", address="x", city="y")
    parking_ajena = Parking(code="P-AJENA", name="Sucursal ajena", address="x", city="y")
    db.add_all([admin, gestor, otro, parking, parking_ajena])
    db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking.id))
    camara = Camera(
        parking_id=parking.id, code="CAM-PLATES", name="Cámara con permiso",
        rtsp_url="rtsp://demo.invalid/1", fps=10, kind=CameraKind.SURVEILLANCE,
    )
    camara_ajena = Camera(
        parking_id=parking_ajena.id, code="CAM-AJENA", name="Cámara ajena",
        rtsp_url="rtsp://demo.invalid/2", fps=10, kind=CameraKind.SURVEILLANCE,
    )
    db.add_all([camara, camara_ajena])
    db.commit()
    for obj in (parking, parking_ajena, admin, gestor, otro, camara, camara_ajena):
        db.refresh(obj)
    return parking, parking_ajena, admin, gestor, otro, camara, camara_ajena


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email, password)}"}


def _placa(db: Session, camera: Camera, plate: str, minutos: int) -> PlatesDetected:
    ahora = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    fila = PlatesDetected(
        camera_id=camera.id,
        plate=plate,
        confidence=0.93,
        bbox_x1=10, bbox_y1=20, bbox_x2=110, bbox_y2=80,
        detected_at=ahora,
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila


# ── GET /plates-detected ─────────────────────────────────────────────


def test_listar_placas_sin_token_devuelve_401(
    client: TestClient, db_session: Session,
) -> None:
    parking, *_ = _seed(db_session)
    r = client.get(f"/api/v1/parkings/{parking.id}/plates-detected")
    assert r.status_code == 401


def test_listar_placas_sin_membresia_devuelve_403(
    client: TestClient, db_session: Session,
) -> None:
    """Un gestor de otra sucursal no ve las matriculas ajenas."""
    parking, _ajena, _admin, _gestor, otro, camara, _camara_ajena = _seed(db_session)
    _placa(db_session, camara, "1234ABC", minutos=0)
    headers = _headers(client, otro.email, "otro12345")
    r = client.get(f"/api/v1/parkings/{parking.id}/plates-detected", headers=headers)
    assert r.status_code == 403, r.text


def test_listar_placas_devuelve_las_de_la_sucursal_ordenadas(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, gestor, _otro, camara, camara_ajena = _seed(db_session)
    _placa(db_session, camara, "1111AAA", minutos=5)
    _placa(db_session, camara, "2222BBB", minutos=1)
    _placa(db_session, camara_ajena, "9999ZZZ", minutos=0)

    headers = _headers(client, gestor.email, "gestor12345")
    r = client.get(f"/api/v1/parkings/{parking.id}/plates-detected", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # La de la otra sucursal NO aparece: es otro parking.
    assert [p["plate"] for p in body] == ["2222BBB", "1111AAA"]
    assert body[0]["camera_id"] == camara.id
    assert body[0]["confidence"] == pytest.approx(0.93)


def test_listar_placas_filtra_por_camara(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, gestor, _otro, camara, camara_ajena = _seed(db_session)
    _placa(db_session, camara, "1111AAA", minutos=1)
    _placa(db_session, camara_ajena, "2222BBB", minutos=0)

    headers = _headers(client, gestor.email, "gestor12345")
    r = client.get(
        f"/api/v1/parkings/{parking.id}/plates-detected?camera_id={camara.id}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [p["plate"] for p in r.json()] == ["1111AAA"]


def test_listar_placas_valida_el_limite(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, gestor, _otro, _camara, _ca = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")
    for limite in (0, 501):
        r = client.get(
            f"/api/v1/parkings/{parking.id}/plates-detected?limit={limite}",
            headers=headers,
        )
        assert r.status_code == 422, f"limit={limite} devolvió {r.status_code}"


# ── POST /cameras/{camera_id}/plates ─────────────────────────────────


def test_crear_placas_sin_membresia_devuelve_403(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, _gestor, otro, camara, _ca = _seed(db_session)
    headers = _headers(client, otro.email, "otro12345")
    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={"hits": []},
    )
    assert r.status_code == 403, r.text


def test_crear_placas_de_una_camara_ajena_devuelve_404(
    client: TestClient, db_session: Session,
) -> None:
    """La cámara tiene que ser de la sucursal del path."""
    parking, _ajena, _admin, gestor, _otro, _camara, camara_ajena = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")
    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara_ajena.id}/plates",
        headers=headers,
        json={"hits": []},
    )
    assert r.status_code == 404, r.text


def test_crear_placas_persiste_y_devuelve_el_resultado(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, gestor, _otro, camara, _ca = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")
    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={
            "hits": [
                {
                    "plate": "1234ABC",
                    "confidence": 0.91,
                    "bbox": [10, 20, 110, 80],
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["plate"] == "1234ABC"
    assert body[0]["camera_id"] == camara.id
    # Sin geocercas en la cámara, el hit no genera ticket.
    assert body[0]["status"] == "skipped_no_geofence"

    # Y queda persistida la fila cruda (auditoría de la lectura OCR).
    db_session.expire_all()
    filas = db_session.query(PlatesDetected).filter(
        PlatesDetected.camera_id == camara.id,
    ).all()
    assert len(filas) == 1
    assert filas[0].plate == "1234ABC"
    assert filas[0].bbox_x1 == 10
    assert filas[0].bbox_y2 == 80


def test_crear_placas_rechaza_un_bbox_invalido(
    client: TestClient, db_session: Session,
) -> None:
    parking, _ajena, _admin, gestor, _otro, camara, _ca = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")
    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={
            "hits": [
                {"plate": "1234ABC", "confidence": 0.91, "bbox": [10, 20, 110]},
            ],
        },
    )
    assert r.status_code == 422, r.text
