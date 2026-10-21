"""API del cliente final (T-24 · PWA instalable del cliente).

Qué aporta este router y qué NO
--------------------------------
El panel del cliente necesita tres cosas: sus vehículos, sus tickets y
**la plaza que ocupa ahora mismo**. Las dos primeras ya las sirven otros
routers (y no se duplican aquí):

- ``GET /api/v1/users/me/vehicles`` → vehículos vinculados (T-19).
- ``GET /api/v1/users/me/tickets``  → tickets de esos vehículos (T-19).
- ``GET /api/v1/plans/me``          → su plan y su suscripción (T-18).

Lo que **no** existía era la plaza: ni ``GET /vehicles`` (staff-only)
ni ``GET /tickets`` (que acota por membresía de sucursal) dicen qué
plaza ocupa el coche, y un cliente no puede ni listar los espacios de
una sucursal (``GET /parkings/{id}/spaces`` exige membresía). Por eso
este router devuelve **los datos enriquecidos** que la app necesita y
que no se pueden derivar en el navegador:

- ``GET /api/v1/cliente/plazas`` → plaza ocupada ahora mismo (etiqueta
  de plaza, sucursal, avería, hora de entrada).
- ``GET /api/v1/cliente/tickets`` → sus tickets con matrícula, nombre de
  sucursal, etiqueta de plaza y el flag de "pendiente de pago".

RBAC
----
Lo puede llamar cualquier usuario autenticado; los datos se acotan
siempre por ``user_id`` (o por los vehículos que tiene vinculados), así
que un gestor que lo llame ve su propio panel (vacío), nunca el de los
clientes.

Alcance de este archivo
-----------------------
Los schemas de respuesta se definen **aquí** (no en ``app/schemas/``)
para no tocar ficheros que, en esta ola de trabajo, son de otro
subagente. Si más adelante se quisieran mover, son clases Pydantic
puras: el contrato HTTP no cambia.

Registro
--------
**Este router todavía NO está registrado** en
``app/api/v1/__init__.py`` (fichero de otro subagente). Lo registra la
sesión principal con:

    api_router.include_router(cliente.router)

Mientras tanto, ``tests/test_cliente_api.py`` lo monta a mano sobre la
app de test para poder ejercitarlo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.enums import TicketStatus
from app.models.parking import Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser

router = APIRouter(prefix="/cliente", tags=["cliente"])


# ── Schemas de respuesta ───────────────────────────────────────────────


class ClientePlazaRead(BaseModel):
    """Plaza que ocupa ahora mismo uno de los vehículos del cliente."""

    ticket_id: int
    vehicle_id: int
    plate: str
    parking_id: int
    parking_name: str
    parking_space_id: Optional[int] = None
    lane: Optional[str] = None
    number: Optional[str] = None
    space_label: Optional[str] = None
    entry_at: datetime
    is_broken: bool = False


class ClienteTicketRead(BaseModel):
    """Ticket del cliente con el detalle de si está pendiente de pago."""

    id: int
    vehicle_id: int
    plate: str
    parking_id: int
    parking_name: str
    parking_space_id: Optional[int] = None
    space_label: Optional[str] = None
    status: str
    entry_at: datetime
    exit_at: Optional[datetime] = None
    amount: Optional[float] = None
    discount: Optional[float] = None
    total: Optional[float] = None
    payment_method: Optional[str] = None
    pdf_path: Optional[str] = None
    pending_payment: bool = False
    days_pending: Optional[int] = None


# ── Helpers ────────────────────────────────────────────────────────────


def _vehiculos_del_cliente(db: Session, user_id: int) -> list[Vehicle]:
    """Vehículos vinculados al usuario (propietario o conductor)."""
    return (
        db.query(Vehicle)
        .join(VehicleUser, VehicleUser.vehicle_id == Vehicle.id)
        .filter(VehicleUser.user_id == user_id)
        .order_by(Vehicle.plate)
        .all()
    )


def _etiqueta_plaza(space: Optional[ParkingSpace]) -> Optional[str]:
    """Etiqueta legible de una plaza: ``A-12``.

    En la siembra el ``number`` ya viene como ``"A-01"`` (y el ``lane``
    como ``"A"``); si algún parking usa otro formato, se antepone la
    calzada para que la etiqueta sea siempre inequívoca.
    """
    if space is None:
        return None
    if space.number.startswith(f"{space.lane}-"):
        return space.number
    return f"{space.lane}-{space.number}"


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normaliza a UTC con zona horaria.

    En SQLite los ``DateTime(timezone=True)`` se recuperan *naive*
    (el dialecto no guarda el offset). La convención del repo es que un
    datetime naive está en UTC (ver ``_ensure_aware`` en
    ``app/services/pricing.py``), así que se etiqueta como tal. De este
    modo el JSON que ve la app lleva siempre el offset y el navegador
    no lo interpreta como hora local por error.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _es_pendiente_de_pago(ticket: Ticket) -> bool:
    """Un ticket está pendiente de pago si está cerrado, tiene importe y
    **no** tiene método de pago anotado.

    El método de pago lo escribe el personal al cerrar el ticket
    (``POST /tickets/{id}/close`` con ``payment_method``). Mientras no
    haya método, la deuda sigue viva. La app del cliente **no** cobra:
    sólo informa del importe pendiente (decisión D2 del plan maestro:
    cobro contable, sin pasarela de pago hasta que haya cliente piloto).
    """
    if ticket.status != TicketStatus.CERRADO:
        return False
    if ticket.total is None or ticket.total <= 0:
        return False
    return not (ticket.payment_method or "").strip()


def _dias_pendientes(ticket: Ticket, ahora: datetime) -> Optional[int]:
    """Días transcurridos desde la salida (sólo para tickets pendientes)."""
    if ticket.exit_at is None:
        return None
    salida = _aware(ticket.exit_at)
    assert salida is not None  # para el type checker
    return max(0, (ahora - salida).days)


def _nombres_de_sucursal(db: Session, parking_ids: list[int]) -> dict[int, str]:
    if not parking_ids:
        return {}
    return {
        p.id: p.name
        for p in db.query(Parking).filter(Parking.id.in_(parking_ids)).all()
    }


def _plazas_por_id(db: Session, space_ids: list[int]) -> dict[int, ParkingSpace]:
    if not space_ids:
        return {}
    return {
        s.id: s
        for s in db.query(ParkingSpace).filter(ParkingSpace.id.in_(space_ids)).all()
    }


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/plazas", response_model=list[ClientePlazaRead])
def listar_plazas(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ClientePlazaRead]:
    """Plazas ocupadas **ahora mismo** por los vehículos del cliente.

    Puede devolver más de una: un cliente puede tener varios coches
    dentro a la vez. Si el cliente no tiene ningún vehículo dentro,
    devuelve una lista vacía.
    """
    vehiculos = _vehiculos_del_cliente(db, user.id)
    if not vehiculos:
        return []
    vehicle_ids = [v.id for v in vehiculos]
    plates = {v.id: v.plate for v in vehiculos}

    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.vehicle_id.in_(vehicle_ids),
            Ticket.status == TicketStatus.ACTIVO,
        )
        .order_by(Ticket.entry_at.desc())
        .all()
    )
    if not tickets:
        return []

    spaces = _plazas_por_id(
        db, [t.parking_space_id for t in tickets if t.parking_space_id]
    )
    parkings = _nombres_de_sucursal(db, [t.parking_id for t in tickets])

    plazas: list[ClientePlazaRead] = []
    for t in tickets:
        space = spaces.get(t.parking_space_id) if t.parking_space_id else None
        plazas.append(
            ClientePlazaRead(
                ticket_id=t.id,
                vehicle_id=t.vehicle_id,
                plate=plates.get(t.vehicle_id, ""),
                parking_id=t.parking_id,
                parking_name=parkings.get(t.parking_id, f"Sucursal {t.parking_id}"),
                parking_space_id=t.parking_space_id,
                lane=space.lane if space else None,
                number=space.number if space else None,
                space_label=_etiqueta_plaza(space),
                entry_at=_aware(t.entry_at),
                is_broken=bool(space.is_broken) if space else False,
            )
        )
    return plazas


@router.get("/tickets", response_model=list[ClienteTicketRead])
def listar_tickets(
    solo_pendientes: bool = Query(
        default=False,
        description="Si es true, devuelve sólo los tickets pendientes de pago.",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ClienteTicketRead]:
    """Tickets de **mis** vehículos, con los datos que la app necesita.

    Mismo scope que ``GET /users/me/tickets`` (T-19), pero enriquecido
    con la matrícula, el nombre de la sucursal, la etiqueta de la plaza
    y el flag de pago pendiente: nada de eso se puede obtener en el
    navegador, porque el cliente no tiene acceso a los espacios ni a las
    sucursales.
    """
    vehiculos = _vehiculos_del_cliente(db, user.id)
    if not vehiculos:
        return []
    plates = {v.id: v.plate for v in vehiculos}

    tickets = (
        db.query(Ticket)
        .filter(Ticket.vehicle_id.in_([v.id for v in vehiculos]))
        .order_by(Ticket.entry_at.desc())
        .limit(200)
        .all()
    )

    spaces = _plazas_por_id(
        db, [t.parking_space_id for t in tickets if t.parking_space_id]
    )
    parkings = _nombres_de_sucursal(db, [t.parking_id for t in tickets])

    ahora = datetime.now(timezone.utc)
    salida: list[ClienteTicketRead] = []
    for t in tickets:
        pendiente = _es_pendiente_de_pago(t)
        if solo_pendientes and not pendiente:
            continue
        space = spaces.get(t.parking_space_id) if t.parking_space_id else None
        salida.append(
            ClienteTicketRead(
                id=t.id,
                vehicle_id=t.vehicle_id,
                plate=plates.get(t.vehicle_id, ""),
                parking_id=t.parking_id,
                parking_name=parkings.get(t.parking_id, f"Sucursal {t.parking_id}"),
                parking_space_id=t.parking_space_id,
                space_label=_etiqueta_plaza(space),
                status=t.status.value if hasattr(t.status, "value") else str(t.status),
                entry_at=_aware(t.entry_at),
                exit_at=_aware(t.exit_at),
                amount=t.amount,
                discount=t.discount,
                total=t.total,
                payment_method=t.payment_method,
                pdf_path=t.pdf_path,
                pending_payment=pendiente,
                days_pending=_dias_pendientes(t, ahora),
            )
        )
    return salida
