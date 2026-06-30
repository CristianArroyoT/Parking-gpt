"""Tests del cliente OCR: timeout, JSON inválido, respuesta correcta.

Ejecutamos las corutinas con `asyncio.run` directamente para no
añadir pytest-asyncio como dependencia obligatoria del contenedor.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ocr.client import OcrClient


def _make_client(handler) -> OcrClient:
    """Crea un OcrClient que NO habla con la red: usa MockTransport."""
    return OcrClient(
        base_url="http://test-ocr",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
    )


def _run(coro):
    """Helper: ejecuta una coroutina en un event loop desde un test sync."""
    return asyncio.run(coro)


def test_recognize_empty_list_when_service_returns_empty() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    hits = _run(client.recognize(b"\xff\xd8\xff\xe0fake-jpeg-bytes"))
    assert hits == []


def test_recognize_returns_empty_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=_request)

    client = _make_client(handler)
    # Importante: NO debe propagar la excepción.
    hits = _run(client.recognize(b"frame"))
    assert hits == []


def test_recognize_parses_one_hit_correctly() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # El cliente envía multipart/form-data con campo 'image'.
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["has_body"] = bool(request.content)
        return httpx.Response(
            200,
            json=[
                {
                    "plate": "1234ABC",
                    "confidence": 0.97,
                    "bbox": [10, 20, 110, 60],
                }
            ],
        )

    client = _make_client(handler)
    hits = _run(client.recognize(b"\xff\xd8\xff\xe0fake"))

    assert captured["method"] == "POST"
    assert captured["path"] == "/recognize"
    assert captured["has_body"] is True

    assert len(hits) == 1
    assert hits[0].plate == "1234ABC"
    assert hits[0].confidence == pytest.approx(0.97)
    assert hits[0].bbox == [10, 20, 110, 60]


def test_recognize_returns_empty_on_non_200() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="OCR engine loading")

    client = _make_client(handler)
    hits = _run(client.recognize(b"frame"))
    assert hits == []


def test_recognize_skips_malformed_hits() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                # válido
                {"plate": "AAAA", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
                # confidence fuera de rango → descartado por Pydantic
                {"plate": "BBBB", "confidence": 1.5, "bbox": [0, 0, 1, 1]},
                # bbox de tamaño incorrecto → descartado
                {"plate": "CCCC", "confidence": 0.5, "bbox": [0, 0]},
            ],
        )

    client = _make_client(handler)
    hits = _run(client.recognize(b"frame"))
    assert len(hits) == 1
    assert hits[0].plate == "AAAA"


def test_health_true_when_status_ok() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "ok", "engine": "paddle", "models_loaded": True},
        )

    client = _make_client(handler)
    assert _run(client.health()) is True


def test_health_false_when_status_degraded() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "degraded", "engine": "paddle"},
        )

    client = _make_client(handler)
    assert _run(client.health()) is False