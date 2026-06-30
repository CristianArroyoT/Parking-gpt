"""Creación de incidentes: marcar plaza averiada / reportar robo / rehabilitar.

Un incidente ES un ``Alert`` con ``type ∈ {SPACE_BROKEN, ROBERY_REPORTED}``
y ``context.kind`` discrimina entre avería/rehabilitación. Esto evita una
tabla paralela y reusa el pipeline de email + audit + acknowledge existente.

Reglas:

- ``space_broken`` / ``space_unbroken``: requieren ``parking_space_id``;
  marcan/limpian ``space.is_broken`` + ``is_broken_at``. Idempotente: si
  ya está en el estado deseado, devuelve sin Alert nuevo.
- ``robery_reported``: todos los campos opcionales (matrícula, plaza,
  fotos). El operador en vivo rara vez conoce la matrícula; el reporte
  debe poder ser "vi un robo, no pude ver la placa".

Email sólo para ``ROBERY_REPORTED`` (CRITICAL). ``SPACE_BROKEN`` /
``SPACE_UNBROKEN`` sólo Alert en BD + audit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.db import SessionLocal
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Parking, ParkingSpace
from app.models.user import User
from app.schemas.audit import IncidentCreate, IncidentKind
from app.services import email as email_module
from app.services import record_audit
from app.services.alerts import _resolve_manager_email

log = logging.getLogger(__name__)


def _normalize_plate(raw: str | None) -> str | None:
    if not raw:
        return None
    norm = "".join(ch for ch in raw.upper() if ch.isalnum())
    return norm or None


def _alert_type_for(kind: IncidentKind) -> AlertType:
    return (
        AlertType.ROBERY_REPORTED
        if kind == IncidentKind.ROBERY_REPORTED
        else AlertType.SPACE_BROKEN
    )


def create_incident(
    payload: IncidentCreate,
    *,
    parking_id: int,
    current_user: User,
    ip: str | None = None,
) -> Alert | None:
    """Crea el incidente. Devuelve la ``Alert`` o ``None`` si idempotente no-op."""
    kind = payload.kind
    reason_value = (
        payload.reason.value
        if hasattr(payload.reason, "value")
        else str(payload.reason)
    )

    with SessionLocal() as db:
        space: ParkingSpace | None = None
        if kind in (IncidentKind.SPACE_BROKEN, IncidentKind.SPACE_UNBROKEN):
            if payload.parking_space_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"kind={kind.value} requiere parking_space_id",
                )
            space = db.get(ParkingSpace, payload.parking_space_id)
            if space is None or space.parking_id != parking_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="La plaza no pertenece a la sucursal indicada",
                )

        # Idempotencia
        if kind == IncidentKind.SPACE_BROKEN and space is not None and space.is_broken:
            record_audit(
                db,
                action="incident_space_broken_noop",
                user_id=current_user.id,
                ip=ip,
                resource=f"space:{space.id}",
                payload={"reason": "already broken"},
            )
            db.commit()
            return None
        if kind == IncidentKind.SPACE_UNBROKEN and space is not None and not space.is_broken:
            record_audit(
                db,
                action="incident_space_unbroken_noop",
                user_id=current_user.id,
                ip=ip,
                resource=f"space:{space.id}",
                payload={"reason": "already healthy"},
            )
            db.commit()
            return None

        now = datetime.now(timezone.utc)
        context: dict = {
            "kind": kind.value,
            "reason": reason_value,
            "notes": payload.notes,
        }

        if kind in (IncidentKind.SPACE_BROKEN, IncidentKind.SPACE_UNBROKEN):
            assert space is not None
            target_state = kind == IncidentKind.SPACE_BROKEN
            space.is_broken = target_state
            space.is_broken_at = now if target_state else None
            context.update({
                "parking_space_id": space.id,
                "lane": space.lane,
                "number": space.number,
            })
            message = (
                f"Plaza {space.lane}-{space.number} "
                f"{'marcada como averiada' if target_state else 'rehabilitada'}"
            )
            severity = AlertSeverity.WARN
        else:  # ROBERY_REPORTED
            context["plate"] = _normalize_plate(payload.plate)
            context["parking_space_id"] = payload.parking_space_id
            context["photos"] = payload.photos
            context["reported_by"] = current_user.email
            message = f"Reporte de robo ({reason_value}) — operador {current_user.email}"
            severity = AlertSeverity.CRITICAL

        alert = Alert(
            parking_id=parking_id,
            type=_alert_type_for(kind),
            severity=severity,
            message=message,
            context=context,
        )
        db.add(alert)
        db.flush()

        record_audit(
            db,
            action=f"incident_{kind.value}",
            user_id=current_user.id,
            ip=ip,
            resource=f"alert:{alert.id}",
            payload={
                "alert_id": alert.id,
                "alert_type": alert.type.value,
                "severity": alert.severity.value,
                "context": context,
            },
        )
        db.commit()
        db.refresh(alert)

        log.warning(
            "incidents: %s alert_id=%s parking_id=%s user_id=%s",
            kind.value, alert.id, parking_id, current_user.id,
        )

        if kind == IncidentKind.ROBERY_REPORTED:
            try:
                park = db.get(Parking, parking_id)
                parking_name = park.name if park else f"parking-{parking_id}"
                manager_email = _resolve_manager_email(db, parking_id)
                email_module.send_alert_email(
                    alert,
                    manager_email,
                    template_kind="robery_reported",
                    parking_name=parking_name,
                )
            except Exception as exc:  # noqa: BLE001 — defensiva
                log.warning(
                    "incidents: fallo enviando email de robo alert=%s: %s",
                    alert.id, exc,
                )

        return alert


__all__ = ["create_incident"]