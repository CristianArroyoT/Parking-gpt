"""Cruce bbox↔geocerca, lookup/create de vehículo y creación de Ticket.

Aislado del worker y del router para poder testearlo sin Celery ni FastAPI.
Abre su propia sesión SQLAlchemy (vía SessionLocal) — no recibe ``db`` por
parámetro — para que cualquier fallo del commit quede contenido y el caller
pueda seguir procesando más hits.

Pipeline (ver `process_plate_hit`):

1. Cargar `CameraGeofence WHERE camera_id = camera.id`.
   Sin filas → ``SKIPPED_NO_GEOFENCE``.
2. Para cada geocerca, IoU contra el ``bbox`` del hit + filtro por
   ``confidence >= geofence.confidence_threshold``. Mejor IoU gana.
   Si ninguna matchea → ``SKIPPED_NO_GEOFENCE``.
3. Lookup Vehicle por ``plate``; INSERT si no existe. Captura
   ``IntegrityError`` por race con otra transacción concurrente.
4. ¿Vehículo ya tiene Ticket activo en este parking? → ``SKIPPED_DUPLICATE_ACTIVE_TICKET``.
5. ¿Plaza del geofence ya tiene Ticket activo? → ``SKIPPED_SPACE_OCCUPIED``.
6. INSERT Ticket activo. Devuelve ``TICKET_CREATED`` con IDs.

Por qué una sola sesión propia y no la del caller: tanto el worker
Celery como el router FastAPI ya gestionan su propia transacción para
persistir ``PlatesDetected``. Si el servicio reusara esa sesión,
un fallo al hacer commit del Ticket revertiría también la fila de
``PlatesDetected``, que es información cruda de OCR que no queremos
perder. Mejor mantener transacciones independientes: la persistencia
del raw siempre commitea, el ticket se crea o se skipea aparte.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Sequence

from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models.enums import TicketStatus
from app.models.geofence import CameraGeofence
from app.models.parking import Camera
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.schemas.plate import PlateHit

log = logging.getLogger(__name__)


class IngestStatus(StrEnum):
    """Resultado del procesamiento de un hit OCR."""

    TICKET_CREATED = "ticket_created"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    SKIPPED_NO_GEOFENCE = "skipped_no_geofence"
    SKIPPED_DUPLICATE_ACTIVE_TICKET = "skipped_duplicate_active_ticket"
    SKIPPED_SPACE_OCCUPIED = "skipped_space_occupied"


@dataclass(frozen=True)
class IngestResult:
    """Resultado del procesamiento de UN hit. Inmutable."""

    plate: str
    camera_id: int
    parking_id: int
    status: IngestStatus
    confidence: float
    ticket_id: int | None = None
    vehicle_id: int | None = None
    parking_space_id: int | None = None
    reason: str | None = None


def process_plate_hit(
    hit: PlateHit,
    camera: Camera,
    *,
    now: datetime | None = None,
) -> IngestResult:
    """Procesa un hit contra la cámara dada y devuelve el resultado.

    ``camera`` debe tener su ``parking_id`` cargado (no se hace lazy load).
    ``now`` se acepta inyectado para tests deterministas; por defecto
    ``datetime.now(UTC)``.

    Nunca propaga excepciones; cualquier fallo inesperado se traduce en
    ``IngestResult`` con status ``skipped_no_geofence`` y motivo
    descriptivo. Esto es coherente con la regla "worker nunca propaga".
    """
    now = now or datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            return _process_in_tx(db, hit, camera, now=now)
    except Exception as exc:  # noqa: BLE001 — defensiva por contrato
        log.exception("ingest: fallo inesperado plate=%s: %s", hit.plate, exc)
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_NO_GEOFENCE,
            confidence=hit.confidence,
            reason=f"error interno: {exc}",
        )


def process_plate_hits(
    hits: Sequence[PlateHit],
    camera: Camera,
) -> list[IngestResult]:
    """Procesa varios hits. Cada uno abre su propia transacción."""
    return [process_plate_hit(h, camera) for h in hits]


# ── Internos ──────────────────────────────────────────────────────────
def _process_in_tx(
    db,
    hit: PlateHit,
    camera: Camera,
    *,
    now: datetime,
) -> IngestResult:
    """Lógica de cruce + creación. La sesión es del servicio (no del caller)."""
    # 1. Geocercas de la cámara
    geofences = (
        db.query(CameraGeofence)
        .filter(CameraGeofence.camera_id == camera.id)
        .all()
    )
    if not geofences:
        log.warning(
            "ingest: cámara %s sin geocercas calibradas (plate=%s)",
            camera.id,
            hit.plate,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_NO_GEOFENCE,
            confidence=hit.confidence,
            reason="Cámara sin geocercas calibradas",
        )

    # 2. Mejor geocerca por IoU + threshold
    matched = _match_geofence(geofences, hit)
    if matched is None:
        log.warning(
            "ingest: bbox fuera de geocercas plate=%s camera=%s bbox=%s",
            hit.plate,
            camera.id,
            hit.bbox,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_NO_GEOFENCE,
            confidence=hit.confidence,
            reason="bbox fuera de las geocercas calibradas",
        )

    # 3. Lookup o create vehicle (con manejo de race condition)
    vehicle = db.query(Vehicle).filter(Vehicle.plate == hit.plate).one_or_none()
    if vehicle is None:
        vehicle = Vehicle(plate=hit.plate)
        db.add(vehicle)
        try:
            db.flush()
        except IntegrityError:
            # Otro proceso creó el mismo vehículo entre nuestro SELECT y
            # nuestro INSERT. Deshacemos el flush y re-fetcheamos.
            db.rollback()
            vehicle = (
                db.query(Vehicle)
                .filter(Vehicle.plate == hit.plate)
                .one()
            )
            log.info(
                "ingest: race en creación de vehicle plate=%s id=%s",
                vehicle.plate,
                vehicle.id,
            )
        else:
            log.info(
                "ingest: vehículo nuevo plate=%s id=%s",
                vehicle.plate,
                vehicle.id,
            )

    # 4. ¿Vehículo ya tiene ticket activo en este parking?
    duplicate_vehicle = (
        db.query(Ticket)
        .filter(
            Ticket.vehicle_id == vehicle.id,
            Ticket.parking_id == camera.parking_id,
            Ticket.status == TicketStatus.ACTIVO,
        )
        .first()
    )
    if duplicate_vehicle is not None:
        log.info(
            "ingest: vehículo %s ya tiene ticket activo %s en parking %s",
            vehicle.plate,
            duplicate_vehicle.id,
            camera.parking_id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_DUPLICATE_ACTIVE_TICKET,
            confidence=hit.confidence,
            ticket_id=duplicate_vehicle.id,
            vehicle_id=vehicle.id,
            parking_space_id=matched.parking_space_id,
            reason="Vehículo ya tiene ticket activo en este parking",
        )

    # 5. ¿Plaza del geofence ya tiene ticket activo?
    occupied_space = (
        db.query(Ticket)
        .filter(
            Ticket.parking_space_id == matched.parking_space_id,
            Ticket.status == TicketStatus.ACTIVO,
        )
        .first()
    )
    if occupied_space is not None:
        log.info(
            "ingest: plaza %s ya tiene ticket activo %s",
            matched.parking_space_id,
            occupied_space.id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_SPACE_OCCUPIED,
            confidence=hit.confidence,
            vehicle_id=vehicle.id,
            parking_space_id=matched.parking_space_id,
            ticket_id=occupied_space.id,
            reason="Plaza ya tiene ticket activo",
        )

    # 6. Crear ticket
    ticket = Ticket(
        parking_id=camera.parking_id,
        vehicle_id=vehicle.id,
        parking_space_id=matched.parking_space_id,
        status=TicketStatus.ACTIVO,
        entry_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    log.info(
        "ingest: ticket creado id=%s plate=%s vehicle_id=%s space_id=%s",
        ticket.id,
        vehicle.plate,
        vehicle.id,
        ticket.parking_space_id,
    )
    return IngestResult(
        plate=hit.plate,
        camera_id=camera.id,
        parking_id=camera.parking_id,
        status=IngestStatus.TICKET_CREATED,
        confidence=hit.confidence,
        ticket_id=ticket.id,
        vehicle_id=vehicle.id,
        parking_space_id=ticket.parking_space_id,
    )


def _match_geofence(
    geofences: Sequence[CameraGeofence],
    hit: PlateHit,
) -> CameraGeofence | None:
    """Geocerca con mayor IoU que supere su threshold de confianza."""
    hx1, hy1, hx2, hy2 = (float(v) for v in hit.bbox)
    best: tuple[float, CameraGeofence] | None = None
    for g in geofences:
        if hit.confidence < g.confidence_threshold:
            continue
        gx2, gy2 = g.x + g.w, g.y + g.h
        iou = _iou((hx1, hy1, hx2, hy2), (g.x, g.y, gx2, gy2))
        if iou <= 0:
            continue
        if best is None or iou > best[0]:
            best = (iou, g)
    return best[1] if best is not None else None


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection-over-Union para dos rectángulos alineados a ejes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


__all__ = [
    "IngestStatus",
    "IngestResult",
    "process_plate_hit",
    "process_plate_hits",
]