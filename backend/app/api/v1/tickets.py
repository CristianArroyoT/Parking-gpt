"""Endpoints de tickets (Fase 1: CRUD básico, sin OCR ni cálculo de tarifa)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query as SAQuery
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import (
    ROLES_STAFF,
    get_current_user,
    parking_context,
    require_role,
)
from app.core.ip import get_real_ip
from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Ticket
from app.models.user import ParkingMembership, User
from app.models.vehicle import Vehicle, VehicleUser
from app.schemas.ticket import TicketClose, TicketCreate, TicketManualCreate, TicketRead
from app.services.manual_tickets import create_manual_ticket as _create_manual_ticket
from app.services.event_bus import EventType, publish as publish_event
from app.services.pdf import render_ticket_pdf, save_ticket_pdf
from app.services.pricing import PricingError, calculate_ticket_total

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _scoped_query(db: Session, user: User, parking_id: Optional[int]) -> SAQuery[Ticket]:
    query = db.query(Ticket)
    if user.role == UserRole.CLIENTE:
        # Un cliente sólo ve los tickets de los vehículos que posee o
        # conduce (relación ``vehicle_users``).
        #
        # POR QUÉ no vale el scope de membresía de sucursal (que es el de
        # gestor y operador): el admin puede añadir membresías a un
        # usuario con cualquier rol, así que un cliente con membresía
        # veía **los tickets de todos los vehículos de esa sucursal**,
        # incluidos los de otros clientes. Eso es una fuga de datos entre
        # clientes (LOPDGDD) y lo detectó la revisión de T-19.
        vehicle_ids = [
            vu.vehicle_id
            for vu in db.query(VehicleUser)
            .filter(VehicleUser.user_id == user.id)
            .all()
        ]
        query = query.filter(Ticket.vehicle_id.in_(vehicle_ids))
    elif user.role != UserRole.ADMIN:
        ids = [
            m.parking_id
            for m in db.query(ParkingMembership)
            .filter(ParkingMembership.user_id == user.id)
            .all()
        ]
        query = query.filter(Ticket.parking_id.in_(ids))
    if parking_id is not None:
        query = query.filter(Ticket.parking_id == parking_id)
    return query


@router.get("", response_model=list[TicketRead])
def list_tickets(
    parking_id: Optional[int] = Query(default=None),
    only_active: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Ticket]:
    query = _scoped_query(db, user, parking_id)
    if only_active:
        query = query.filter(Ticket.status == TicketStatus.ACTIVO)
    return query.order_by(Ticket.entry_at.desc()).limit(200).all()


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
@audited("create_ticket")
def create_ticket(
    payload: TicketCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Ticket:
    """Alta de un ticket.

    T-113 (2026-10-23): el endpoint aceptaba el ``parking_id`` del body
    **sin mirar si el usuario tenia membresia en esa sucursal**. Medido
    contra el sistema en marcha (gestor de la sucursal 11, la 12 no
    tenia ni un miembro)::

        POST /api/v1/tickets  {"parking_id": 12, ...}   -> [201]  ticket 617

    O sea: un gestor escribia en la contabilidad de otra sucursal (y el
    ticket creado ya no lo podia ni ver: ``GET /tickets/617`` -> 404).
    El patron correcto ya estaba dos endpoints mas abajo, en
    ``POST /tickets/manual``: ``parking_context(payload.parking_id, ...)``.

    Ademas, el ``IntegrityError`` del indice unico parcial (un vehiculo no
    puede tener dos tickets activos en la misma sucursal, T-105) no se
    capturaba: la API devolvia un **500**. Ahora es un 409 con el motivo.
    """
    if user.role == UserRole.CLIENTE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los clientes no crean tickets manualmente",
        )
    # T-113: la sucursal del body tiene que ser una sucursal del usuario.
    parking_context(payload.parking_id, current=user, db=db)
    ticket = Ticket(**payload.model_dump(), status=TicketStatus.ACTIVO)
    db.add(ticket)
    try:
        db.commit()
    except IntegrityError:
        # T-105: el indice unico parcial (vehiculo + sucursal, solo
        # 'activo') es la unica cosa que una carrera no puede saltar.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El vehículo ya tiene un ticket activo en esa sucursal",
        ) from None
    db.refresh(ticket)
    return ticket


@router.post(
    "/manual",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_role(
            UserRole.ADMIN.value,
            UserRole.GESTOR.value,
            UserRole.OPERADOR.value,
        ))
    ],
)
def create_manual_ticket_endpoint(
    payload: TicketManualCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ticket:
    """Alta manual ENTRADA/SALIDA del operador.

    RBAC: admin, gestor u operador. El operador debe tener membresía en la
    sucursal (validado con ``parking_context``).
    """
    parking_context(payload.parking_id, current=current_user, db=db)
    # OJO (T-62): con ``request.client.host`` se auditaba la IP del
    # PROXY (nginx), no la del cliente.
    ip = get_real_ip(request) if request.client else None
    return _create_manual_ticket(payload, current_user=current_user, ip=ip)


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Ticket:
    ticket = _scoped_query(db, user, None).filter(Ticket.id == ticket_id).one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return ticket


@router.get("/{ticket_id}/pdf")
def descargar_pdf_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Descarga el PDF del ticket (T-97).

    El PDF se **genera al vuelo**, no se sirve el fichero de ``/tmp``:
    asi la API no tiene que exponer la ruta del servidor (que ademas
    no la servia nadie: el enlace del cliente daba 404) y el PDF
    corresponde siempre a los datos actuales del ticket.

    El scope es el MISMO que ``GET /tickets/{id}``: un cliente solo
    descarga los PDF de sus vehiculos y un gestor los de su sucursal.
    """
    ticket = (
        _scoped_query(db, user, None).filter(Ticket.id == ticket_id).one_or_none()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    vehicle = db.get(Vehicle, ticket.vehicle_id)
    pdf = render_ticket_pdf(ticket, vehicle)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="ticket-{ticket.id}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/{ticket_id}/close", response_model=TicketRead)
