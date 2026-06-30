"""Servicios de dominio. En Fase 1 sólo auditoría y seeding."""

from __future__ import annotations

from typing import Any

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
) -> None:
    """Inserta un registro en audit_logs sin commit (lo hace el caller)."""
    db.add(
        AuditLog(
            user_id=user_id,
            ip=ip,
            action=action,
            resource=resource,
            payload=payload,
            confidence=confidence,
        )
    )