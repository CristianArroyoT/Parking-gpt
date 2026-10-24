"""T-166 (2026-10-24): el push externo no debe persistir basura.

El defecto
----------
``POST /parkings/{id}/cameras/{id}/plates`` (el camino real de datos:
el push del fabricante) creaba y persistía una fila de ``plates_detected``
por **cada** hit del payload, **sin filtrar**. El filtro
``parece_matricula`` sólo se aplicaba después, dentro de
``process_plate_hits``, que **ignora** la lectura: no crea vehículo ni
ticket, pero la fila basura ya estaba en la base de datos.

Medido (2026-10-24, contra la API en marcha): un push con una
matrícula buena y dos basura ("SIN PLACA" y "###") dejó **2 filas de
basura** en ``plates_detected`` (ids 15 y 16), y el gestor las veía en
``GET /parkings/{id}/plates-detected``.

El arreglo
----------
El endpoint filtra **antes de persistir** (igual que ya hacía el worker
``ping_camera``), y **loguea** lo que descarta.

Lo que NO cambia: el contrato de la respuesta. Sigue habiendo **un
resultado por hit**, y los descartados vuelven con su motivo
``skipped_not_a_plate`` (lo decide ``process_plate_hits``).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import CameraKind, UserRole
from app.models.parking import Camera, Parking
from app.models.plates_detected import PlatesDetected
from app.models.user import ParkingMembership, User


def _seed(db: Session) -> tuple[Parking, User, Camera]:
    gestor = User(
        email="gestor@push166.es",
        full_name="Gestor",
        role=UserRole.GESTOR,
        hashed_password=hash_password("gestor12345"),
    )
    parking = Parking(code="P-PUSH166", name="Sucursal", address="x", city="y")
    db.add_all([gestor, parking])
    db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking.id))
    camara = Camera(
        parking_id=parking.id,
        code="CAM-PUSH166",
        name="Cámara",
        rtsp_url="rtsp://demo.invalid/166",
        fps=10,
        kind=CameraKind.SURVEILLANCE,
    )
    db.add(camara)
    db.commit()
    for obj in (parking, gestor, camara):
        db.refresh(obj)
    return parking, gestor, camara


def _headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _filas(db: Session, camera: Camera) -> list[PlatesDetected]:
    db.expire_all()
    return (
        db.query(PlatesDetected)
        .filter(PlatesDetected.camera_id == camera.id)
        .order_by(PlatesDetected.id)
        .all()
    )


def test_el_push_no_persiste_una_lectura_que_no_es_matricula(
    client: TestClient, db_session: Session,
) -> None:
    """La basura del OCR no puede acabar en ``plates_detected``."""
    parking, gestor, camara = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={
            "hits": [
                {"plate": "1234ABC", "confidence": 0.93, "bbox": [10, 20, 110, 80]},
                {"plate": "SIN PLACA", "confidence": 0.41, "bbox": [200, 20, 260, 60]},
                {"plate": "###", "confidence": 0.35, "bbox": [300, 20, 330, 50]},
            ]
        },
    )
    assert r.status_code == 201, r.text

    # El contrato de la respuesta NO cambia: un resultado por hit.
    body = r.json()
    assert len(body) == 3
    por_placa = {item["plate"]: item["status"] for item in body}
    assert por_placa["1234ABC"] != "skipped_not_a_plate"
    assert por_placa["SIN PLACA"] == "skipped_not_a_plate"
    assert por_placa["###"] == "skipped_not_a_plate"

    # Pero en la base de datos sólo queda la matrícula buena.
    filas = _filas(db_session, camara)
    assert [f.plate for f in filas] == ["1234ABC"], (
        f"se persistieron lecturas que no son matrículas: "
        f"{[f.plate for f in filas]}"
    )
    assert filas[0].confidence == 0.93
    assert filas[0].bbox_x1 == 10
    assert filas[0].bbox_y2 == 80


def test_un_push_solo_de_basura_no_persiste_nada(
    client: TestClient, db_session: Session,
) -> None:
    """Si no hay ninguna matrícula, no se escribe ninguna fila."""
    parking, gestor, camara = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={
            "hits": [
                {"plate": "CAM 01", "confidence": 0.5, "bbox": [1, 2, 3, 4]},
                {"plate": "SOLIDAPP", "confidence": 0.4, "bbox": [5, 6, 7, 8]},
            ]
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body) == 2
    assert all(item["status"] == "skipped_not_a_plate" for item in body)

    assert _filas(db_session, camara) == []


def test_el_listado_no_enseña_la_basura(
    client: TestClient, db_session: Session,
) -> None:
    """Lo que el gestor ve en el listado es lo único que se persistió."""
    parking, gestor, camara = _seed(db_session)
    headers = _headers(client, gestor.email, "gestor12345")

    client.post(
        f"/api/v1/parkings/{parking.id}/cameras/{camara.id}/plates",
        headers=headers,
        json={
            "hits": [
                {"plate": "1234ABC", "confidence": 0.93, "bbox": [10, 20, 110, 80]},
                {"plate": "SIN PLACA", "confidence": 0.41, "bbox": [200, 20, 260, 60]},
            ]
        },
    )

    r = client.get(
        f"/api/v1/parkings/{parking.id}/plates-detected", headers=headers
    )
    assert r.status_code == 200, r.text
    assert [p["plate"] for p in r.json()] == ["1234ABC"]
