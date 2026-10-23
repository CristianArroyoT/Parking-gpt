"""Un vehiculo no puede tener dos tickets activos (T-105).

POR QUE: la ingesta comprobaba antes de insertar (un SELECT de "este
vehiculo ya tiene ticket activo") y despues insertaba. Eso es un
"comprueba y luego hace": dos pushes de la misma matricula a la vez
(dos rondas solapadas, o dos peticiones simultaneas) podian pasar las
dos comprobaciones y crear **DOS tickets activos** -> el cliente
cobraba dos veces.

Con estos indices, la **base de datos** lo prohibe (es lo unico que una
carrera no puede saltar) y el codigo captura el rechazo y devuelve el
ticket que ya habia.

- ``uq_tickets_activo_vehiculo``: un vehiculo, como mucho, un ticket
  activo por sucursal.
- ``uq_tickets_activo_plaza``: una plaza, como mucho, un vehiculo.

Si la base ya tuviera datos que violen la regla, la migracion **falla**
(es lo que hay que hacer: el operador tiene que resolver el duplicado
antes, no que la base lo acepte).

Revisa: 0015_email_canonico
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ticket_activo_unico"
down_revision: str | None = "0015_email_canonico"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_tickets_activo_vehiculo",
        "tickets",
        ["vehicle_id", "parking_id"],
        unique=True,
        sqlite_where=sa.text("status = 'activo'"),
        postgresql_where=sa.text("status = 'activo'"),
    )
    op.create_index(
        "uq_tickets_activo_plaza",
        "tickets",
        ["parking_space_id"],
        unique=True,
        sqlite_where=sa.text("status = 'activo' AND parking_space_id IS NOT NULL"),
        postgresql_where=sa.text("status = 'activo' AND parking_space_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tickets_activo_plaza", table_name="tickets")
    op.drop_index("uq_tickets_activo_vehiculo", table_name="tickets")
