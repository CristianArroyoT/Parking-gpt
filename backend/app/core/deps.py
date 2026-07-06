"""Dependencias compartidas: usuario actual, RBAC y contexto de sucursal."""

from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decodifica el JWT, recupera el usuario activo o lanza 401."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token no válido",
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuario no válido",
        ) from exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo")
    return user


def require_role(*roles: str):
    """Devuelve una dependencia que valida el rol del usuario actual."""

    allowed = set(roles)

    def _checker(current: User = Depends(get_current_user)) -> User:
        role_value = current.role.value if hasattr(current.role, "value") else current.role
        if role_value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta operación",
            )
        return current

    return _checker


def parking_context(
    parking_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Valida que el usuario (no admin) tenga membresía en la sucursal."""
    from app.models.user import ParkingMembership

    # El rol se persiste como String(16); tras recargar el ORM puede venir
    # como enum o como str (depende del flush). Aceptamos ambos casos.
    role_value = current.role.value if hasattr(current.role, "value") else current.role
    if role_value == "admin":
        return current

    membership = (
        db.query(ParkingMembership)
        .filter(
            ParkingMembership.user_id == current.id,
            ParkingMembership.parking_id == parking_id,
        )
        .one_or_none()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene acceso a esta sucursal",
        )
    return current


def require_any_role(roles: Iterable[str]) -> str:
    """Helper de tipo: expone un iterable para fastapi.Depends."""
    return ",".join(roles)


def get_current_user_or_query_token(
    request: Request,
    token: str | None = Query(default=None),
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Igual que ``get_current_user`` pero también acepta ``?token=...``.

    Pensado para el endpoint SSE (``GET /parkings/{id}/events``).
    ``EventSource`` del navegador NO permite setear el header
    ``Authorization``; por eso permitimos pasar el JWT en query
    string como fallback. Riesgo: el token queda en logs de proxies
    intermedios. Mitigado por ``ACCESS_TOKEN_TTL_MINUTES=15``.

    Si ni header ni query traen token → 401. Si ambos vienen → gana
    el header (``bearer_token`` no es ``None`` cuando viene el header).

    Sprint O2 (2026-07-06).
    """
    raw: str | None = bearer_token or token
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token no válido",
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuario no válido",
        ) from exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo")
    return user
