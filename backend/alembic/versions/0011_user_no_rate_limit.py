"""Añade ``users.no_rate_limit`` (Sprint hardening R6, 2026-07-06).

Permite que service accounts (p. ej. cronjobs de carga inicial de datos)
se salten el rate-limit de los CRUDs autenticados sin tener que cambiar
settings globales. Default ``false`` para todos los usuarios existentes.

Revisa: 0010_cost_table
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_user_no_rate_limit"
down_revision: str | None = "0010_cost_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "no_rate_limit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "no_rate_limit")