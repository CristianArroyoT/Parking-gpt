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


class GeofenceDirection(str, enum.Enum):
    """Dirección de la geocerca: si la cámara procesa esta plaza como
    entrada o salida. Permite separar físicamente las cámaras cuando se
    decida el fabricante."""

    ENTRY = "entry"
    EXIT = "exit"


class CameraKind(str, enum.Enum):
    """Tipo de cámara en la sucursal.

    ``SURVEILLANCE``: cámaras de fiscalización que observan el parking
    continuamente y disparan ingestas por OCR cuando un vehículo entra
    o sale del frame. Es el comportamiento por defecto.

    ``GATE``: cámaras de "portería" dedicadas a una única transacción
    (entrada o salida) en barrera. El operador las usa para emitir
    tickets manualmente desde el stream RTSP cuando el OCR falla.

    Sprint Fase 4 (2026-07-01): introduce esta distinción para que la UI
    pueda filtrar/segmentar cámaras según rol, y para que un futuro
    worker pueda aplicar heurísticas distintas por kind.
    """

    SURVEILLANCE = "surveillance"
    GATE = "gate"