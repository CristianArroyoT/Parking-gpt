"""Servicios de auditoría operativa (sprint Fase 3A, 2026-07-01).

API principal:
  - ``record_audit``: escribe en ``audit_logs``. NO hace commit (el
    caller decide, igual que el legacy de Fase 1).
  - ``record_audit_from_request``: helper que lee el contexto del
    ``AuditMiddleware`` (request.state.audit) y llama a ``record_audit``.
  - ``record_audit_worker`` (Fase 3B): variante para workers Celery que
    no tienen ``Request``. Genera correlation_id propio, fija
    ``user_id=None`` y ``ip="worker"``.

Back-compat: ``app.services.__init__.record_audit`` re-exporta esta
función para no romper los 4 callers de Fase 1/2 (``incidents.py``,
``manual_tickets.py``).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

log = logging.getLogger(__name__)


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
    """Helper que extrae user_id/ip/correlation_id de ``request.state.audit``.

    Sprint O1 (2026-07-06): además de persistir en ``audit_logs``, emite
    un ``log.info(...)`` con ``extra={"action", "result", "user_id", ...}``
    para que Promtail/Loki reciba el evento y los dashboards Grafana
    puedan graficarlo. NO loggeamos el ``payload`` (puede contener
    emails/IPs — corre por canal separado en la fila de ``audit_logs``).
    """
    audit = getattr(request.state, "audit", None) or {}
    user_id_value = audit.get("user_id")
    ip_value = audit.get("ip")
    correlation_id_value = audit.get("correlation_id")

    record_audit(
        db,
        action=action,
        user_id=user_id_value,
        ip=ip_value,
        resource=resource,
        payload=payload,
        confidence=confidence,
        parking_id=parking_id,
        result=result,
        duration_ms=duration_ms,
        correlation_id=correlation_id_value,
    )

    # Telemetría para Loki/Grafana (Sprint O1). Misma correlation_id que
    # el audit_log permite cruzar ambos canales. Si el logger no tiene
    # handler configurado (tests con PYTEST_CURRENT_TEST), se ignora.
    try:
        log.info(
            "audit event",
            extra={
                "event": "audit",
                "action": action,
                "result": result,
                "user_id": user_id_value,
                "resource": resource,
                "parking_id": parking_id,
                "correlation_id": correlation_id_value,
            },
        )
    except Exception:  # pragma: no cover - logging nunca debe romper audit
        pass


def record_audit_worker(
    db: Session,
    *,
    action: str,
    parking_id: int | None = None,
    resource: str | None = None,
    payload: dict[str, Any] | None = None,
    result: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Variante para workers Celery (sin Request HTTP).

    Fija ``user_id=None`` y ``ip="worker"``. Si no se pasa
    ``correlation_id`` se genera un UUID hex de 36 chars (uno por
    invocación del worker).

    NO hace commit — el caller decide, igual que el resto.
    """
    record_audit(
        db,
        action=action,
        user_id=None,
        ip="worker",
        resource=resource,
        payload=payload,
        parking_id=parking_id,
        result=result,
        correlation_id=correlation_id or uuid.uuid4().hex + uuid.uuid4().hex[:4],
    )


__all__ = [
    "record_audit",
    "record_audit_from_request",
    "record_audit_worker",
    "make_worker_correlation_id",
]


def make_worker_correlation_id() -> str:
    """Genera correlation_id de 36 chars hex para una invocación de task.

    Sprint Fase 3C (2026-07-01). Cada invocación de una task Celery
    (``ping_camera``, ``probe_heartbeats``, etc.) genera UN solo
    correlation_id al inicio y lo pasa explícito a TODOS los
    ``record_audit_worker(correlation_id=cid)`` Y a todos los
    ``log.warning/info(extra={"correlation_id": cid, ...})`` de esa
    invocación. Esto da correlación real con Loki, no sólo con
    ``audit_logs``.

    UUID v4 hex mide 32 chars; añadimos 4 chars hex adicionales de otro
    UUID para llegar exactamente a 36 (límite del String(36) de la
    columna ``audit_logs.correlation_id``). Formato compatible con el
    header ``X-Request-ID`` que el middleware HTTP ya emite.
    """
    return uuid.uuid4().hex + uuid.uuid4().hex[:4]