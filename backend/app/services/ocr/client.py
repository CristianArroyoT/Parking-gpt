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

T-177 (2026-10-24): `recognize()` devuelve una lista **vacía** en dos
situaciones que no son lo mismo: el servicio **no dio una respuesta
utilizable** (red caída, timeout, 4xx/5xx) y el servicio **respondió y
no leyó nada**. La primera no dice nada de la cámara (es un problema del
servicio) y la segunda sí (es un problema de la cámara).
`reconocer()` devuelve las dos cosas separadas
(`OcrResultado.respondio`), que es lo que usa `ping_camera` para no
culpar a 51 cámaras de un servicio caído.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.plate import PlateHit

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrResultado:
    """Resultado de un reconocimiento, con **el motivo** del vacío.

    - `hits`: las matrículas leídas (puede estar vacía).
    - `respondio`: ``True`` si el servicio OCR dio una **respuesta
      utilizable** (HTTP 200 con una lista). ``False`` si no la dio: no
      se pudo hablar con él (timeout, error de red), contestó con un
      error (4xx/5xx) o devolvió algo que no es una lista. Un 4xx cuenta
      como «no utilizable» (y no como «leyó y no vio nada») porque el
      servicio **contestó**: el problema es del servicio o de la
      imagen, no de la cámara.
    - `motivo`: por qué (``no_disponible``, ``status_400``, ``no_json``,
      ``formato``, ``sin_lecturas``…); "" si hubo lecturas.
    """

    hits: list[PlateHit] = field(default_factory=list)
    respondio: bool = False
    motivo: str = ""


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
            return bool(r.json().get("status") == "ok")
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

        OJO (T-177): una lista vacía **no** dice si el servicio falló o
        si no leyó nada. Para eso está `reconocer()`.
        """
        resultado = await self.reconocer(
            image_bytes, filename=filename, content_type=content_type
        )
        return resultado.hits

    async def reconocer(
        self,
        image_bytes: bytes,
        *,
        filename: str = "frame.jpg",
        content_type: str = "image/jpeg",
    ) -> OcrResultado:
        """Como `recognize()`, pero **distingue el motivo del vacío**.

        - El servicio **respondió** con una lista (aunque vacía) →
          `respondio=True`. Esto dice algo de la imagen (y de la cámara).
        - El servicio **no dio una respuesta utilizable** (timeout, red,
          4xx/5xx, no JSON, no es una lista) → `respondio=False` y
          `motivo` explica por qué. Esto **no** dice nada de la cámara:
          no es culpa suya.

        NUNCA lanza excepción.
        """
        try:
            async with self._client() as client:
                files = {"image": (filename, image_bytes, content_type)}
                r = await client.post(
                    f"{self._base_url}/recognize", files=files
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            log.warning("OCR recognize: servicio no disponible: %s", exc)
            return OcrResultado(hits=[], respondio=False, motivo="no_disponible")
        except Exception as exc:  # noqa: BLE001
            log.exception("OCR recognize: error inesperado: %s", exc)
            return OcrResultado(hits=[], respondio=False, motivo="error")

        if r.status_code != 200:
            log.warning(
                "OCR recognize: status=%s body=%s",
                r.status_code,
                r.text[:200],
            )
            return OcrResultado(
                hits=[], respondio=False, motivo=f"status_{r.status_code}"
            )

        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR recognize: respuesta no JSON: %s", exc)
            return OcrResultado(hits=[], respondio=False, motivo="no_json")

        if not isinstance(data, list):
            log.warning(
                "OCR recognize: respuesta inesperada (no es lista): %r",
                type(data).__name__,
            )
            return OcrResultado(hits=[], respondio=False, motivo="formato")

        hits: list[PlateHit] = []
        for item in data:
            try:
                hits.append(PlateHit.model_validate(item))
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR recognize: hit inválido, se descarta: %s", exc)
        if not hits:
            return OcrResultado(hits=[], respondio=True, motivo="sin_lecturas")
        return OcrResultado(hits=hits, respondio=True, motivo="")


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


__all__ = ["OcrClient", "OcrResultado", "PlateHit", "get_ocr_client", "reset_ocr_client"]