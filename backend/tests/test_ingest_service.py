"""Tests del servicio de ingesta (OCR → ticket).

Estrategia: BD SQLite en memoria con StaticPool (mismo patrón que
``test_ticket_close.py``). El servicio abre su propia sesión vía
``SessionLocal``, así que la fixture sustituye el símbolo
``app.services.ingest_service.SessionLocal`` por un sessionmaker que
apunta al motor de prueba.

Casos cubiertos:
  1. Cámara sin geocercas → SKIPPED_NO_GEOFENCE.
  2. Bbox fuera de toda geocerca → SKIPPED_NO_GEOFENCE.
  3. Confidence < threshold de la geocerca → SKIPPED_NO_GEOFENCE.
  4. Vehículo desconocido → INSERT + TICKET_CREATED.
  5. Vehículo existente → reusa, no duplica.
  6. Vehículo ya con ticket activo en parking → SKIPPED_DUPLICATE_ACTIVE_TICKET.
  7. Plaza ya con ticket activo → SKIPPED_SPACE_OCCUPIED.
  8. Varias geocercas matchean → elige la de mayor IoU.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — fuerza el registro de todas las tablas en Base.metadata
from app.core.db import Base
from app.models.enums import TicketStatus
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.schemas.plate import PlateHit
from app.services import ingest_service
from app.services.ingest_service import IngestStatus, process_plate_hit


@pytest.fixture()
def ingest_env(monkeypatch):
    """Crea una BD SQLite en memoria, registra modelos, y parchea
    ``ingest_service.SessionLocal`` para que el servicio escriba aquí.

    Devuelve una sesión para que los tests creen fixtures y lean
    resultados. Todos los cambios se ven a través de la misma sesión
    porque SQLite + StaticPool comparte el mismo almacenamiento.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(ingest_service, "SessionLocal", TestSessionLocal)

    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _setup_with_geofence(db, *, threshold: float = 0.85):
    """Crea parking + plaza + cámara + geocerca (0..200, 0..200)."""
    parking = Parking(code="P1", name="P1", address="x", city="y")
    db.add(parking)
    db.flush()
    space = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    db.add(space)
    db.flush()
    camera = Camera(
        parking_id=parking.id, code="CAM-01", name="Cámara 1",
        rtsp_url="rtsp://demo.invalid/x",
    )
    db.add(camera)
    db.flush()
    db.add(
        CameraGeofence(
            camera_id=camera.id,
            parking_space_id=space.id,
            x=0, y=0, w=200, h=200,
            confidence_threshold=threshold,
        )
    )
    db.commit()
    # Expulsar del identity map para que process_plate_hit (otra sesión)
    # los vea limpios. Re-fetch con el sessionlocal original es OK porque
    # comparten el motor.
    return parking, space, camera


