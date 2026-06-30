"""Tests del servicio de ingesta (OCR → ticket ENTRADA/SALIDA).

Estrategia: BD SQLite en memoria con StaticPool (mismo patrón que
``test_ticket_close.py``). El servicio abre su propia sesión vía
``SessionLocal``, así que la fixture sustituye el símbolo
``app.services.ingest_service.SessionLocal`` por un sessionmaker que
apunta al motor de prueba.

Casos cubiertos:
  1. Cámara sin geocercas → SKIPPED_NO_GEOFENCE.
  2. Bbox fuera de toda geocerca → SKIPPED_NO_GEOFENCE.
  3. Confidence < threshold de la geocerca → SKIPPED_LOW_CONFIDENCE.
  4. Vehículo desconocido → INSERT + TICKET_CREATED.
  5. Vehículo existente → reusa, no duplica.
  6. Vehículo con ticket activo → SALIDA: cierra con tarifa, TICKET_CLOSED.
  7. SALIDA sin tarifa vigente → SKIPPED_CLOSE_FAILED, ticket sigue activo.
  8. SALIDA con suscripción del vehículo → descuento aplicado.
  9. Plaza ya con ticket activo de OTRO vehículo → SKIPPED_SPACE_OCCUPIED.
 10. Varias geocercas matchean → elige la de mayor IoU.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — fuerza el registro de todas las tablas en Base.metadata
from app.core.db import Base
from app.models.enums import TicketStatus
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking, ParkingSpace
from app.models.pricing import Plan, Subscription, Tariff
from app.models.ticket import Ticket
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, VehicleRole, VehicleUser
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
    return parking, space, camera


def _add_tariff(db, parking_id: int, *, valid_from=None) -> Tariff:
    """Crea una tarifa vigente estándar para que ``calculate_ticket_total``
    no lance ``PricingError``."""
    return Tariff(
        parking_id=parking_id,
        name="Estándar",
        price_per_hour=2.0,
        price_per_fraction=0.5,
        fraction_minutes=15,
        valid_from=valid_from or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


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
    """Confidence 0.5 < threshold 0.85 → SKIPPED_LOW_CONFIDENCE (granular)."""
    _setup_with_geofence(ingest_env, threshold=0.85)

    parking = ingest_env.query(Parking).one()
    camera = ingest_env.query(Camera).filter(Camera.parking_id == parking.id).one()

    hit = PlateHit(plate="1234ABC", confidence=0.5, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_LOW_CONFIDENCE
    assert result.confidence == 0.5
    assert result.reason and "confidence" in result.reason.lower()
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


def test_closes_active_ticket_on_second_hit(ingest_env) -> None:
    """Vehículo con ticket activo → SALIDA: cierra y calcula tarifa."""
    parking, space, camera = _setup_with_geofence(ingest_env)
    ingest_env.add(_add_tariff(ingest_env, parking.id))
    ingest_env.commit()

    veh = Vehicle(plate="EXIT-1")
    ingest_env.add(veh)
    ingest_env.flush()
    entry = datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)
    ingest_env.add(
        Ticket(
            parking_id=parking.id,
            vehicle_id=veh.id,
            parking_space_id=space.id,
            status=TicketStatus.ACTIVO,
            entry_at=entry,
        )
    )
    ingest_env.commit()

    # Forzamos exit_at exacto a 1h30 después del entry_at para evitar
    # drift de microsegundos entre el datetime.now() del servicio y el del
    # test (un drift > 0 hace que las fracciones redondeen a 3 en lugar
    # de 2). Con 1h30 exactos: 1 h × 2 € + ceil(30/15)=2 × 0.50 € = 3 €.
    fixed_exit = entry + timedelta(hours=1, minutes=30)

    hit = PlateHit(plate="EXIT-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera, now=fixed_exit)

    assert result.status == IngestStatus.TICKET_CLOSED
    assert result.ticket_id is not None
    assert result.amount == 3.0
    assert result.discount == 0.0
    assert result.total == 3.0

    ingest_env.expire_all()
    ticket = ingest_env.get(Ticket, result.ticket_id)
    assert ticket.status == TicketStatus.CERRADO
    assert ticket.exit_at is not None
    assert ticket.amount == 3.0
    assert ticket.total == 3.0


def test_close_fails_without_active_tariff(ingest_env) -> None:
    """SALIDA sin tarifa vigente → SKIPPED_CLOSE_FAILED, ticket sigue activo."""
    parking, space, camera = _setup_with_geofence(ingest_env)
    # SIN tarifa — calculate_ticket_total lanzará PricingError.

    veh = Vehicle(plate="NOFARE-1")
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

    hit = PlateHit(plate="NOFARE-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_CLOSE_FAILED
    assert result.ticket_id is not None  # ticket previo referenciado
    assert result.reason and "tarifa" in result.reason.lower()

    ingest_env.expire_all()
    ticket = ingest_env.get(Ticket, result.ticket_id)
    assert ticket.status == TicketStatus.ACTIVO  # no se cerró


def test_close_applies_subscription_discount(ingest_env) -> None:
    """Vehículo vinculado a usuario con plan activo → descuento aplicado al cerrar."""
    parking, space, camera = _setup_with_geofence(ingest_env)
    ingest_env.add(_add_tariff(ingest_env, parking.id))

    # Usuario con plan activo al 20%
    user = User(
        email="subs@test.es",
        full_name="Subs User",
        role=UserRole.CLIENTE,
        hashed_password="x",
    )
    plan = Plan(
        code="EMPRESA",
        name="Empresa",
        monthly_price=200.0,
        discount_percent=20.0,
        included_vehicles=10,
        is_active=True,
    )
    ingest_env.add_all([user, plan])
    ingest_env.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )
    veh = Vehicle(plate="SUB-1")
    ingest_env.add_all([sub, veh])
    ingest_env.flush()
    ingest_env.add(
        VehicleUser(
            vehicle_id=veh.id, user_id=user.id, role=VehicleRole.PROPIETARIO,
        )
    )
    entry = datetime.now(timezone.utc) - timedelta(hours=2)
    ingest_env.add(
        Ticket(
            parking_id=parking.id,
            vehicle_id=veh.id,
            parking_space_id=space.id,
            status=TicketStatus.ACTIVO,
            entry_at=entry,
        )
    )
    ingest_env.commit()

    # exit_at exacto = entry + 2h para evitar el drift de ms que añadiría
    # 1 fracción extra (15 min). Con 2h exactas: 2 h × 2 € = 4 €;
    # descuento 20 % = 0.80 €; total = 3.20 €.
    fixed_exit = entry + timedelta(hours=2)

    hit = PlateHit(plate="SUB-1", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera, now=fixed_exit)

    assert result.status == IngestStatus.TICKET_CLOSED
    assert result.amount == 4.0
    assert result.discount == 0.8
    assert result.total == 3.2


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
    assert ingest_env.query(Ticket).count() == 1


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
    hit = PlateHit(plate="NEW-1", confidence=0.95, bbox=[250, 250, 270, 270])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.parking_space_id == space2.id