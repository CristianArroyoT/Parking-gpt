"""Token de recuperación de contraseña (T-22 · plan maestro 2026-10-21).

Antes de este sprint **no existía** ningún flujo de "olvidé mi contraseña":
el login sólo aceptaba usuario + contraseña y la única forma de recuperar
el acceso era que un admin reiniciara la clave a mano.

Decisiones de seguridad (no negociables):

- **En la BD sólo se guarda el hash SHA-256 del token**, nunca el token en
  claro. Si alguien lee (o se lleva) la tabla ``password_reset_tokens`` no
  puede usarla para resetear contraseñas: el token en claro viaja
  únicamente por el correo del usuario.
- **Un token es de un solo uso**: ``used_at`` lo marca como consumido y a
  partir de ahí deja de valer, aunque su ``expires_at`` siga en el futuro.
- **Caducidad**: ``expires_at`` acota la ventana (30 minutos por defecto).
- Al pedir un reset nuevo, los tokens pendientes anteriores del usuario se
  invalidan: sólo el último correo recibido sirve.

La tabla NO guarda el email ni la contraseña en claro: sólo el vínculo con
el usuario y el hash del token.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class PasswordResetToken(Base, TimestampMixin):
    """Token de un solo uso para restablecer la contraseña de un usuario."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Hash SHA-256 en hexadecimal (64 caracteres) del token en claro.
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False,
    )
    #: Instante en el que el token deja de ser válido (30 min por defecto).
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False,
    )
    #: Instante en el que el token se consumió (NULL ⇒ todavía no usado).
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    #: IP desde la que se pidió el reset (telemetría anti-abuso).
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = ["PasswordResetToken"]
