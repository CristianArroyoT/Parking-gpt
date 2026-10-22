"""Utilidades de seguridad: hash de contraseñas y JWT."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.password_policy import LIMITE_BYTES_BCRYPT

_settings = get_settings()
# ``truncate_error=True``: bcrypt solo tiene en cuenta los primeros 72
# bytes y **trunca en silencio**. Con esta opcion passlib **falla** en
# vez de guardar (o comparar) una contrasena truncada (T-87). Sin ella,
# una contrasena de 100 caracteres se guardaba como si fueran 72.
_pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", truncate_error=True,
)

# Hash bcrypt SENUELO (T-86): 12 rondas, como los de verdad. Se usa para
# que el login tarde lo mismo exista o no la cuenta. Medido antes del
# arreglo: 13,9 ms con un email inexistente frente a 207,6 ms con un
# email real y contrasena incorrecta (15 veces de diferencia: un oraculo
# para enumerar que emails estan registrados).
_HASH_SENUELO = "$2b$12$3QZrzBhg1hQg7GIAgtzZTOJa/uig1GzIGfmJ61dny9PQj3B8uAKDG"


def hash_password(plain: str) -> str:
    """Devuelve el hash bcrypt de la contraseña en claro."""
    # passlib no esta tipado: devuelve Any.
    return cast(str, _pwd_context.hash(plain))


def _bcrypt_verify(plain: str, hashed: str) -> bool:
    """Compara la contrasena con el hash (truncando, como hace bcrypt)."""
    try:
        return cast(bool, _pwd_context.verify(plain, hashed))
    except ValueError:
        return False


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica una contraseña contra su hash.

    OJO (T-87): ``truncate_error=True`` de passlib sólo protege al
    **hashear**: al **verificar**, bcrypt trunca en silencio y una
    contrasena de 80 bytes con los mismos 72 primeros que la original
    **entaba**. Medido: ``verify_password("A" * 80, hash_de_72)`` era
    ``True`` con el flag puesto. Por eso aqui se rechaza, antes de
    comparar, cualquier contrasena que pase de 72 bytes: el sistema no
    admite contrasenas que no puede distinguir.
    """
    if len(plain.encode("utf-8")) > LIMITE_BYTES_BCRYPT:
        return False
    return _bcrypt_verify(plain, hashed)


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    """Verifica contra ``hashed``; si no hay hash, contra uno SENUELO.

    Devuelve ``False`` cuando ``hashed`` es ``None`` (usuario
    inexistente), pero **tarda lo mismo** que una verificacion real: el
    bcrypt se ejecuta contra ``_HASH_SENUELO`` y su resultado se
    descarta. Sin esto, el tiempo de respuesta del login filtraba que
    correos estan registrados (T-86).
    """
    if hashed is None:
        # Aunque la contrasena sea larga, se quema el tiempo del bcrypt:
        # el suelo de latencia no puede depender de la longitud.
        _bcrypt_verify(plain, _HASH_SENUELO)
        return False
    return verify_password(plain, hashed)


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
    # pyjwt no esta tipado: devuelve Any.
    return cast(str, jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm))


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
    return cast(str, jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm))


def decode_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un JWT. Devuelve el payload."""
    try:
        return cast(dict[str, Any], jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm]))
    except JWTError as exc:
        raise ValueError("Token inválido o expirado") from exc
