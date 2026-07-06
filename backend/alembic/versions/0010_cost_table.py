"""Añade tabla ``costs`` (Sprint P1 solidAPP, 2026-07-06).

Modelo para imputar costes operativos por sucursal y calcular el
margen en un periodo. La tabla incluye dos ENUMs Postgres:

  - ``costcategory`` (mantenimiento / camaras / operacion / otros)
  - ``costperiod`` (puntual / mensual / trimestral / anual)

El servicio ``compute_margin`` (en ``app/services/cost.py``) los usa
para prorratear costes recurrentes dentro del rango del reporte.

Revisa: 0009_camera_kind
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_cost_table"
down_revision: str | None = "0009_camera_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Crear los tipos Postgres para los dos enums. ``checkfirst``
    #    hace la migración idempotente ante recovery tras crash.
    costcategory = postgresql.ENUM(
        "mantenimiento", "camaras", "operacion", "otros",
        name="costcategory",
    )
    costcategory.create(op.get_bind(), checkfirst=True)

    costperiod = postgresql.ENUM(
        "puntual", "mensual", "trimestral", "anual",
        name="costperiod",
    )
    costperiod.create(op.get_bind(), checkfirst=True)

    # 2) Tabla ``costs``. FK a ``parkings`` con CASCADE para que al
    #    borrar la sucursal se vaya también su histórico de costes.
    op.create_table(
        "costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "parking_id", sa.Integer(),
            sa.ForeignKey("parkings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category",
            postgresql.ENUM(
                "mantenimiento", "camaras", "operacion", "otros",
                name="costcategory", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column(
            "periodicity",
            postgresql.ENUM(
                "puntual", "mensual", "trimestral", "anual",
                name="costperiod", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_costs_parking_id", "costs", ["parking_id"])
    op.create_index("ix_costs_category", "costs", ["category"])
    op.create_index("ix_costs_periodicity", "costs", ["periodicity"])
    op.create_index("ix_costs_period_start", "costs", ["period_start"])


def downgrade() -> None:
    op.drop_index("ix_costs_period_start", table_name="costs")
    op.drop_index("ix_costs_periodicity", table_name="costs")
    op.drop_index("ix_costs_category", table_name="costs")
    op.drop_index("ix_costs_parking_id", table_name="costs")
    op.drop_table("costs")
    # Tipos Postgres sin columnas que los usen → se pueden borrar.
    op.execute("DROP TYPE IF EXISTS costperiod")
    op.execute("DROP TYPE IF EXISTS costcategory")