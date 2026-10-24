"""Purga de los vehículos «fantasma» (T-125).

QUÉ ES UN VEHÍCULO FANTASMA
----------------------------
La ingesta crea el vehículo de una matrícula desconocida **antes** de
saber si va a haber ticket: si después la plaza está ocupada, o averiada,
o la cámara no tiene geocerca calibrada, el intento se queda a medias y
el vehículo se queda **sin dueño y sin ticket**. Como nadie lo borra, la
tabla ``vehicles`` crece sin límite en un sistema de OCR que ve
matrículas nuevas constantemente.

Medido el 2026-10-23 en la base de datos de QA: 3 vehículos con **cero**
dueños y **cero** tickets, creados el 2026-06-30 (casi cuatro meses
antes) y sin ninguna tarea que los purgara.

EL CRITERIO (tres condiciones, todas necesarias)
------------------------------------------------
1. **sin dueño**: no hay ninguna fila en ``vehicle_users``. Esto
   protege a los vehículos que los clientes dan de alta en la app
   (``POST /users/me/vehicles``): esos sí tienen dueño.
2. **sin tickets**: ni activos ni cerrados. Un vehículo que ha entrado
   alguna vez se queda para siempre (los tickets no se purgan: ver
   T-124, que es una decisión de producto pendiente).
3. **antiguo**: ``created_at`` anterior al corte. Sin esto, la purga
   borraría el vehículo de un coche que acaba de entrar y cuyo ticket
   todavía no se ha escrito.

OJO (2026-10-23): esto borra también los vehículos **de ejemplo** del
seed (``1111DIR``, ``2222NEW``, ``9999DIR``): son filas sin uso igual
que los fantasmas. El flujo de "dar de alta un coche desconocido" no
se rompe, porque el alta manual crea el vehículo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.vehicle import Vehicle

log = logging.getLogger(__name__)

#: Antigüedad mínima (en horas) para que un vehículo sin dueño y sin
#: tickets se considere fantasma. Con 24 h, el vehículo de un coche que
#: acaba de entrar (y cuyo ticket aún no está escrito) no se toca.
DEFAULT_MAX_AGE_HOURS = 24

#: Filas que trae la purga en cada lote (T-156). Sin esto, la purga
#: cargaba **todos** los vehículos fantasma a memoria de una vez (y la
#: tabla ``vehicles`` crece sin límite: es el motivo del T-125).
LOTE = 500


def _aware(momento: datetime | None) -> datetime | None:
    """Normaliza a UTC con zona horaria.

    OJO: un ``datetime`` que viene de la base de datos vuelve **naive**
    en SQLite (en PostgreSQL sí trae zona). Comparar un naive con un
    aware da un resultado **falso** (en SQLite se comparan como
    cadenas), asi que la comparación se hace aqui, en Python, y no en
    la consulta.
    """
    if momento is None:
        return None
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def vehiculos_fantasma(db: Session, limite: int | None = None) -> list[Vehicle]:
    """Los vehículos sin dueño y sin tickets (sin el filtro de antigüedad).

    T-156 (2026-10-24): con ``limite`` se traen **los más antiguos
    primero** y sólo ese número, para que la purga vaya por lotes en vez
    de cargar la tabla entera en memoria.
    """
    consulta = (
        db.query(Vehicle)
        .filter(~Vehicle.users.any())
        .filter(
            ~db.query(Ticket)
            .filter(Ticket.vehicle_id == Vehicle.id)
            .exists()
        )
        .order_by(Vehicle.created_at)
    )
    if limite is not None:
        consulta = consulta.limit(limite)
    return consulta.all()


def purgar_vehiculos_fantasma(
    db: Session,
    max_age_hours: int | None = None,
) -> dict[str, object]:
    """Borra los vehículos fantasma más antiguos que el corte.

    Idempotente: si no hay nada que borrar devuelve ``deleted=0``.
    Defensivo: un fallo al borrar **no** propaga (una purga no puede
    tumbar al worker).

    T-156 (2026-10-24): va **por lotes** (como la purga de auditoría,
    T-104). Antes traía **todos** los vehículos fantasma a memoria de una
    vez y los filtraba por antigüedad en Python.
    """
    horas = DEFAULT_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    ahora = datetime.now(timezone.utc)
    corte = ahora - timedelta(hours=horas)

    borrados: list[int] = []
    while True:
        # Los más antiguos primero: si del lote no sale ninguno que cumpla
        # el corte, los siguientes son más recientes y no hay nada más que
        # purgar (y el bucle termina).
        lote = vehiculos_fantasma(db, limite=LOTE)
        if not lote:
            break
        borrables = []
        for vehiculo in lote:
            creado = _aware(vehiculo.created_at)
            if creado is None or creado >= corte:
                # Todavía no tiene edad: el coche puede haber entrado ahora
                # mismo y su ticket escribirse después.
                continue
            borrables.append(vehiculo)
        if not borrables:
            break
        for vehiculo in borrables:
            borrados.append(vehiculo.id)
            db.delete(vehiculo)
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001 — una purga no propaga
            db.rollback()
            log.warning(
                "purga de vehiculos fantasma: no se pudo confirmar: %s", exc
            )
            return {
                "deleted": 0,
                "max_age_hours": horas,
                "cutoff": corte.isoformat(),
            }
        if len(lote) < LOTE:
            # No hay más vehículos fantasma: se acabó.
            break

    log.info(
        "purga de vehiculos fantasma: horas=%s corte=%s borrados=%s",
        horas,
        corte.isoformat(),
        len(borrados),
    )
    return {
        "deleted": len(borrados),
        "max_age_hours": horas,
        "cutoff": corte.isoformat(),
    }
