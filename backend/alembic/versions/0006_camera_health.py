"""Añade `last_heartbeat_at` + `last_heartbeat_ok` a `cameras` (sprint Camera Health).

Revision ID: 0006_camera_health
Revises: 0005_geofence_direction
Create Date: 2026-07-01 00:00:00

Ambas columnas ``nullable=True`` — el valor inicial "nunca probada" es NULL,
sin backfill explícito. La task ``probe_heartbeats`` escribe el primer valor
en su próxima ronda (cada 60 s).

El índice ``ix_cameras_last_heartbeat_at`` cubre queries futuras tipo
"cámaras sin heartbeat hace > N min", que formarán parte de la Fase 3
(dashboards operativos). En este sprint no se consulta desde ningún
servicio.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_camera_health"
down_revision: Union[str, None] = "0005_geofence_direction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cameras",
        sa.Column("last_heartbeat_ok", sa.Boolean, nullable=True),
    )
    op.create_index(
        "ix_cameras_last_heartbeat_at",
        "cameras",
        ["last_heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cameras_last_heartbeat_at", table_name="cameras")
    op.drop_column("cameras", "last_heartbeat_ok")
    op.drop_column("cameras", "last_heartbeat_at")
