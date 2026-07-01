"""Amplía audit_logs con parking_id, result, duration_ms, correlation_id.

Sprint Fase 3A Auditoría Operativa + Loki (2026-07-01).

Revises: 0006_camera_health
Create Date: 2026-07-01 00:00:00

Añade 4 columnas a ``audit_logs``:

  - ``parking_id`` FK SET NULL — permite consultas "qué pasó en el
    parking X" sin pasar por el JSON.
  - ``result`` String(16) — ``"success"`` | ``"failure"`` | NULL. Permite
    distinguir operaciones exitosas de las que hicieron rollback.
  - ``duration_ms`` Integer — latencia del handler auditado.
  - ``correlation_id`` String(36) UUID — une todos los logs del mismo
    request HTTP con su ``audit_log`` y con los ``log.warning/info`` de
    Python. Acepta un UUID entrante vía header ``X-Request-ID`` o
    genera uno nuevo (en ``AuditMiddleware``).

Sin backfill explícito: los registros históricos quedan con NULL en las
4 columnas nuevas. El sistema los irá rellenando a medida que audite
eventos nuevos.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_audit_log_extended"
down_revision: Union[str, None] = "0006_camera_health"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column(
            "parking_id",
            sa.Integer(),
            sa.ForeignKey("parkings.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column("result", sa.String(16), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("correlation_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_audit_logs_parking_id",
        "audit_logs",
        ["parking_id"],
    )
    op.create_index(
        "ix_audit_logs_correlation_id",
        "audit_logs",
        ["correlation_id"],
    )
    op.create_index(
        "ix_audit_logs_user_id_created_at",
        "audit_logs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_id_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_parking_id", table_name="audit_logs")
    op.drop_column("audit_logs", "correlation_id")
    op.drop_column("audit_logs", "duration_ms")
    op.drop_column("audit_logs", "result")
    op.drop_column("audit_logs", "parking_id")