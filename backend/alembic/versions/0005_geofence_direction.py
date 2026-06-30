"""Añade `direction` a `camera_geofences` (sprint Dirección Cámara 2026-06-30).

Revision ID: 0005_geofence_direction
Revises: 0004_space_broken
Create Date: 2026-06-30 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_geofence_direction"
down_revision: Union[str, None] = "0004_space_broken"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "camera_geofences",
        sa.Column(
            "direction",
            sa.String(8),
            nullable=False,
            server_default="entry",
        ),
    )
    op.create_index(
        "ix_camera_geofences_direction",
        "camera_geofences",
        ["direction"],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_geofences_direction", table_name="camera_geofences")
    op.drop_column("camera_geofences", "direction")