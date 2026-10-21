"""Regresión del apagado del stream SSE (T-06+1 del plan de pendientes).

El stream ``GET /api/v1/parkings/{parking_id}/events`` mantiene una conexión
HTTP abierta **para siempre** (es un SSE). Antes de este arreglo su
generador miraba únicamente el mensaje de Redis: no comprobaba ningún
evento de apagado, así que una conexión SSE abierta bloqueaba el apagado
de uvicorn exactamente igual que lo hacía el preview MJPEG (bug T-06).

Consecuencia medida: uvicorn se quedaba en "Waiting for connections to
close" y, como el reloader hace ``process.join()`` antes de arrancar el
proceso hijo, el backend entero dejaba de servir (``/health`` → 000)
hasta un ``docker restart``.

El arreglo: ``app.state.shutdown_event`` (creado en el ``lifespan``) lo
activa el hook de señales de ``app.main`` — la única pista de apagado que
llega ANTES de que uvicorn espere a las conexiones abiertas — y el
generador SSE lo comprueba en cada vuelta.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import _login, _seed_admin, _seed_parking


def test_la_app_expone_el_evento_de_apagado(client: TestClient) -> None:
    """Tras el startup, la app tiene un evento de apagado SIN marcar."""
    evento = getattr(client.app.state, "shutdown_event", None)
    assert evento is not None, (
        "app.state.shutdown_event no existe: los streams SSE no podrían "
        "cerrarse al apagar el servidor"
    )
    assert not evento.is_set()


def test_sse_termina_al_marcar_el_apagado(
    client: TestClient, db_session: Session
) -> None:
    """Con el evento marcado, el stream SSE termina en menos de 5 s."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-SSE-SHUT")
    token = _login(client, admin.email, "admin12345")

    async def _escenario() -> tuple[float, list[bytes]]:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            url = f"/api/v1/parkings/{parking.id}/events"
            headers = {"Authorization": f"Bearer {token}"}
            recibidos: list[bytes] = []

            async def _leer() -> None:
                async with ac.stream("GET", url, headers=headers) as resp:
                    assert resp.status_code == 200
                    assert "text/event-stream" in resp.headers.get(
                        "content-type", ""
                    )
                    async for chunk in resp.aiter_bytes():
                        recibidos.append(chunk)

            t0 = time.perf_counter()
            tarea = asyncio.create_task(_leer())
            # Damos tiempo a que el stream se abra y se quede esperando.
            await asyncio.sleep(0.5)
            # Esto es lo que hace el hook de señales al apagar el servidor.
            client.app.state.shutdown_event.set()
            # El stream debe terminar por sí solo (sin cancelar la tarea).
            await asyncio.wait_for(tarea, timeout=5)
            return time.perf_counter() - t0, recibidos

    duracion, recibidos = asyncio.run(_escenario())

    assert duracion < 5.0, (
        f"el stream SSE tardó {duracion:.1f} s en cerrarse tras el apagado"
    )
    assert recibidos, "el stream no llegó a emitir nada"
    assert b"event: ping" in b"".join(recibidos), (
        "el stream no llegó a enviar el evento inicial"
    )


def test_sse_no_termina_sin_apagado(
    client: TestClient, db_session: Session
) -> None:
    """Sin evento de apagado, el stream sigue abierto (no se cierra solo)."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-SSE-ABIERTO")
    token = _login(client, admin.email, "admin12345")

    async def _escenario() -> bool:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            url = f"/api/v1/parkings/{parking.id}/events"
            headers = {"Authorization": f"Bearer {token}"}

            async def _leer() -> None:
                async with ac.stream("GET", url, headers=headers) as resp:
                    async for _chunk in resp.aiter_bytes():
                        pass

            tarea = asyncio.create_task(_leer())
            await asyncio.sleep(1.0)
            terminada = tarea.done()
            tarea.cancel()
            try:
                await tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            return terminada

    terminada = asyncio.run(_escenario())
    assert not terminada, (
        "el stream SSE se cerró solo sin que se marcara el apagado: "
        "se ha roto la permanencia del stream"
    )


@pytest.mark.parametrize("ruta", ["/api/v1/parkings/1/events"])
def test_el_endpoint_sse_sigue_requiriendo_autenticacion(
    client: TestClient, ruta: str
) -> None:
    """Sin token, el SSE sigue devolviendo 401 (no se afloja nada)."""
    r = client.get(ruta)
    assert r.status_code == 401


def test_sse_acepta_el_token_por_query_param(
    client: TestClient, db_session: Session
) -> None:
    """``?token=`` debe funcionar: el endpoint lo anunciaba y daba 401.

    El dep ``parking_context`` global exige cabecera ``Authorization:
    Bearer``, así que combinándolo con ``get_current_user_or_query_token``
    el ``?token=`` se aceptaba en una dependencia y se rechazaba en la
    otra. Ahora el SSE usa el mismo patrón opt-in por endpoint que el
    preview MJPEG: query token + ``enforce_parking_membership``.
    """
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-SSE-QS")
    token = _login(client, admin.email, "admin12345")

    async def _escenario() -> int:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            url = f"/api/v1/parkings/{parking.id}/events?token={token}"
            estado: dict[str, int] = {}

            async def _leer() -> None:
                async with ac.stream("GET", url) as resp:
                    estado["status"] = resp.status_code
                    estado["content_type"] = resp.headers.get("content-type", "")
                    async for _chunk in resp.aiter_bytes():
                        pass

            # OJO: bajo ``ASGITransport`` las cabeceras de respuesta no
            # llegan hasta que el cuerpo termina, así que hay que marcar el
            # apagado desde una tarea concurrente: si se espera a que
            # llegue la respuesta antes de marcarlo, el generador nunca
            # termina y la petición se queda colgada.
            tarea = asyncio.create_task(_leer())
            await asyncio.sleep(0.5)
            client.app.state.shutdown_event.set()
            await asyncio.wait_for(tarea, timeout=5)
            return estado.get("status", 0)

    codigo = asyncio.run(_escenario())
    assert codigo == 200


def test_sse_con_query_param_invalido_devuelve_401(
    client: TestClient, db_session: Session
) -> None:
    """Un ``?token=`` inválido no abre el stream."""
    parking = _seed_parking(db_session, code="P-SSE-QS-MALO")
    r = client.get(f"/api/v1/parkings/{parking.id}/events?token=no-es-un-jwt")
    assert r.status_code == 401
