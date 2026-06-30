"""Cliente async contra el servicio OCR separado (PaddleOCR en `ocr:8800`).

Reglas:
- Timeout corto (4 s por defecto). Si el servicio no responde, el cliente
  devuelve `[]` — NUNCA propaga la excepción al caller. La app prefiere
  un "no sé" a un 500 cuando OCR está caído.
- `health()` devuelve bool (True si status=='ok', False en cualquier error).
- `PlateHit` se reexporta desde schemas para mantener un único modelo
  compartido entre cliente, API y worker.
- El cliente se construye por defecto leyendo `OCR_SERVICE_URL` y
  `OCR_SERVICE_TIMEOUT` desde Settings. Los tests inyectan un
  `httpx.MockTransport` vía el kwarg `transport=`.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.plate import PlateHit

log = logging.getLogger(__name__)


class OcrClient:
    """Cliente HTTP fino contra el servicio OCR."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self._base_url = (base_url or s.ocr_service_url).rstrip("/")
        self._timeout = timeout if timeout is not None else s.ocr_service_timeout
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
            log.warning("OCR health: servicio no disponible: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.exception("OCR health: error inesperado: %s", exc)
            return False
        if r.status_code != 200:
            return False
        try:
            return r.json().get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False

    async def recognize(
        self,
        image_bytes: bytes,
        *,
        filename: str = "frame.jpg",
        content_type: str = "image/jpeg",
    ) -> list[PlateHit]:
        """Envía un frame al servicio OCR. Devuelve [] si algo falla.

        NUNCA lanza excepción. La promesa es: o devuelve los hits, o
        devuelve lista vacía. El caller decide qué hacer con el vacío
        (alertar, loguear, etc.).
        """
        try:
            async with self._client() as client:
                files = {"image": (filename, image_bytes, content_type)}
                r = await client.post(
                    f"{self._base_url}/recognize", files=files
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("OCR recognize: servicio no disponible: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            log.exception("OCR recognize: error inesperado: %s", exc)
            return []

        if r.status_code != 200:
            log.warning(
                "OCR recognize: status=%s body=%s",
                r.status_code,
                r.text[:200],
            )
            return []

        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR recognize: respuesta no JSON: %s", exc)
            return []

        if not isinstance(data, list):
            log.warning(
                "OCR recognize: respuesta inesperada (no es lista): %r",
                type(data).__name__,
            )
            return []

        hits: list[PlateHit] = []
        for item in data:
            try:
                hits.append(PlateHit.model_validate(item))
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR recognize: hit inválido, se descarta: %s", exc)
        return hits


_default_client: OcrClient | None = None


def get_ocr_client() -> OcrClient:
    """Singleton perezoso: se crea en la primera llamada.

    Para tests que necesitan un cliente con MockTransport, instanciar
    directamente `OcrClient(transport=...)`.
    """
    global _default_client
    if _default_client is None:
        _default_client = OcrClient()
    return _default_client


def reset_ocr_client() -> None:
    """Borra el singleton (útil en tests que cambian OCR_SERVICE_URL)."""
    global _default_client
    _default_client = None


__all__ = ["OcrClient", "PlateHit", "get_ocr_client", "reset_ocr_client"]