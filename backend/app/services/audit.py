"""Servicios de auditoría operativa (sprint Fase 3A, 2026-07-01).

API principal:
  - ``record_audit``: escribe en ``audit_logs``. NO hace commit (el
    caller decide, igual que el legacy de Fase 1).
  - ``record_audit_from_request``: helper que lee el contexto del
    ``AuditMiddleware`` (request.state.audit) y llama a ``record_audit``.

Back-compat: ``app.services.__init__.record_audit`` re-exporta esta
función para no romper los 4 callers de Fase 1/2 (``incidents.py``,
``manual_tickets.py``).
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    ip: str | None = None,
    resource: str | None = None,
    payload: dict[str, Any] | None = None,
    confidence: float | None = None,
    parking_id: int | None = None,
    result: str | None = None,
    duration_ms: int | None = None,
    correlation_id: str | None = None,
) -> None:
    """Inserta en audit_logs sin commit (lo hace el caller)."""
    db.add(
        AuditLog(
            user_id=user_id,
            ip=ip,
            action=action,
            resource=resource,
            payload=payload,
            confidence=confidence,
            parking_id=parking_id,
            result=result,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )
    )


def record_audit_from_request(
    request: Request,
    db: Session,
    *,
    action: str,
    resource: str | None = None,
    payload: dict[str, Any] | None = None,
    confidence: float | None = None,
    parking_id: int | None = None,
    result: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Helper que extrae user_id/ip/correlation_id de ``request.state.audit``."""
    audit = getattr(request.state, "audit", None) or {}
    record_audit(
        db,
        action=action,
        user_id=audit.get("user_id"),
        ip=audit.get("ip"),
        resource=resource,
        payload=payload,
        confidence=confidence,
        parking_id=parking_id,
        result=result,
        duration_ms=duration_ms,
        correlation_id=audit.get("correlation_id"),
    )


__all__ = ["record_audit", "record_audit_from_request"]