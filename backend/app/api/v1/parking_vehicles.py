"""Vehículos de una sucursal (T-116).

POR QUÉ existe este router
--------------------------
``GET /vehicles`` (la flota global) queda para el administrador: antes
devolvía **todas** las matrículas del sistema a cualquier gestor u
operador, incluidas las de vehículos que sólo operan en otras
sucursales (dato personal, LOPDGDD).

El personal sí necesita un listado de vehículos: el operador ve una
matrícula en la puerta y el gestor tiene que poder filtrar los
movimientos por vehículo. Por eso este router da **los vehículos de una
sucursal**: los que tienen (o han tenido) un ticket en ella.

Es el mismo patrón que el resto de routers por sucursal
(``/parkings/{id}/spaces``, ``/cameras``, ``/tariffs``, ``/alerts``):
``parking_context`` como dependencia del router, de modo que un gestor
de otra sucursal recibe **403** y no un 200 con lista vacía.

Lo usa la vista de movimientos del gestor
(``frontend/src/views/gestor/MovementsView.vue``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import parking_context
from app.models.ticket import Ticket
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleRead

router = APIRouter(
    prefix="/parkings/{parking_id}/vehicles",
    tags=["vehiculos"],
    dependencies=[Depends(parking_context)],
)


@router.get("", response_model=list[VehicleRead])
def list_parking_vehicles(
    parking_id: int,
    db: Session = Depends(get_db),
) -> list[Vehicle]:
    """Vehículos que tienen un ticket (activo o cerrado) en esta sucursal.

    Se deduplican por vehículo: un coche que ha entrado 30 veces aparece
    una sola vez. Sin tickets no hay nada que listar (un vehículo recién
    creado todavía no ha pasado por ninguna cámara).
    """
    vehicle_ids = [
        fila[0]
        for fila in db.query(Ticket.vehicle_id)
        .filter(Ticket.parking_id == parking_id)
        .distinct()
        .all()
    ]
    if not vehicle_ids:
        return []
    return (
        db.query(Vehicle)
        .filter(Vehicle.id.in_(vehicle_ids))
        .order_by(Vehicle.plate)
        .all()
    )
