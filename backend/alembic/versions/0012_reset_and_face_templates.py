"""Añade las tablas de T-22 y T-23 (plan maestro 2026-10-21).

Dos estructuras "preparadas" que agrupan el mismo bloque del plan:

- ``password_reset_tokens`` (T-22): tokens de un solo uso para el
  flujo de "olvidé mi contraseña". En la tabla sólo vive el **hash
  SHA-256** del token; el token en claro viaja por el correo.

- ``face_templates`` (T-23): estructura de datos del reconocimiento
  facial. **Fuera del MVP**: la tabla se crea, pero el endpoint que la
  usa está deshabilitado por feature flag (``FACE_TEMPLATES_ENABLED``,
  por defecto ``false``) y **no se usa para autenticar a nadie**.

Van las dos en la misma revisión (0012) porque las comparten el mismo
ciclo de despliegue y el plan maestro asigna una única revisión nueva
a este bloque.

AVISO: el ``downgrade`` **borra** ``face_templates``. Si se ejecuta sobre
una base con datos, esa información se pierde de forma irreversible.

Revisa: 0011_user_no_rate_limit
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_reset_and_face_templates"
down_revision: str | None = "0011_user_no_rate_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── T-22 · password_reset_tokens ──────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Hash SHA-256 en hexadecimal del token en claro (nunca el token).
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
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
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"],
    )
    # Único: un hash de token sólo puede existir una vez.
    op.create_index(
        "ix_password_reset_tokens_token_hash", "password_reset_tokens",
        ["token_hash"], unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at", "password_reset_tokens",
        ["expires_at"],
    )

    # ── T-23 · face_templates (FUERA DEL MVP) ─────────────────────────────
    op.create_table(
        "face_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # La cámara es informativa: si se da de baja la cámara, el
        # template se conserva (ON DELETE SET NULL).
        sa.Column(
            "camera_id", sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Vector de características. Se guarda como JSON: es la estructura
        # preparada, NO se usa para autenticar a nadie todavía.
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_face_templates_user_id", "face_templates", ["user_id"])
    op.create_index("ix_face_templates_camera_id", "face_templates", ["camera_id"])


def downgrade() -> None:
    # AVISO: borra la tabla completa. Con datos de face_templates, esa
    # información se pierde de forma irreversible.
    op.drop_index("ix_face_templates_camera_id", table_name="face_templates")
    op.drop_index("ix_face_templates_user_id", table_name="face_templates")
    op.drop_table("face_templates")

    op.drop_index(
        "ix_password_reset_tokens_expires_at", table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_token_hash", table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_user_id", table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
