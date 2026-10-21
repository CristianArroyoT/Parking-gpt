"""Bus de eventos efímero sobre Redis pub/sub.

Sprint O2 (2026-07-06): empuja eventos del backend al frontend (MapView)
con latencia <1 s sin polling. Reemplaza el ``setInterval(tick, 5000)``
de MapView por un stream SSE que se nutre de este bus.

Diseño:

- **Un canal por sucursal** (``parking:{id}:events``) para que los
  suscriptores sólo reciban eventos de su parking. Multiplexación
  via ``type`` en el payload.
- **Publicador defensivo**: si Redis cae, loguea y sigue — la BD es la
  fuente de verdad y los clientes caerán al ``setInterval(30s)`` de
  respaldo en MapView.
- **Cliente sync** porque los hooks están en código sync (handlers
  HTTP, services). El subscriber async vive en ``redis_async.py``.

Tipos de evento (extensibles sin migración):

- ``ticket_created``: plaza pasa de LIBRE a OCUPADA.
- ``ticket_closed``: plaza pasa de OCUPADA a LIBRE.
- ``ticket_cancelled``: ticket cancelado por admin/gestor.
- ``space_broken_changed``: plaza averiada/rehabilitada.
- ``camera_health_changed``: cámara subió/bajó su ``last_heartbeat_ok``.

Formato del payload publicado::

    {"type": "ticket_created", "payload": {...}, "ts": "2026-07-06T10:11:12Z"}
"""
from __future__ import annotations

from typing import Any
import json
import logging
from datetime import datetime, timezone

import redis

from app.core.config import get_settings

log = logging.getLogger(__name__)


class EventType:
    """Tipos de evento publicados en el bus. Constantes."""

    TICKET_CREATED = "ticket_created"
    TICKET_CLOSED = "ticket_closed"
    TICKET_CANCELLED = "ticket_cancelled"
    SPACE_BROKEN_CHANGED = "space_broken_changed"
    CAMERA_HEALTH_CHANGED = "camera_health_changed"


def channel_for_parking(parking_id: int) -> str:
    """Nombre del canal Redis para una sucursal concreta."""
    return f"parking:{parking_id}:events"


def publish(parking_id: int, event_type: str, payload: dict[str, Any]) -> None:
    """Publica un evento en el canal ``parking:{id}:events``.

    Fire-and-forget: cualquier excepción (Redis caído, timeout, JSON
    no serializable) se loguea y se traga. Esto es crítico: los hooks
    se llaman en ``ingest_service``, ``manual_tickets``,
    ``incidents``, ``workers/tasks`` y un fallo de Redis NO debe
    tumbar la transacción principal ni el flujo OCR.

    Devuelve ``None`` siempre (no propagable).
    """
    try:
        s = get_settings()
        r = redis.Redis.from_url(s.redis_url, decode_responses=True)
        body = json.dumps(
            {
                "type": event_type,
                "payload": payload,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        )
        r.publish(channel_for_parking(parking_id), body)
    except Exception as exc:  # noqa: BLE001 — defensiva por contrato
        log.warning(
            "event_bus: publish falló parking=%s event=%s: %s",
            parking_id,
            event_type,
            exc,
        )


__all__ = ["EventType", "channel_for_parking", "publish"]