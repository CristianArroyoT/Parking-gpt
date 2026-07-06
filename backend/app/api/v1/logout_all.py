"""Endpoint ``/auth/logout/all`` (Sprint R2, 2026-07-06).

Invalida TODAS las sesiones del usuario (access + refresh) blacklistando
cada ``jti`` registrado en el set ``user:{user_id}:active_jtis``. Usado
como botón de pánico (p. ej. "me robaron el móvil, invalida todo").

Aislado de ``app/api/v1/auth.py`` para minimizar el surface area del
cambio — un único handler + 1 import en ``api/v1/__init__.py``. El hook
en ``_build_tokens`` (que añade jtis al set en login/refresh) queda
fuera de este sprint y se aplicará en un follow-up; sin ese hook, el
set está vacío en condiciones normales y ``revoke_all`` devuelve 0.

RBAC: self-only (sólo el usuario autenticado puede cerrar SUS
sesiones). ``request.state.audit["user_id"]`` identifica al caller.

Audit ``logout_all_success`` con ``payload.revoked_count`` (número
de jtis invalidados). Si Redis cae durante ``revoke_all`` →
``RedisError`` propaga → 503 (fail-CLOSED, mismo patrón que
``token_blacklist.add``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import MessageResponse
from app.services.audit import record_audit_from_request
from app.services.session_tracker import session_tracker

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/logout/all",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
def logout_all(
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Invalida todas las sesiones del usuario autenticado.

    Steps:
      1. Lee ``user_id`` de ``request.state.audit`` (poblado por
         ``AuditMiddleware`` tras decodificar el JWT).
      2. ``session_tracker.revoke_all(user_id)`` → blacklistea cada
         jti del set en Redis con su TTL y elimina el set.
      3. Audita ``logout_all_success`` con ``revoked_count``.

    Devuelve ``MessageResponse`` siempre que el usuario esté
    autenticado. Si el set está vacío (cero sesiones trackeadas —
    caso normal porque el hook en ``_build_tokens`` aún no está
    integrado), devuelve 200 con ``revoked_count=0``.
    """
    audit = getattr(request.state, "audit", None) or {}
    user_id = audit.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        revoked = session_tracker.revoke_all(user_id=user_id)
    except RedisError as exc:
        db.rollback()
        # Fail-CLOSED: si no podemos garantizar la invalidación
        # masiva, devolvemos 503. El cliente reintenta.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no disponible",
        ) from exc

    record_audit_from_request(
        request, db,
        action="logout_all_success",
        resource=f"users/{user_id}",
        payload={"revoked_count": revoked},
        result="success",
    )
    db.commit()
    return MessageResponse(
        detail=f"Sesiones cerradas: {revoked}",
    )