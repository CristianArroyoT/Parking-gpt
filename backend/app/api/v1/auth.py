"""Router de autenticación."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.ip import get_real_ip
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import User
from app.schemas import LoginRequest, MessageResponse, TokenPair
from app.services.audit import record_audit_from_request
from app.services.rate_limit import rate_limiter
from app.services.token_blacklist import token_blacklist

log = logging.getLogger(__name__)

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
def login_json(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPair:
    # Sprint Fase 3C: rate-limit por IP + email (Redis INCR + EXPIRE).
    # Si CUALQUIER bucket supera ``login_rate_limit_max_attempts`` en
    # ``login_rate_limit_window_seconds`` → 429 Too Many Requests y
    # audit con ``action=rate_limited_login``. Fail-open si Redis cae.
    client_ip = get_real_ip(request)
    allowed, bucket, count = rate_limiter.check(
        ip=client_ip, email=payload.email,
    )
    if not allowed:
        record_audit_from_request(
            request, db,
            action="rate_limited_login",
            payload={
                "email": payload.email,
                "ip": client_ip,
                "bucket": bucket,
                "count": count,
            },
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Intenta más tarde.",
        )
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        # Sprint Fase 3A: audit de intento fallido (sin password).
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={"email": payload.email, "reason": "invalid_credentials"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    if not user.is_active:
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={"email": payload.email, "reason": "user_inactive"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo"
        )
    # Login OK: audit.
    record_audit_from_request(
        request, db,
        action="login_success",
        resource=f"users/{user.id}",
        payload={"email": user.email, "role": user.role.value if hasattr(user.role, "value") else str(user.role)},
        result="success",
    )
    db.commit()
    return _build_tokens(user)


@router.post("/login/oauth", response_model=TokenPair)
def login_oauth(
    form: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db),
) -> TokenPair:
    user = db.query(User).filter(User.email == form.username).one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={"email": form.username, "reason": "invalid_credentials",
                      "grant_type": "oauth_form"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    record_audit_from_request(
        request, db,
        action="login_success",
        resource=f"users/{user.id}",
        payload={"email": user.email, "grant_type": "oauth_form"},
        result="success",
    )
    db.commit()
    return _build_tokens(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: TokenPair,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPair:
    try:
        data = decode_token(payload.refresh_token)
    except ValueError as exc:
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": str(exc)},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if data.get("type") != "refresh":
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": "wrong_token_type"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de refresco requerido"
        )
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active:
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": "user_unavailable"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no disponible"
        )
    record_audit_from_request(
        request, db,
        action="refresh_success",
        resource=f"users/{user.id}",
        result="success",
    )
    db.commit()
    return _build_tokens(user)


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, db: Session = Depends(get_db)) -> MessageResponse:
    """Logout real: blacklistea el ``jti`` del token actual en Redis.

    Sprint Fase 3D (2026-07-01). Antes (Fase 3A) sólo registraba audit.
    Ahora: añade el ``jti`` del JWT actual al blacklist con TTL
    ``(exp - now) + grace_seconds``, de forma que el ``AuditMiddleware``
    rechace cualquier request subsecuente con el mismo token.

    Si el token no tiene ``jti`` (legacy pre-Fase 3D), auditamos
    ``logout_success`` con ``jti_blacklisted=False`` y respondemos 200
    igualmente (degradación graceful — el sistema sigue funcionando, sólo
    que ese token concreto no puede ser invalidado).

    Si Redis cae durante el blacklist → 503 ``Servicio de autenticación
    no disponible``. Fail-CLOSED: preferible un logout fallido antes
    que un token comprometido circulando.
    """
    audit = getattr(request.state, "audit", None) or {}
    user_id = audit.get("user_id")
    jti = audit.get("jti")
    exp = audit.get("exp")

    jti_blacklisted = False
    if jti is not None and exp is not None:
        try:
            token_blacklist.add(jti=jti, exp_epoch=int(exp))
            jti_blacklisted = True
        except RedisError as exc:
            db.rollback()
            log.warning(
                "logout: Redis caído, no se pudo blacklistear jti=%s (%s)",
                jti, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación no disponible",
            )

    record_audit_from_request(
        request, db,
        action="logout_success",
        resource=f"users/{user_id}" if user_id else None,
        payload={"jti_blacklisted": jti_blacklisted},
        result="success",
    )
    db.commit()
    return MessageResponse(detail="Sesión cerrada")