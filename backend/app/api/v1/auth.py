"""Router de autenticación."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import User
from app.schemas import LoginRequest, MessageResponse, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_tokens(user: User) -> TokenPair:
    settings = get_settings()
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    access = create_access_token(user.id, extra={"role": role_value})
    refresh = create_refresh_token(user.id)
    return TokenPair(
        access_token=access,
        expires_in=settings.access_token_ttl_minutes * 60,
        refresh_token=refresh,
    )


@router.post("/login", response_model=TokenPair)
def login_json(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo"
        )
    return _build_tokens(user)


@router.post("/login/oauth", response_model=TokenPair)
def login_oauth(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenPair:
    user = db.query(User).filter(User.email == form.username).one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    return _build_tokens(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: TokenPair, db: Session = Depends(get_db)) -> TokenPair:
    try:
        data = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de refresco requerido"
        )
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no disponible"
        )
    return _build_tokens(user)


@router.post("/logout", response_model=MessageResponse)
def logout() -> MessageResponse:
    return MessageResponse(detail="Sesión cerrada")