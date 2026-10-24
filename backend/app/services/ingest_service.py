"""Cruce bbox↔geocerca, ENTRADA/SALIDA de tickets.

Aislado del worker y del router para poder testearlo sin Celery ni FastAPI.
Abre su propia sesión SQLAlchemy (vía SessionLocal) — no recibe ``db`` por
parámetro — para que cualquier fallo del commit quede contenido y el caller
pueda seguir procesando más hits.

Pipeline (ver `process_plate_hit`):

1. Cargar ``CameraGeofence WHERE camera_id = camera.id``.
   Sin filas → ``SKIPPED_NO_GEOFENCE``.
2. Para cada geocerca, IoU contra el ``bbox`` del hit + filtro por
   ``confidence >= geofence.confidence_threshold``. Mejor IoU gana.
   Si ninguna matchea → ``SKIPPED_NO_GEOFENCE``.
3. Lookup Vehicle por ``plate``; INSERT si no existe. Captura
   ``IntegrityError`` por race con otra transacción concurrente.
4. ¿Vehículo ya tiene ticket activo en este parking? → SALIDA:
   cerrar el ticket, calcular tarifa, generar PDF, devolver
   ``TICKET_CLOSED``. Si el cálculo de tarifa falla → ``SKIPPED_CLOSE_FAILED``.
5. ¿Plaza del geofence ya tiene ticket activo de OTRO vehículo?
   → ``SKIPPED_SPACE_OCCUPIED``.
6. INSERT Ticket activo. Devuelve ``TICKET_CREATED`` con IDs.

Por qué una sola sesión propia y no la del caller: tanto el worker
Celery como el router FastAPI ya gestionan su propia transacción para
persistir ``PlatesDetected``. Si el servicio reusara esa sesión,
un fallo al hacer commit del Ticket revertiría también la fila de
``PlatesDetected``, que es información cruda de OCR que no queremos
perder. Mejor mantener transacciones independientes: la persistencia
del raw siempre commitea, el ticket se crea o se cierra aparte.

Modelo entrada/salida (MVP): el mismo OCR dispara los dos. Si la
matrícula no estaba dentro → ENTRADA. Si ya estaba dentro (ticket
activo) → SALIDA. Esta convención cubre el caso de una sola cámara;
con dos (entrada y salida separadas) haría falta un flag ``direction``
en CameraGeofence o Camera. Por ahora se asume la regla más simple.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Sequence
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models.enums import GeofenceDirection, TicketStatus
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.schemas.plate import PlateHit
from app.services.pdf import save_ticket_pdf
from app.services.plates import normalizar_matricula, parece_matricula
from app.services.pricing import PricingError, calculate_ticket_total
from app.services.ticket_closing import TicketAlreadyClosedError, cerrar_ticket
from app.services.event_bus import EventType, publish as publish_event

log = logging.getLogger(__name__)


class IngestStatus(StrEnum):
    """Resultado del procesamiento de un hit OCR."""

    TICKET_CREATED = "ticket_created"
    TICKET_CLOSED = "ticket_closed"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    SKIPPED_NO_GEOFENCE = "skipped_no_geofence"
    SKIPPED_CLOSE_FAILED = "skipped_close_failed"
    SKIPPED_SPACE_OCCUPIED = "skipped_space_occupied"
    SKIPPED_SPACE_BROKEN = "skipped_space_broken"
    #: T-163 (2026-10-24): la plaza esta **desactivada** (obra, reservado,
    #: fuera de servicio). Antes solo se comprobaba ``is_broken`` (la
    #: averiada), asi que una plaza desactivada seguia admitiendo
    #: tickets: justo lo que el operador queria evitar.
    SKIPPED_SPACE_INACTIVE = "skipped_space_inactive"
    #: T-163 (2026-10-24): la sucursal esta **desactivada**. Antes
    #: ``Parking.is_active`` no lo leia nadie: una sucursal cerrada
    #: seguia recibiendo pushes, creando tickets y **cobrando**.
    SKIPPED_PARKING_INACTIVE = "skipped_parking_inactive"
    SKIPPED_ALREADY_INSIDE = "skipped_already_inside"
    #: El OCR leyó un texto que no es una matrícula (2026-10-22): el
    #: timestamp quemado de la cámara, el rótulo de la marca... No se
    #: crea ni vehículo ni ticket.
    SKIPPED_NOT_A_PLATE = "skipped_not_a_plate"
    SKIPPED_NO_ACTIVE_TICKET = "skipped_no_active_ticket"
    #: T-123 (2026-10-23): fallo inesperado. Antes todo error caia en
    #: ``skipped_no_geofence`` ("no hay geocerca"), que es una
    #: explicacion falsa: el motivo real (una plaza ocupada, un error de
    #: la base de datos) se perdia.
    SKIPPED_ERROR = "skipped_error"


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
    amount: float | None = None
    discount: float | None = None
    total: float | None = None
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
    # 0. ¿Es una matrícula o es otro texto? (2026-10-22)
    #
    # El OCR devuelve TEXTO, no matrículas: también lee el timestamp
    # quemado de la cámara o el rótulo de la marca. Con el vídeo de QA
    # del repo, devolvió "t=105.0sframe=2625" como si fuera una
    # matrícula. Si pasara, crearía un vehículo fantasma (la columna
    # ``vehicles.plate`` es UNIQUE) y, si la geocerca estuviera pintada
    # encima, un ticket.
    #
    # Se comprueba ANTES de tocar la base: aquí no se crea nada.
    if not parece_matricula(hit.plate):
        log.warning(
            "ingest: el OCR no leyó una matrícula (se ignora): %r", hit.plate
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_NOT_A_PLATE,
            confidence=hit.confidence,
            reason=(
                f"el OCR leyó '{hit.plate}', que no tiene forma de matrícula "
                "(normalmente es el timestamp o el rótulo quemado en la imagen)"
            ),
        )
    try:
        with SessionLocal() as db:
            return _process_in_tx(db, hit, camera, now=now)
    except Exception as exc:  # noqa: BLE001 — defensiva por contrato
        log.exception("ingest: fallo inesperado plate=%s: %s", hit.plate, exc)
        # T-123 (2026-10-23): esto ya NO es "no hay geocerca". El
        # catch-all traducia cualquier error a ese estado, de modo que
        # un fallo de la base de datos o una plaza ocupada se
        # anunciaban con una explicacion falsa.
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_ERROR,
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
    db: Session,
    hit: PlateHit,
    camera: Camera,
    *,
    now: datetime,
) -> IngestResult:
    """Lógica de cruce + creación/cierre. La sesión es del servicio (no del caller)."""
    # 0. T-163 (2026-10-24): la sucursal tiene que estar ACTIVA. Antes
    # ``Parking.is_active`` no lo leia nadie, asi que una sucursal
    # desactivada seguia recibiendo pushes: le creaba ticket con su
    # tarifa (o sea, cobra) y ocupaba plazas.
    parking = db.get(Parking, camera.parking_id)
    if parking is not None and not parking.is_active:
        log.warning(
            "ingest: sucursal %s desactivada, se omite (plate=%s camera=%s)",
            camera.parking_id,
            hit.plate,
            camera.id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_PARKING_INACTIVE,
            confidence=hit.confidence,
            reason="Sucursal desactivada; no se admiten entradas",
        )

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
    matched, skip_reason = _match_geofence(geofences, hit)
    if matched is None:
        if skip_reason == "low_confidence":
            log.warning(
                "ingest: confidence %.2f por debajo de thresholds plate=%s camera=%s",
                hit.confidence,
                hit.plate,
                camera.id,
            )
            return IngestResult(
                plate=hit.plate,
                camera_id=camera.id,
                parking_id=camera.parking_id,
                status=IngestStatus.SKIPPED_LOW_CONFIDENCE,
                confidence=hit.confidence,
                reason=(
                    f"confidence {hit.confidence:.2f} por debajo de los "
                    f"thresholds de las geocercas calibradas"
                ),
            )
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
    #
    # T-122 (2026-10-23): la matricula se NORMALIZA antes de buscar y
    # de crear. Antes se usaba el texto crudo del OCR, de modo que la
    # entrada "1234 abc" y la salida "1234ABC" creaban dos vehiculos
    # distintos: la salida no encontraba el ticket activo (y no se
    # cobraba) y el ticket de la entrada se quedaba activo para siempre.
    # El filtro de "esto es una matricula" (``parece_matricula``) ya
    # normalizaba; lo que faltaba era normalizar la identidad.
    matricula = normalizar_matricula(hit.plate)
    vehicle = db.query(Vehicle).filter(Vehicle.plate == matricula).one_or_none()
    if vehicle is None:
        vehicle = Vehicle(plate=matricula)
        db.add(vehicle)
        try:
            db.flush()
        except IntegrityError:
            # Otro proceso creó el mismo vehículo entre nuestro SELECT y
            # nuestro INSERT. Deshacemos el flush y re-fetcheamos.
            db.rollback()
            vehicle = (
                db.query(Vehicle)
                .filter(Vehicle.plate == matricula)
                .one_or_none()
            )
            if vehicle is None:
                # T-128 (2026-10-23): el error **no** era de la
                # matrícula duplicada (puede ser el indice de la plaza al
                # insertar el ticket, o una FK). El rollback se ha
                # carriedo tambien el vehiculo que acababamos de crear,
                # asi que no hay nada que re-fetchear: se propaga el
                # error original. Antes, un ``.one()`` lanzaba
                # ``NoResultFound`` y la causa quedaba enterrada.
                raise
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

    # 4. Decisión ENTRADA / SALIDA basada en `direction` de la geocerca
    # matched. Elimina la regla "primer hit abre, segundo cierra" del MVP
    # de una sola cámara: cada cámara sabe si procesa entrada o salida.
    direction = getattr(matched, "direction", GeofenceDirection.ENTRY)
    if hasattr(direction, "value"):
        direction_value = direction.value
    else:
        direction_value = str(direction)
    is_exit = direction_value == GeofenceDirection.EXIT.value

    if is_exit:
        # ── Cámara de SALIDA ─────────────────────────────────────
        active_ticket = (
            db.query(Ticket)
            .filter(
                Ticket.vehicle_id == vehicle.id,
                Ticket.parking_id == camera.parking_id,
                Ticket.status == TicketStatus.ACTIVO,
            )
            .first()
        )
        if active_ticket is None:
            log.info(
                "ingest: EXIT sin ticket activo plate=%s camera=%s",
                hit.plate,
                camera.id,
            )
            return IngestResult(
                plate=hit.plate,
                camera_id=camera.id,
                parking_id=camera.parking_id,
                status=IngestStatus.SKIPPED_NO_ACTIVE_TICKET,
                confidence=hit.confidence,
                vehicle_id=vehicle.id,
                parking_space_id=matched.parking_space_id,
                reason="Cámara de salida: vehículo sin ticket activo en este parking",
            )
        try:
            closed = _close_ticket_for_exit(db, active_ticket, exit_at=now)
        except TicketAlreadyClosedError:
            # T-121: otro cierre se ha adelantado (p.ej. el manual de un
            # operador). El ticket ya esta cerrado y con su importe: no
            # se vuelve a cobrar.
            log.info(
                "ingest: SALIDA con el ticket ya cerrado plate=%s ticket=%s",
                hit.plate,
                active_ticket.id,
            )
            return IngestResult(
                plate=hit.plate,
                camera_id=camera.id,
                parking_id=camera.parking_id,
                status=IngestStatus.SKIPPED_ALREADY_INSIDE,
                confidence=hit.confidence,
                ticket_id=active_ticket.id,
                vehicle_id=vehicle.id,
                parking_space_id=matched.parking_space_id,
                reason="El ticket ya estaba cerrado (lo cerró otro cierre antes)",
            )
        except PricingError as exc:
            log.warning(
                "ingest: SALIDA fallida plate=%s ticket=%s motivo=%s",
                hit.plate,
                active_ticket.id,
                exc,
            )
            return IngestResult(
                plate=hit.plate,
                camera_id=camera.id,
                parking_id=camera.parking_id,
                status=IngestStatus.SKIPPED_CLOSE_FAILED,
                confidence=hit.confidence,
                ticket_id=active_ticket.id,
                vehicle_id=vehicle.id,
                parking_space_id=matched.parking_space_id,
                reason=str(exc),
            )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.TICKET_CLOSED,
            confidence=hit.confidence,
            ticket_id=closed.id,
            vehicle_id=vehicle.id,
            parking_space_id=closed.parking_space_id,
            amount=closed.amount,
            discount=closed.discount,
            total=closed.total,
        )

    # ── Cámara de ENTRADA ─────────────────────────────────────────
    # 4a. ¿Vehículo ya tiene ticket activo en este parking?
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
            "ingest: ENTRY vehículo ya dentro plate=%s camera=%s",
            hit.plate,
            camera.id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_ALREADY_INSIDE,
            confidence=hit.confidence,
            ticket_id=duplicate_vehicle.id,
            vehicle_id=vehicle.id,
            parking_space_id=matched.parking_space_id,
            reason="Vehículo ya tiene ticket activo en este parking",
        )

    # 5. ¿Plaza del geofence ya tiene ticket activo de OTRO vehículo?
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

    # 5b. ¿Plaza del geofence está marcada como averiada o desactivada?
    # T-163 (2026-10-24): antes solo se miraba ``is_broken``; una plaza
    # **desactivada** (obra, reservado, fuera de servicio) seguia
    # admitiendo tickets.
    space = db.get(ParkingSpace, matched.parking_space_id)
    if space is not None and not space.is_active:
        log.info(
            "ingest: plaza %s desactivada, se omite creación de ticket",
            matched.parking_space_id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_SPACE_INACTIVE,
            confidence=hit.confidence,
            parking_space_id=matched.parking_space_id,
            reason="Plaza desactivada; no se admiten entradas",
        )
    if space is not None and space.is_broken:
        log.info(
            "ingest: plaza %s averiada, se omite creación de ticket",
            matched.parking_space_id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_SPACE_BROKEN,
            confidence=hit.confidence,
            vehicle_id=vehicle.id,
            parking_space_id=matched.parking_space_id,
            reason="Plaza averiada; rehabilítala antes de asignar tickets",
        )

    # 6. Crear ticket (ENTRADA)
    ticket = Ticket(
        parking_id=camera.parking_id,
        vehicle_id=vehicle.id,
        parking_space_id=matched.parking_space_id,
        status=TicketStatus.ACTIVO,
        entry_at=now,
    )
    db.add(ticket)
    try:
        db.commit()
    except IntegrityError:
        # T-105: otra peticion creo el ticket mientras esta comprobaba
        # (dos pushes de la misma matricula a la vez). La base de datos
        # lo prohibe (indice unico parcial) y aqui se devuelve el
        # ticket que ya habia, en vez de crear un segundo (y cobrar dos
        # veces).
        db.rollback()
        existente = (
            db.query(Ticket)
            .filter(
                Ticket.vehicle_id == vehicle.id,
                Ticket.parking_id == camera.parking_id,
                Ticket.status == TicketStatus.ACTIVO,
            )
            .first()
        )
        if existente is None:
            # No es el indice del vehiculo. Puede ser el de la PLAZA
            # (otro vehiculo la ocupa): eso no es un error interno, es
            # la plaza ocupada (T-123).
            ocupada = (
                db.query(Ticket)
                .filter(
                    Ticket.parking_space_id == matched.parking_space_id,
                    Ticket.status == TicketStatus.ACTIVO,
                )
                .first()
            )
            if ocupada is not None:
                log.info(
                    "ingest: ENTRY con la plaza ocupada plate=%s space=%s ticket=%s",
                    hit.plate,
                    matched.parking_space_id,
                    ocupada.id,
                )
                return IngestResult(
                    plate=hit.plate,
                    camera_id=camera.id,
                    parking_id=camera.parking_id,
                    status=IngestStatus.SKIPPED_SPACE_OCCUPIED,
                    confidence=hit.confidence,
                    vehicle_id=vehicle.id,
                    parking_space_id=matched.parking_space_id,
                    reason="La plaza ya la ocupa otro vehículo",
                )
            # Es otro error: el original se propaga.
            raise
        log.info(
            "ingest: ENTRY duplicado en carrera plate=%s camera=%s ticket_id=%s",
            hit.plate,
            camera.id,
            existente.id,
        )
        return IngestResult(
            plate=hit.plate,
            camera_id=camera.id,
            parking_id=camera.parking_id,
            status=IngestStatus.SKIPPED_ALREADY_INSIDE,
            confidence=hit.confidence,
            ticket_id=existente.id,
            vehicle_id=vehicle.id,
            parking_space_id=existente.parking_space_id,
            reason="Vehículo ya tiene ticket activo en este parking",
        )
    db.refresh(ticket)
    log.info(
        "ingest: ENTRADA ticket creado id=%s plate=%s vehicle_id=%s space_id=%s",
        ticket.id,
        vehicle.plate,
        vehicle.id,
        ticket.parking_space_id,
    )
    # Sprint O2 (2026-07-06): notificar al bus SSE para refresco live
    # de MapView. Fire-and-forget: un fallo de Redis no afecta la tx.
    publish_event(
        camera.parking_id,
        EventType.TICKET_CREATED,
        {
            "ticket_id": ticket.id,
            "plate": vehicle.plate,
            "parking_space_id": ticket.parking_space_id,
        },
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


def _close_ticket_for_exit(
    db: Session, ticket: Ticket, *, exit_at: datetime
) -> Ticket:
    """Cierra un ticket activo: calcula tarifa, marca CERRADO, genera PDF.

    El commit del cierre + cálculo de tarifa es atómico. La generación de
    PDF va en un commit aparte: si falla, el ticket ya queda cerrado y
    el operador puede regenerar el PDF manualmente.

    Lanza ``PricingError`` si no hay tarifa vigente (el caller decide
    qué hacer — típicamente devolver ``SKIPPED_CLOSE_FAILED``).
    """
    total = calculate_ticket_total(
        db,
        parking_id=ticket.parking_id,
        vehicle_id=ticket.vehicle_id,
        entry_at=ticket.entry_at,
        exit_at=exit_at,
    )
    # T-121/T-130: el cierre usa el helper comun
    # (``ticket_closing.cerrar_ticket``), que es **condicional**: la
    # comprobacion (el ticket sigue ACTIVO) y la escritura son la misma
    # sentencia. Antes se comprobaba al leer y se commiteaba a ciegas,
    # asi que dos cierres a la vez podian tener exito los dos.
    cerrar_ticket(
        db,
        ticket,
        exit_at=exit_at,
        amount=total.amount,
        discount=total.discount,
        total=total.total,
    )
    # Sprint O2 (2026-07-06): notificar al bus SSE para refresco live
    # de MapView (plaza vuelve a libre).
    publish_event(
        ticket.parking_id,
        EventType.TICKET_CLOSED,
        {"ticket_id": ticket.id, "total": ticket.total},
    )

    # PDF en commit aparte; un fallo aquí no rompe el cierre.
    try:
        vehicle = db.get(Vehicle, ticket.vehicle_id)
        ticket.pdf_path = save_ticket_pdf(ticket, vehicle)
        db.commit()
        db.refresh(ticket)
    except Exception as exc:  # noqa: BLE001 — defensiva
        log.warning(
            "ingest: PDF no generado para ticket %s: %s",
            ticket.id,
            exc,
        )

    # Email al usuario asociado al vehículo: Fase 3. Por ahora sólo log.
    log.info(
        "ingest: SALIDA ticket cerrado id=%s plate=%s amount=%.2f discount=%.2f total=%.2f",
        ticket.id,
        ticket.vehicle.plate if ticket.vehicle else "?",
        ticket.amount or 0.0,
        ticket.discount or 0.0,
        ticket.total or 0.0,
    )

    return ticket


def _match_geofence(
    geofences: Sequence[CameraGeofence],
    hit: PlateHit,
) -> tuple[CameraGeofence | None, str | None]:
    """Devuelve ``(geofence_ganadora, None)`` o ``(None, razón_de_skip)``.

    Razones de skip:
      - ``"low_confidence"``: ninguna geocerca pasó el filtro de
        ``confidence_threshold``. El operador tiene que recalibrar
        bajando el threshold o mejorando el OCR.
      - ``"no_intersection"``: alguna geocerca pasó el threshold pero
        el ``bbox`` del hit no solapó con su rectángulo. El operador
        tiene que pintar más geocercas o reubicar el hit.
    """
    hx1, hy1, hx2, hy2 = (float(v) for v in hit.bbox)
    best: tuple[float, CameraGeofence] | None = None
    any_passed_threshold = False
    for g in geofences:
        if hit.confidence < g.confidence_threshold:
            continue
        any_passed_threshold = True
        gx2, gy2 = g.x + g.w, g.y + g.h
        iou = _iou((hx1, hy1, hx2, hy2), (g.x, g.y, gx2, gy2))
        if iou <= 0:
            continue
        if best is None or iou > best[0]:
            best = (iou, g)
    if best is not None:
        return best[1], None
    if not any_passed_threshold:
        return None, "low_confidence"
    return None, "no_intersection"


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