def test_no_geofences_calibrated(ingest_env) -> None:
    """Cámara sin geocercas → SKIPPED_NO_GEOFENCE sin tocar tickets."""
    parking = Parking(code="P1", name="P1", address="x", city="y")
    ingest_env.add(parking)
    ingest_env.flush()
    camera = Camera(
        parking_id=parking.id, code="CAM-01", name="C1",
        rtsp_url="rtsp://demo.invalid/x",
    )
    ingest_env.add(camera)
    ingest_env.commit()

    hit = PlateHit(plate="1234ABC", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_NO_GEOFENCE
    assert result.reason == "Cámara sin geocercas calibradas"
    assert result.ticket_id is None
    assert ingest_env.query(Ticket).count() == 0


def test_bbox_outside_geofences(ingest_env) -> None:
    """Bbox fuera del rectángulo de la geocerca → SKIPPED_NO_GEOFENCE."""
    _setup_with_geofence(ingest_env)

    parking = ingest_env.query(Parking).one()
    camera = ingest_env.query(Camera).filter(Camera.parking_id == parking.id).one()

    # Geocerca en (0..200, 0..200); hit muy lejos.
    hit = PlateHit(plate="1234ABC", confidence=0.95, bbox=[500, 500, 600, 600])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_NO_GEOFENCE
    assert "fuera" in (result.reason or "").lower()
    assert ingest_env.query(Ticket).count() == 0


def test_low_confidence_below_threshold(ingest_env) -> None:
    """Confidence 0.5 < threshold 0.85 → no se considera, SKIPPED."""
    _setup_with_geofence(ingest_env, threshold=0.85)

    parking = ingest_env.query(Parking).one()
    camera = ingest_env.query(Camera).filter(Camera.parking_id == parking.id).one()

    hit = PlateHit(plate="1234ABC", confidence=0.5, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_NO_GEOFENCE
    assert ingest_env.query(Ticket).count() == 0
    assert ingest_env.query(Vehicle).count() == 0


def test_creates_vehicle_when_unknown_plate(ingest_env) -> None:
    """Matrícula nueva → INSERT Vehicle + TICKET_CREATED."""
    parking, space, camera = _setup_with_geofence(ingest_env)

    hit = PlateHit(plate="1234ABC", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.ticket_id is not None
    assert result.vehicle_id is not None
    assert result.parking_space_id == space.id

    # El servicio escribió en su propia sesión. Limpiamos la nuestra
    # y re-leemos del motor de prueba.
    ingest_env.expire_all()
    veh = ingest_env.get(Vehicle, result.vehicle_id)
    assert veh is not None
    assert veh.plate == "1234ABC"

    ticket = ingest_env.get(Ticket, result.ticket_id)
    assert ticket is not None
    assert ticket.parking_id == parking.id
    assert ticket.parking_space_id == space.id
    assert ticket.status == TicketStatus.ACTIVO


def test_reuses_existing_vehicle(ingest_env) -> None:
    """Matrícula ya existe → no duplica Vehicle, crea Ticket."""
    parking, space, camera = _setup_with_geofence(ingest_env)

    existing = Vehicle(plate="EXIST-1")
    ingest_env.add(existing)
    ingest_env.commit()
    existing_id = existing.id

    hit = PlateHit(plate="EXIST-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.vehicle_id == existing_id

    ingest_env.expire_all()
    assert ingest_env.query(Vehicle).count() == 1
    assert ingest_env.query(Vehicle).filter_by(plate="EXIST-1").one().id == existing_id


def test_skips_when_vehicle_already_has_active_ticket(ingest_env) -> None:
    """Misma matrícula + mismo parking + ticket activo → SKIPPED_DUPLICATE."""
    parking, space, camera = _setup_with_geofence(ingest_env)

    veh = Vehicle(plate="DUP-1")
    ingest_env.add(veh)
    ingest_env.flush()
    ingest_env.add(
        Ticket(
            parking_id=parking.id,
            vehicle_id=veh.id,
            parking_space_id=space.id,
            status=TicketStatus.ACTIVO,
            entry_at=datetime.now(timezone.utc),
        )
    )
    ingest_env.commit()

    hit = PlateHit(plate="DUP-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_DUPLICATE_ACTIVE_TICKET
    assert result.ticket_id is not None  # referencia al ticket previo
    assert ingest_env.query(Ticket).count() == 1  # no se duplica


def test_skips_when_space_already_occupied(ingest_env) -> None:
    """Otra persona ocupa la plaza → SKIPPED_SPACE_OCCUPIED."""
    parking, space, camera = _setup_with_geofence(ingest_env)

    other = Vehicle(plate="OTHER-1")
    ingest_env.add(other)
    ingest_env.flush()
    ingest_env.add(
        Ticket(
            parking_id=parking.id,
            vehicle_id=other.id,
            parking_space_id=space.id,
            status=TicketStatus.ACTIVO,
            entry_at=datetime.now(timezone.utc),
        )
    )
    ingest_env.commit()

    hit = PlateHit(plate="NEW-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_SPACE_OCCUPIED
    assert result.parking_space_id == space.id
    assert ingest_env.query(Ticket).count() == 1  # no se crea el segundo


def test_selects_geofence_with_best_iou(ingest_env) -> None:
    """Dos geocercas matchean el bbox → se asigna la de mayor IoU."""
    parking = Parking(code="P1", name="P1", address="x", city="y")
    ingest_env.add(parking)
    ingest_env.flush()
    space1 = ParkingSpace(parking_id=parking.id, lane="A", number="A-01")
    space2 = ParkingSpace(parking_id=parking.id, lane="A", number="A-02")
    ingest_env.add_all([space1, space2])
    ingest_env.flush()
    camera = Camera(
        parking_id=parking.id, code="CAM-01", name="C1",
        rtsp_url="rtsp://demo.invalid/x",
    )
    ingest_env.add(camera)
    ingest_env.flush()
    ingest_env.add_all(
        [
            CameraGeofence(
                camera_id=camera.id, parking_space_id=space1.id,
                x=0, y=0, w=100, h=100, confidence_threshold=0.85,
            ),
            CameraGeofence(
                camera_id=camera.id, parking_space_id=space2.id,
                x=200, y=200, w=100, h=100, confidence_threshold=0.85,
            ),
        ]
    )
    ingest_env.commit()

    # Hit dentro de geocerca 2 (250..270), solapa muy poco con geocerca 1 (0..100).
    # IoU con 2 >> IoU con 1.
    hit = PlateHit(plate="NEW-1", confidence=0.95, bbox=[250, 250, 270, 270])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.parking_space_id == space2.id