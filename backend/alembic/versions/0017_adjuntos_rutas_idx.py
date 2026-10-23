"""Indices en las rutas de los adjuntos (T-108).

POR QUE: la purga de adjuntos caducados busca, por cada adjunto, si otro
adjunto apunta al mismo fichero (para no borrar un fichero que otro sigue
usando). Sin indice, esa busqueda es un **Seq Scan** de la tabla
entera: medido el 2026-10-23, el plan era "Seq Scan on
incident_attachments", y con 1.000 adjuntos caducados la tarea de las
3:17 hacia 2.000 escaneos completos.

Revisa: 0016_ticket_activo_unico
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_adjuntos_rutas_idx"
down_revision: str | None = "0016_ticket_activo_unico"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_incident_attachments_storage_path",
        "incident_attachments",
        ["storage_path"],
    )
    op.create_index(
        "ix_incident_attachments_thumbnail_path",
        "incident_attachments",
        ["thumbnail_path"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incident_attachments_thumbnail_path", table_name="incident_attachments",
    )
    op.drop_index(
        "ix_incident_attachments_storage_path", table_name="incident_attachments",
    )
