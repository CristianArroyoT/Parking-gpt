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
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza el registro de todas las tablas en Base.metadata
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
def ingest_env(monkeypatch, motor_de_test):
    """BD del dialecto de la suite, y parchea
    ``ingest_service.SessionLocal`` para que el servicio escriba aquí.

    Usa ``motor_de_test`` (conftest) para que el fichero se ejecute
    también contra PostgreSQL cuando la suite corre contra PostgreSQL:
    antes tenía su propio SQLite y el dialecto real quedaba sin cubrir.

    Devuelve una sesión para que los tests creen fixtures y lean
    resultados. Todos los cambios se ven a través de la misma sesión
    porque el motor comparte el mismo almacenamiento.
    """
    engine = motor_de_test
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


def _setup_with_geofence(db, *, threshold: float = 0.85, direction: str = "entry"):
    """Crea parking + plaza + cámara + geocerca (0..200, 0..200).

    ``direction`` puede ser ``"entry"`` (default) o ``"exit"``.
    """
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
            direction=direction,
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

    existing = Vehicle(plate="1111AAA")
    ingest_env.add(existing)
    ingest_env.commit()
    existing_id = existing.id

    hit = PlateHit(plate="1111AAA", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.vehicle_id == existing_id

    ingest_env.expire_all()
    assert ingest_env.query(Vehicle).count() == 1
    assert ingest_env.query(Vehicle).filter_by(plate="1111AAA").one().id == existing_id


def test_exit_closes_active_ticket(ingest_env) -> None:
    """Cámara de salida (direction=exit) cierra el ticket activo del vehículo."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="exit")
    ingest_env.add(_add_tariff(ingest_env, parking.id))
    ingest_env.commit()

    veh = Vehicle(plate="2222BBB")
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

    # exit_at exacto a 1h30 para evitar drift de fracciones.
    fixed_exit = entry + timedelta(hours=1, minutes=30)

    hit = PlateHit(plate="2222BBB", confidence=0.95, bbox=[10, 10, 50, 50])
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


def test_exit_fails_without_active_tariff(ingest_env) -> None:
    """Cámara de salida sin tarifa vigente → SKIPPED_CLOSE_FAILED."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="exit")
    # SIN tarifa — calculate_ticket_total lanzará PricingError.
    veh = Vehicle(plate="3333CCC")
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

    hit = PlateHit(plate="3333CCC", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.SKIPPED_CLOSE_FAILED
    assert result.ticket_id is not None
    assert result.reason and "tarifa" in result.reason.lower()

    ingest_env.expire_all()
    ticket = ingest_env.get(Ticket, result.ticket_id)
    assert ticket.status == TicketStatus.ACTIVO


def test_exit_with_subscription_discount(ingest_env) -> None:
    """Cámara de salida con plan activo aplica descuento."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="exit")
    ingest_env.add(_add_tariff(ingest_env, parking.id))

    user = User(
        email="subs@test.es", full_name="Subs", role=UserRole.CLIENTE,
        hashed_password="x",
    )
    plan = Plan(
        code="EMPRESA", name="Empresa", monthly_price=200.0,
        discount_percent=20.0, included_vehicles=10, is_active=True,
    )
    ingest_env.add_all([user, plan])
    ingest_env.flush()
    sub = Subscription(
        user_id=user.id, plan_id=plan.id,
        starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )
    veh = Vehicle(plate="4444DDD")
    ingest_env.add_all([sub, veh])
    ingest_env.flush()
    ingest_env.add(VehicleUser(vehicle_id=veh.id, user_id=user.id, role=VehicleRole.PROPIETARIO))
    entry = datetime.now(timezone.utc) - timedelta(hours=2)
    ingest_env.add(Ticket(
        parking_id=parking.id, vehicle_id=veh.id, parking_space_id=space.id,
        status=TicketStatus.ACTIVO, entry_at=entry,
    ))
    ingest_env.commit()

    fixed_exit = entry + timedelta(hours=2)
    hit = PlateHit(plate="4444DDD", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera, now=fixed_exit)

    assert result.status == IngestStatus.TICKET_CLOSED
    assert result.amount == 4.0
    assert result.discount == 0.8
    assert result.total == 3.2


# ── Tests nuevos del sprint dirección cámara ─────────────────────
def test_exit_without_active_ticket_returns_skip(ingest_env) -> None:
    """Cámara de salida sin ticket activo del vehículo → SKIPPED_NO_ACTIVE_TICKET."""
    parking, _space, camera = _setup_with_geofence(ingest_env, direction="exit")
    hit = PlateHit(plate="5555EEE", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)
    assert result.status == IngestStatus.SKIPPED_NO_ACTIVE_TICKET
    assert "ticket activo" in (result.reason or "").lower()


def test_entry_rejects_vehicle_already_inside(ingest_env) -> None:
    """Cámara de entrada: vehículo ya dentro → SKIPPED_ALREADY_INSIDE."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="entry")
    veh = Vehicle(plate="6666FFF")
    ingest_env.add(veh)
    ingest_env.flush()
    ingest_env.add(Ticket(
        parking_id=parking.id, vehicle_id=veh.id, parking_space_id=space.id,
        status=TicketStatus.ACTIVO,
        entry_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    ))
    ingest_env.commit()

    hit = PlateHit(plate="6666FFF", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)
    assert result.status == IngestStatus.SKIPPED_ALREADY_INSIDE


def test_exit_with_space_occupied_by_other(ingest_env) -> None:
    """Cámara de salida, OTRO vehículo ocupa la plaza → SKIPPED_SPACE_OCCUPIED."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="exit")
    other = Vehicle(plate="7777GGG")
    ingest_env.add(other)
    ingest_env.flush()
    ingest_env.add(Ticket(
        parking_id=parking.id, vehicle_id=other.id, parking_space_id=space.id,
        status=TicketStatus.ACTIVO, entry_at=datetime.now(timezone.utc),
    ))
    ingest_env.commit()

    hit = PlateHit(plate="8888HHH", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)
    # La cámara es de salida pero el vehículo no tiene ticket activo,
    # por lo que el flujo correcto es SKIPPED_NO_ACTIVE_TICKET (no
    # SPACE_OCCUPIED, que es para flujo de ENTRY).
    assert result.status == IngestStatus.SKIPPED_NO_ACTIVE_TICKET


def test_entry_with_space_broken_returns_skip(ingest_env) -> None:
    """Cámara de entrada con plaza averiada → SKIPPED_SPACE_BROKEN."""
    parking, space, camera = _setup_with_geofence(ingest_env, direction="entry")
    space.is_broken = True
    ingest_env.commit()

    hit = PlateHit(plate="8888HHH", confidence=0.95, bbox=[10, 10, 50, 50])
    result = process_plate_hit(hit, camera)
    assert result.status == IngestStatus.SKIPPED_SPACE_BROKEN


def test_mixed_cameras_independent(ingest_env) -> None:
    """Dos cámaras separadas (entry+exit) del mismo parking: el comportamiento
    ya no depende del historial del vehículo. Cada cámara decide."""
    parking, _space_a, cam_entry = _setup_with_geofence(ingest_env, direction="entry")
    space_b = ParkingSpace(parking_id=parking.id, lane="B", number="B-01")
    ingest_env.add(space_b)
    ingest_env.flush()
    cam_exit = Camera(
        parking_id=parking.id, code="CAM-OUT", name="Out",
        rtsp_url="rtsp://demo.invalid/x",
    )
    ingest_env.add(cam_exit)
    ingest_env.flush()
    ingest_env.add(CameraGeofence(
        camera_id=cam_exit.id, parking_space_id=space_b.id,
        x=0, y=0, w=200, h=200, confidence_threshold=0.85,
        direction="exit",
    ))
    ingest_env.add(_add_tariff(ingest_env, parking.id))
    ingest_env.commit()

    # Hit en entry → TICKET_CREATED (no importa historial).
    hit = PlateHit(plate="9999III", confidence=0.95, bbox=[10, 10, 50, 50])
    r1 = process_plate_hit(hit, cam_entry)
    assert r1.status == IngestStatus.TICKET_CREATED
    assert r1.ticket_id is not None

    # Misma matrícula en exit → TICKET_CLOSED.
    r2 = process_plate_hit(hit, cam_exit)
    assert r2.status == IngestStatus.TICKET_CLOSED
    assert r2.ticket_id == r1.ticket_id


def test_skips_when_space_already_occupied(ingest_env) -> None:
    """Otra persona ocupa la plaza → SKIPPED_SPACE_OCCUPIED."""
    parking, space, camera = _setup_with_geofence(ingest_env)

    other = Vehicle(plate="7777GGG")
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

    hit = PlateHit(plate="8888HHH", confidence=0.95, bbox=[10, 10, 50, 50])
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
    hit = PlateHit(plate="8888HHH", confidence=0.95, bbox=[250, 250, 270, 270])
    result = process_plate_hit(hit, camera)

    assert result.status == IngestStatus.TICKET_CREATED
    assert result.parking_space_id == space2.id