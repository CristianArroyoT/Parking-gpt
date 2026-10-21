"""Adjuntos de incidentes (T-21) y autor del incidente.

Dos cosas, en la misma revisión:

- ``incident_attachments``: **metadata** de las fotos adjuntas a un
  incidente (nombre original, hash del contenido, mime, tamaño y rutas
  relativas dentro del volumen local). El binario **no** va a la base
  de datos: vive en el volumen ``incident_attachments`` con el nombre
  derivado del SHA-256 del contenido.

- ``alerts.created_by``: quién reportó el incidente. Las alertas del
  sistema (cámara caída, OCR fallido…) lo tienen a NULL. Con
  ``ON DELETE CASCADE``, borrar al usuario borra su incidente y, en
  cascada, sus fotos adjuntas —derecho al olvido (LOPDGDD)—.

AVISO: el ``downgrade`` **borra** la tabla ``incident_attachments``. Si
se ejecuta sobre una base con fotos, esa información se pierde de
forma irreversible (y los ficheros del volumen se quedan huérfanos).

Revisa: 0012_reset_and_face_templates
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_incident_attachments"
down_revision: str | None = "0012_reset_and_face_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── alerts.created_by (autor del incidente) ───────────────────────────
    # ``batch_alter_table`` para que la migración también funcione en
    # SQLite (que no admite ``ALTER TABLE ... ADD CONSTRAINT``).
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(
            sa.Column("created_by", sa.Integer(), nullable=True),
        )
        batch.create_index("ix_alerts_created_by", ["created_by"])
        batch.create_foreign_key(
            "fk_alerts_created_by_users",
            "users",
            ["created_by"],
            ["id"],
            ondelete="CASCADE",
        )

    # ── incident_attachments (metadata; el binario va al volumen) ────────
    op.create_table(
        "incident_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alert_id", sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parking_id", sa.Integer(),
            sa.ForeignKey("parkings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        # SHA-256 en hexadecimal del contenido: de ahí se deriva el
        # nombre del fichero en el volumen.
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        # Tipo verificado por los BYTES del fichero, no el que declara
        # el cliente.
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        # Rutas RELATIVAS al directorio del volumen.
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("thumbnail_path", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_incident_attachments_alert_id", "incident_attachments", ["alert_id"],
    )
    op.create_index(
        "ix_incident_attachments_parking_id", "incident_attachments", ["parking_id"],
    )
    op.create_index(
        "ix_incident_attachments_uploaded_by", "incident_attachments", ["uploaded_by"],
    )
    op.create_index(
        "ix_incident_attachments_content_hash", "incident_attachments", ["content_hash"],
    )
    op.create_index(
        "ix_incident_attachments_expires_at", "incident_attachments", ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incident_attachments_expires_at", table_name="incident_attachments",
    )
    op.drop_index(
        "ix_incident_attachments_content_hash", table_name="incident_attachments",
    )
    op.drop_index(
        "ix_incident_attachments_uploaded_by", table_name="incident_attachments",
    )
    op.drop_index(
        "ix_incident_attachments_parking_id", table_name="incident_attachments",
    )
    op.drop_index(
        "ix_incident_attachments_alert_id", table_name="incident_attachments",
    )
    # AVISO: borra la tabla completa (con datos de fotos).
    op.drop_table("incident_attachments")

    with op.batch_alter_table("alerts") as batch:
        batch.drop_constraint("fk_alerts_created_by_users", type_="foreignkey")
        batch.drop_index("ix_alerts_created_by")
        batch.drop_column("created_by")
