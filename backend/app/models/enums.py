"""Enumeraciones del dominio: roles, estados, tipos."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    GESTOR = "gestor"
    OPERADOR = "operador"
    CLIENTE = "cliente"


class TicketStatus(str, enum.Enum):
    ACTIVO = "activo"
    CERRADO = "cerrado"
    ANULADO = "anulado"


class VehicleRole(str, enum.Enum):
    PROPIETARIO = "propietario"
    CONDUCTOR = "conductor"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class AlertType(str, enum.Enum):
    OCR_FAILED = "ocr_failed"
    CAMERA_OFFLINE = "camera_offline"
    SPACE_EMPTY_TOO_LONG = "space_empty_too_long"
    ROBERY_REPORTED = "robery_reported"
    SPACE_BROKEN = "space_broken"
    OTHER = "other"


class ManualEntryReason(str, enum.Enum):
    """Motivo declarado por el operador al hacer un alta manual.

    Distinto semánticamente de ``AlertType``: aquí clasifica la ACCIÓN del
    operador, mientras que ``AlertType`` notifica INCIDENCIAS del sistema.
    """

    CAMERA_DOWN = "camera_down"
    OCR_FAILED = "ocr_failed"
    OTHER = "other"


class TicketOrigin(str, enum.Enum):
    """Origen del ticket. ``AUTOMATIC`` para OCR; ``MANUAL_ENTRY/EXIT`` para
    alta manual del operador."""

    AUTOMATIC = "automatic"
    MANUAL_ENTRY = "manual_entry"
    MANUAL_EXIT = "manual_exit"