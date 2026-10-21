"""Cliente async contra el servicio vehicle-detector (YOLO en ``vehicle-detector:8800``).

Réplica exacta del patrón de ``app.services.ocr.client``:
- Timeout corto configurable (8 s por defecto: YOLO en CPU tarda ~300-500 ms
  por imagen 960x540, pero el primer request sufre warm-up de ~2 s).
- NUNCA lanza excepción — devuelve ``[]`` ante timeout/JSON inválido/404.
  La app prefiere un "no detecté nada" a un 500 cuando el detector está caído.
- ``health()`` devuelve bool (True si ``status=='ok'``, False en cualquier error).
- Singleton lazy + ``reset_vehicle_detector_client()`` para tests con MockTransport.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.vehicle_detection import VehicleDetection

log = logging.getLogger(__name__)


class VehicleDetectorClient:
    """Cliente HTTP fino contra el servicio YOLO separado."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self._base_url = (base_url or s.vehicle_detector_url).rstrip("/")
        self._timeout = (
            timeout if timeout is not None else s.vehicle_detector_timeout
        )
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def health(self) -> bool:
        try:
            async with self._client() as client:
                r = await client.get(f"{self._base_url}/health")
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("vehicle-detector health: servicio no disponible: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.exception("vehicle-detector health: error inesperado: %s", exc)
            return False
        if r.status_code != 200:
            return False
        try:
            return bool(r.json().get("status") == "ok")
        except Exception:  # noqa: BLE001
            return False

    async def detect(
        self,
        image_bytes: bytes,
        *,
        filename: str = "captured.jpg",
        content_type: str = "image/jpeg",
    ) -> list[VehicleDetection]:
        """Envía un frame al servicio YOLO. Devuelve [] si algo falla.

        NUNCA lanza excepción. La promesa es: o devuelve las detecciones, o
        devuelve lista vacía. El caller decide qué hacer con el vacío
        (toast "No se detectaron vehículos", por ejemplo).
        """
        try:
            async with self._client() as client:
                files = {"image": (filename, image_bytes, content_type)}
                r = await client.post(
                    f"{self._base_url}/detect", files=files
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("vehicle-detector detect: servicio no disponible: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            log.exception("vehicle-detector detect: error inesperado: %s", exc)
            return []

        if r.status_code != 200:
            log.warning(
                "vehicle-detector detect: status=%s body=%s",
                r.status_code,
                r.text[:200],
            )
            return []

        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("vehicle-detector detect: respuesta no JSON: %s", exc)
            return []

        if not isinstance(data, list):
            log.warning(
                "vehicle-detector detect: respuesta inesperada (no es lista): %r",
                type(data).__name__,
            )
            return []

        detections: list[VehicleDetection] = []
        for item in data:
            try:
                detections.append(VehicleDetection.model_validate(item))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "vehicle-detector detect: detección inválida, se descarta: %s",
                    exc,
                )
        return detections


_default_client: VehicleDetectorClient | None = None


def get_vehicle_detector_client() -> VehicleDetectorClient:
    """Singleton perezoso: se crea en la primera llamada.

    Para tests que necesitan un cliente con MockTransport, instanciar
    directamente ``VehicleDetectorClient(transport=...)``.
    """
    global _default_client
    if _default_client is None:
        _default_client = VehicleDetectorClient()
    return _default_client


def reset_vehicle_detector_client() -> None:
    """Borra el singleton (útil en tests que cambian VEHICLE_DETECTOR_URL)."""
    global _default_client
    _default_client = None


__all__ = [
    "VehicleDetectorClient",
    "VehicleDetection",
    "get_vehicle_detector_client",
    "reset_vehicle_detector_client",
]