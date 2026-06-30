"""Añade tabla plates_detected (resultados OCR por cámara).

Revision ID: 0002_plates_detected
Revises: 0001_initial
Create Date: 2026-06-30 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_plates_detected"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plates_detected",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer,
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plate", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("bbox_x1", sa.Integer, nullable=False),
        sa.Column("bbox_y1", sa.Integer, nullable=False),
        sa.Column("bbox_x2", sa.Integer, nullable=False),
        sa.Column("bbox_y2", sa.Integer, nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response", sa.JSON),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_plates_detected_camera_id", "plates_detected", ["camera_id"]
    )
    op.create_index(
        "ix_plates_detected_detected_at", "plates_detected", ["detected_at"]
    )
    op.create_index(
        "ix_plates_detected_plate", "plates_detected", ["plate"]
    )


def downgrade() -> None:
    op.drop_index("ix_plates_detected_plate", table_name="plates_detected")
    op.drop_index(
        "ix_plates_detected_detected_at", table_name="plates_detected"
    )
    op.drop_index(
        "ix_plates_detected_camera_id", table_name="plates_detected"
    )
    op.drop_table("plates_detected")