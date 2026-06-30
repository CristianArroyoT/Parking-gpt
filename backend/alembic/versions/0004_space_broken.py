"""Añade `is_broken` y `is_broken_at` a `parking_spaces` (sprint Marcar Plaza / Robo).

Revision ID: 0004_space_broken
Revises: 0003_ticket_origin
Create Date: 2026-06-30 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_space_broken"
down_revision: Union[str, None] = "0003_ticket_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parking_spaces",
        sa.Column(
            "is_broken",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "parking_spaces",
        sa.Column("is_broken_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_parking_spaces_is_broken", "parking_spaces", ["is_broken"]
    )


def downgrade() -> None:
    op.drop_index("ix_parking_spaces_is_broken", table_name="parking_spaces")
    op.drop_column("parking_spaces", "is_broken_at")
    op.drop_column("parking_spaces", "is_broken")