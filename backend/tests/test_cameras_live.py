"""Tests del endpoint GET /parkings/{id}/cameras/{cid}/live.

API bajo test: ``GET /api/v1/parkings/{parking_id}/cameras/{camera_id}/live``
(registrado en Sprint Live-Preview 2026-07-07). Consume el stream MJPEG
que pinta el modal "Ver en vivo" de ``CalibrateView.vue``.

Cubre:

  1. Sin token (ni header ni query) → 401.
  2. Token por query param válido → 200 con
     ``Content-Type: multipart/x-mixed-replace; boundary=frame`` y primer
     chunk empezando por ``--frame``.
  3. Cámara que no pertenece al ``parking_id`` del path → 404.
  4. Si ya hay un stream activo para la cámara → 409.
  5. Tras ``release``, el siguiente cliente puede reservar el slot.

El generador ``mjpeg_generator`` NO abre un RTSP real (la URL
``rtsp://demo.invalid/x`` no responde); por eso en 4 y 5 manipulamos
el registry directamente con ``try_acquire`` / ``release`` en vez de
intentar dos streams HTTP simultáneos (que sería flaky y bloquearía
los 5 s del timeout en serie).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.parking import Camera
from app.services.cameras.live_streams import live_streams
from tests._audit_helpers import (
    _login,
    _login_headers,
    _seed_admin,
    _seed_gestor,
    _seed_parking,
)


def _seed_camera(db: Session, parking_id: int, code: str = "CAM-LIVE") -> Camera:
    cam = Camera(
        parking_id=parking_id, code=code,
        name=f"Cámara {code}", rtsp_url="rtsp://demo.invalid/x", fps=10,
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


@pytest.fixture(autouse=True)
def _cleanup_live_registry():
    """Vacía el ``LiveStreamRegistry`` entre tests para que la prueba
    409 no contamine a las siguientes."""
    yield
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    for cam_id in list(live_streams._active.keys()):  # noqa: SLF001
        loop.run_until_complete(live_streams.release(cam_id))


def test_live_requires_auth(
    client: TestClient, db_session: Session,
) -> None:
    """Sin Authorization ni query token → 401."""
    parking = _seed_parking(db_session, code="P-LIVE-401")
    _seed_camera(db_session, parking.id, code="CAM-LIVE-401")

    r = client.get(f"/api/v1/parkings/{parking.id}/cameras/1/live")
    assert r.status_code == 401


def test_live_query_token_returns_multipart(
    client: TestClient, db_session: Session,
) -> None:
    """Auth por ``Authorization: Bearer`` → 200 + content-type MJPEG + primer
    chunk válido. Si RTSP no abre (esperado en tests), el primer chunk es
    igualmente un ``--frame`` con placeholder JPEG.

    Nota: el endpoint también acepta ``?token=...`` (patrón del SSE Sprint O2
    para ``EventSource`` del navegador); ese path lo cubre test_live_query_token_supported.
    Aquí usamos Bearer porque TestClient enruta el header correctamente y
    TestClient.stream no soporta ``params=``.
    """
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-LIVE-OK")
    _seed_camera(db_session, parking.id, code="CAM-LIVE-OK")
    headers = _login_headers(client, admin.email, "admin12345")

    with client.stream(
        "GET",
        f"/api/v1/parkings/{parking.id}/cameras/1/live",
        headers=headers,
    ) as r:
        assert r.status_code == 200, r.read() if r.status_code != 200 else ""
        ct = r.headers["content-type"]
        assert "multipart/x-mixed-replace" in ct
        assert "boundary=frame" in ct
        first_chunk = next(r.iter_bytes(chunk_size=64))
        assert first_chunk.startswith(b"--frame"), (
            f"primer chunk inesperado: {first_chunk[:40]!r}"
        )


def test_live_404_when_camera_not_in_parking(
    client: TestClient, db_session: Session,
) -> None:
    """Cámara de otro parking → 404 (defensa contra IDs cruzados)."""
    admin = _seed_admin(db_session)
    parking_a = _seed_parking(db_session, code="P-LIVE-A")
    parking_b = _seed_parking(db_session, code="P-LIVE-B")
    _seed_camera(db_session, parking_b.id, code="CAM-LIVE-B")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.get(
        f"/api/v1/parkings/{parking_a.id}/cameras/1/live",
        headers=headers,
    )
    assert r.status_code == 404


def test_live_query_token_authenticates_via_parking_context(
    client: TestClient, db_session: Session,
) -> None:
    """Regresión Sprint Live-Preview (2026-07-07): ``?token=...`` debe
    atravesar tanto ``_user`` como ``_ctx = Depends(parking_context)``.

    Antes, ``parking_context`` usaba ``Depends(get_current_user)`` (sólo
    header Bearer) y rechazaba con 401 el flujo del ``<img>`` del
    navegador. Fix: ``parking_context`` ahora usa ``get_current_user_or_query_token``.
    """
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-LIVE-Q")
    cam = _seed_camera(db_session, parking.id, code="CAM-LIVE-Q")
    token = _login(client, admin.email, "admin12345")

    # GET ?token= con el <img> del navegador — ningún header Authorization.
    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/live?token={token}",
    )
    assert r.status_code == 200, (
        f"esperaba 200 (query token debería atravesar parking_context), "
        f"obtuve {r.status_code}: {r.text}"
    )
    assert "multipart/x-mixed-replace" in r.headers["content-type"]


def test_live_query_token_rejects_gestor_without_membership(
    client: TestClient, db_session: Session,
) -> None:
    """``?token=...`` con un gestor SIN membresía en la sucursal → 403.

    Verifica que el cambio en ``parking_context`` mantiene el control de
    acceso por sucursal cuando el token viaja por query string.
    """
    gestor = _seed_gestor(db_session, email="gestor-lv@test.es")
    parking = _seed_parking(db_session, code="P-LIVE-G")
    cam = _seed_camera(db_session, parking.id, code="CAM-LIVE-G")
    token = _login(client, gestor.email, "gestor1234")

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/live?token={token}",
    )
    assert r.status_code == 403
    assert "No tiene acceso" in r.text


def test_live_409_when_already_active(
    client: TestClient, db_session: Session,
) -> None:
    """Mientras hay un stream activo (reservado manualmente), el endpoint
    devuelve 409 Conflict."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-LIVE-409")
    cam = _seed_camera(db_session, parking.id, code="CAM-LIVE-409")
    headers = _login_headers(client, admin.email, "admin12345")

    loop = asyncio.get_event_loop()
    session = loop.run_until_complete(live_streams.try_acquire(cam.id))
    assert session is not None

    try:
        r = client.get(
            f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/live",
            headers=headers,
        )
        assert r.status_code == 409, (
            f"esperaba 409 con stream activo, obtuve {r.status_code}: {r.text}"
        )
        assert "vista en vivo abierta" in r.text
    finally:
        loop.run_until_complete(live_streams.release(cam.id))


def test_live_release_allows_new_session(
    client: TestClient, db_session: Session,
) -> None:
    """Tras ``release``, ``try_acquire`` vuelve a funcionar (el slot
    se libera correctamente)."""
    admin = _seed_admin(db_session)
    parking = _seed_parking(db_session, code="P-LIVE-REL")
    cam = _seed_camera(db_session, parking.id, code="CAM-LIVE-REL")
    _ = _login(client, admin.email, "admin12345")  # sólo limpia setup

    loop = asyncio.get_event_loop()
    s1 = loop.run_until_complete(live_streams.try_acquire(cam.id))
    assert s1 is not None
    loop.run_until_complete(live_streams.release(cam.id))
    s2 = loop.run_until_complete(live_streams.try_acquire(cam.id))
    assert s2 is not None
    loop.run_until_complete(live_streams.release(cam.id))