@audited("close_ticket", resource_arg="ticket_id")
def close_ticket(
    ticket_id: int,
    payload: TicketClose,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*ROLES_STAFF)),
) -> Ticket:
    """Cierra un ticket (operacion de personal).

    T-120 (2026-10-23): esto era ``get_current_user`` + el scope del
    cliente, asi que un **conductor** podia cerrar su propio ticket
    activo. Medido contra el sistema en marcha::

        [cliente] POST /tickets/620/close            -> [200]  (cerrado, 0,63 EUR)
        [cliente] POST /tickets/621/close  (exit_at = ayer) -> [200]  (22,50 EUR
                    por una estancia de 10 dias)

    O sea: el cliente no solo cerraba su estancia, **fijaba la hora de
    salida** y por tanto **el importe de su propio cobro**. Los tickets
    los cierra la camara de salida (o el personal, a mano); el cliente
    no toca el cobro.

    OJO: ``require_role`` va ANTES que la consulta, asi que un cliente
    recibe 403 sin que la consulta revele si el ticket existe.
    """
    ticket = _scoped_query(db, user, None).filter(Ticket.id == ticket_id).one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    if ticket.status != TicketStatus.ACTIVO:
        raise HTTPException(status_code=409, detail="El ticket no está activo")
    ticket.exit_at = payload.exit_at or datetime.now(timezone.utc)
    try:
        total = calculate_ticket_total(
            db,
            parking_id=ticket.parking_id,
            vehicle_id=ticket.vehicle_id,
            entry_at=ticket.entry_at,
            exit_at=ticket.exit_at,
        )
    except PricingError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # T-121 (2026-10-23): el estado se comprobaba AL LEERLO y luego se
    # commiteaba a ciegas. Si la camara de salida cerraba el ticket
    # entre la lectura y el commit, los dos tenian exito y el ultimo que
    # commite mandaba sobre el importe. Con un UPDATE condicional, la
    # comprobacion y la escritura son la misma sentencia.
    actualizados = (
        db.query(Ticket)
        .filter(Ticket.id == ticket.id, Ticket.status == TicketStatus.ACTIVO)
        .update(
            {
                "exit_at": ticket.exit_at,
                "amount": total.amount,
                "discount": total.discount,
                "total": total.total,
                "status": TicketStatus.CERRADO,
                "payment_method": payload.payment_method,
            },
            synchronize_session=False,
        )
    )
    if not actualizados:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El ticket ya no está activo",
        )
    db.commit()
    db.refresh(ticket)

    # T-127 (2026-10-23): el cierre por camara y el alta manual publican
    # en el bus SSE (para que el mapa del gestor se actualice al
    # instante). El cierre manual no publicaba nada, asi que la app se
    # enteraba hasta el poll de 30 s.
    publish_event(
        ticket.parking_id,
        EventType.TICKET_CLOSED,
        {"ticket_id": ticket.id, "total": ticket.total},
    )

    # Generar PDF de justificante. Si ReportLab fallase (raro en prod),
    # dejamos el ticket cerrado igualmente; sólo logueamos.
    try:
        vehicle = db.get(Vehicle, ticket.vehicle_id)
        ticket.pdf_path = save_ticket_pdf(ticket, vehicle)
        db.commit()
        db.refresh(ticket)
    except Exception:  # pragma: no cover - defensivo
        import logging
        logging.getLogger(__name__).exception("No se pudo generar el PDF del ticket %s", ticket.id)

    return ticket