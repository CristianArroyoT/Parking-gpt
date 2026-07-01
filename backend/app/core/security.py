"""Utilidades de seguridad: hash de contraseñas y JWT."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Devuelve el hash bcrypt de la contraseña en claro."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica una contraseña contra su hash."""
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    """Genera un JWT de acceso con TTL corto.

    Sprint Fase 3D (2026-07-01): incluye ``jti`` (UUID v4 hex de 32
    chars) como claim. Permite el blacklist real de tokens en logout
    (cada token emitido tiene un id único persistido en Redis cuando
    el usuario cierra sesión).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_settings.access_token_ttl_minutes)).timestamp()),
        "type": "access",
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def create_refresh_token(subject: str | int) -> str:
    """Genera un JWT de refresco con TTL largo.

    Sprint Fase 3D: incluye ``jti`` (coherente con access). El refresh
    NO se blacklistea en logout actual (queda fuera de scope del MVP;
    ver riesgos del sprint), pero lleva jti por simetría y porque
    cualquier futura invalidación de refresh lo necesitará.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_settings.refresh_token_ttl_days)).timestamp()),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un JWT. Devuelve el payload."""
    try:
        return jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Token inválido o expirado") from exc
