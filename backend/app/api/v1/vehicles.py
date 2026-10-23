"""CRUD de vehículos y asociación con usuarios."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.db import get_db
from app.core.deps import ROLES_STAFF, require_role
from app.models.enums import UserRole, VehicleRole
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleUser
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleRead,
    VehicleUpdate,
    VehicleUserCreate,
    VehicleUserRead,
)
from app.services.endpoint_rate_limit import enforce_endpoint_rate_limit

router = APIRouter(prefix="/vehicles", tags=["vehículos"])


def _escapar_like(texto: str) -> str:
    """Escapa los comodines de LIKE para que el usuario no use de comodín.

    POR QUÉ (T-93, 2026-10-23): el filtro era
    ``Vehicle.plate.ilike(f"%{plate}%")``, con el texto del usuario metido
    en el patrón. Eso convierte los comodines de LIKE en comodines de
    verdad: ``?plate=%`` devolvía **todos** los vehículos de la flota y
    ``?plate=______`` hacía wildcard sobre cualquier matrícula de 6
    caracteres. Con un rol de staff, la "búsqueda" era un comodín para
    enumerar las matrículas entera (y para escanear la tabla).

    El valor sigue yendo **ligado** como parámetro (no es inyección SQL:
    SQLAlchemy lo escapa); lo que se escapa aquí son los comodines del
    propio LIKE, para que el usuario busque el texto que escribe.
    """
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

#: T-116: los roles de personal tienen UNA sola definicion
#: (``app.core.deps.ROLES_STAFF``). Antes esta tupla estaba duplicada
#: aqui y se podia desincronizar.
_STAFF = ROLES_STAFF


def _enforce_endpoint_rate_limit(
    request: Request, db: Session, *, scope: str, actor_id: int,
) -> None:

    """Delega en la implementación única (T-69).

    Antes este helper estaba copiado en cinco routers: arreglar uno
    no arreglaba los otros cuatro.
    """
    enforce_endpoint_rate_limit(
        request, db, scope=scope, actor_id=actor_id,
    )


@router.get("", response_model=list[VehicleRead])
def list_vehicles(
    # T-93: el mismo limite que el modelo (16 caracteres): un patron
    # enorme no es una busqueda de matriculas. Los comodines de LIKE
    # van escapados (_escapar_like): `?plate=%` busca el signo literal,
    # no comodin (ver test_vehicles_busqueda.py).
    #
    # T-116: NO hay minimo de caracteres. Se probo (3) y se quito: no
    # cierra nada (3 caracteres siguen siendo un comodin sobre una
    # matricula de 6-7) y rompia un contrato ya verificado (T-93). El
    # acotado que importa es el LISTADO GLOBAL, que es de admin.
    plate: Optional[str] = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_STAFF)),
) -> list[Vehicle]:
    """Listado de vehiculos.

    T-116 (2026-10-23): este endpoint devolvia la **flota completa** a
    cualquier gestor u operador. Medido contra el sistema en marcha: el
    gestor de la sucursal 11 recibio las 6 matriculas del sistema, 3 de
    las cuales no aparecen en sus propios movimientos::

        GET /vehicles -> [200] 6 vehiculos:
        1111DIR, 1234ABC, 2222NEW, 8888ZZZ, 9999DIR, 9999ZZZ

    Ahora hay dos comportamientos distintos:

    - **Con** ``plate``: es una BUSQUEDA DIRIGIDA (el operador tiene la
      matricula delante, en la puerta) y la puede hacer el personal. Es
      global a proposito: un coche puede no tener ticket todavia en
      ninguna sucursal.
    - **Sin** ``plate``: el listado completo es de **admin**. Para el
      personal, el endpoint acotado es ``GET /parkings/{id}/vehicles``
      (los vehiculos de su sucursal), que es el que usa la vista de
      movimientos.
    """
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    if not plate and role_value != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El listado completo de la flota es solo para el administrador",
        )
    query = db.query(Vehicle)
    if plate:
        query = query.filter(
            Vehicle.plate.ilike(f"%{_escapar_like(plate)}%", escape="\\")
        )
    return query.order_by(Vehicle.plate).all()


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
@audited("create_vehicle")
def create_vehicle(
    payload: VehicleCreate,
    request: Request,
    db: Session = Depends(get_db),
    # T-116: el alta global de vehiculos es de ADMIN. Con staff, un
    # gestor de la sucursal A podia ocupar (squat) la matricula de un
    # cliente de B: el alta posterior de ese vehiculo en B fallaba con
    # 409 "Matricula duplicada". El alta legitima la hace el cliente
    # (POST /users/me/vehicles) o el operador con el alta manual de
    # ticket (POST /tickets/manual, que resuelve y crea el vehiculo).
    _user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> Vehicle:
    # Sprint Fase 3D: rate-limit por actor (staff autenticado).
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="vehicles_create", actor_id=actor_id,
        )
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Matrícula duplicada"
        ) from exc
    db.refresh(vehicle)
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleRead)
@audited("update_vehicle", resource_arg="vehicle_id")
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    # T-116: "Vehicle" es global (no tiene "parking_id"), asi que un
    # gestor de la sucursal A podia editar la marca, el modelo y el
    # color de un vehiculo que solo opera en B (lo que ve el cliente en
    # "Mis vehiculos"). De admin: el cliente edita los suyos con
    # PATCH /users/me/vehicles/{id}.
    _user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> Vehicle:
    # Sprint Fase 3D: rate-limit por actor en updates también.
    audit = getattr(request.state, "audit", None) or {}
    actor_id = audit.get("user_id")
    if actor_id is not None:
        _enforce_endpoint_rate_limit(
            request, db, scope="vehicles_update", actor_id=actor_id,
        )
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, key, value)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post(
    "/{vehicle_id}/users",
    response_model=VehicleUserRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("add_vehicle_user", resource_arg="vehicle_id")
def add_vehicle_user(
    vehicle_id: int,
    payload: VehicleUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    # T-116: este endpoint decidia QUE TICKETS VE CADA CLIENTE (la tabla
    # "vehicle_users" es el scope de los tickets de un cliente). Con
    # staff, un gestor de la sucursal A podia vincular CUALQUIER usuario
    # del sistema (incluidos clientes de B) a CUALQUIER vehiculo. De
    # admin: el vinculo legitimo lo hace el propietario con
    # POST /users/me/vehicles/{id}/links.
    _user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> VehicleUser:
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    link = VehicleUser(
        vehicle_id=vehicle_id,
        user_id=payload.user_id,
        role=VehicleRole(payload.role),
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Asociación duplicada"
        ) from exc
    db.refresh(link)
    return link