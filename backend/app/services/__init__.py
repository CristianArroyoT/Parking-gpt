"""Servicios de dominio. Back-compat para Fase 1/2 (sprint Fase 3A migró
a ``app.services.audit`` con API extendida)."""

from __future__ import annotations

from app.services.audit import record_audit

__all__ = ["record_audit"]