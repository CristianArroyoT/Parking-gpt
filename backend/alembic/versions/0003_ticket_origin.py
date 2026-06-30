"""Añade columna `origin` a `tickets` (sprint Alta Manual del Operador).

Revision ID: 0003_ticket_origin
Revises: 0002_plates_detected
Create Date: 2026-06-30 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ticket_origin"
down_revision: Union[str, None] = "0002_plates_detected"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "origin",
            sa.String(16),
            nullable=False,
            server_default="automatic",
        ),
    )
    op.create_index("ix_tickets_origin", "tickets", ["origin"])


def downgrade() -> None:
    op.drop_index("ix_tickets_origin", table_name="tickets")
    op.drop_column("tickets", "origin")