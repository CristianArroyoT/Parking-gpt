"""Servicios de dominio. Back-compat para Fase 1/2 (sprint Fase 3A migró
a ``app.services.audit`` con API extendida)."""

from __future__ import annotations

from app.services.audit import (
    make_worker_correlation_id,
    record_audit,
    record_audit_from_request,
    record_audit_worker,
)

__all__ = [
    "record_audit",
    "record_audit_from_request",
    "record_audit_worker",
    "make_worker_correlation_id",
]