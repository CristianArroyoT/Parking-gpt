"""Añade ``kind`` a ``cameras`` (Sprint Fase 4 solidAPP, 2026-07-01).

Distingue cámaras de fiscalización (``surveillance``) vs cámaras de
portería (``gate``). Las cámaras de portería están dedicadas a una
única transacción de barrera (entrada o salida) y se usan cuando el
operador emite tickets manualmente desde el stream RTSP.

Revisa: 0008_audit_logs_created_at_idx
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_camera_kind"
down_revision: Union[str, None] = "0008_audit_logs_created_at_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Crear el tipo nativo Postgres ``camerakind``. ``checkfirst``
    # lo hace idempotente si la migración se ejecuta dos veces (p. ej.
    # recovery tras crash).
    camkind = postgresql.ENUM("surveillance", "gate", name="camerakind")
    camkind.create(op.get_bind(), checkfirst=True)

    # 2) Añadir la columna con ``server_default='surveillance'`` para
    # rellenar automáticamente las filas existentes (back-compat).
    op.add_column(
        "cameras",
        sa.Column(
            "kind",
            postgresql.ENUM("surveillance", "gate", name="camerakind",
                            create_type=False),
            nullable=False,
            server_default="surveillance",
        ),
    )
    op.create_index(
        "ix_cameras_kind",
        "cameras",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_cameras_kind", table_name="cameras")
    op.drop_column("cameras", "kind")
    # El tipo Postgres se elimina explícitamente porque ya no hay
    # columnas que lo usen.
    op.execute("DROP TYPE IF EXISTS camerakind")

