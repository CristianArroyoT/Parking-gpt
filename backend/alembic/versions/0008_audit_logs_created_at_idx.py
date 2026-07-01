"""Índice dedicado sobre ``audit_logs.created_at`` para la rotación Fase 3C.

Sprint Fase 3C (2026-07-01). Sin este índice la task
``solidapp.purge_audit_logs`` haría seq scan sobre toda la tabla
(con millones de filas se vuelve de minutos). El índice compuesto
``ix_audit_logs_user_id_created_at`` (migración 0007) NO cubre esta
query porque la rotación filtra sólo por ``created_at``, sin user_id.

Revises: 0007_audit_log_extended
Create Date: 2026-07-01 12:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0008_audit_logs_created_at_idx"
down_revision: Union[str, None] = "0007_audit_log_extended"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_logs_created_at",
        "audit_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")