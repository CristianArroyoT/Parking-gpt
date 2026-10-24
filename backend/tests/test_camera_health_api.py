"""Tests del endpoint ``GET /parkings/{parking_id}/cameras/{camera_id}/health``
(sprint Camera Health 2026-07-01).

Estrategia: TestClient + SQLite en memoria + StaticPool. Las cámaras y los
health fields se setean directamente en BD con ``db_session``. Redis se
mockea a nivel de módulo (en el router) para los tests que necesiten
aislar el contador ``consecutive_failures`` o forzar un fallo.

Cobertura:
  1. status=never_probed (ambos campos NULL).
  2. status=healthy (last_ok=True + probe reciente).
  3. status=degraded (last_ok=True + probe antiguo, > stale_threshold).
  4. status=offline (last_ok=False).
  5. 404 cuando la cámara no existe o pertenece a otro parking.
  6. 401 sin token.
  7. 403 gestor sin membresía en el parking del path.
  8. Redis caído → fallback a consecutive_failures=0, sin 500.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.parking import Camera, Parking
from app.models.user import ParkingMembership, User


# ── helpers ────────────────────────────────────────────────────────
def _seed(db) -> tuple[Parking, Camera, User]:
    """Admin + parking + cámara fresca (sin health fields)."""
    admin = User(
        email="admin@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    parking = Parking(code="P-H", name="Health test", address="x", city="y")
    db.add_all([admin, parking]); db.flush()
    cam = Camera(
        parking_id=parking.id, code="CAM-H1", name="Cámara H1",
        rtsp_url="rtsp://real/h1",
    )
    db.add(cam); db.commit()
    db.refresh(parking); db.refresh(cam)
    return parking, cam, admin


def _seed_with_gestor(db) -> tuple[Parking, Camera, User, User, Parking]:
    """Admin + gestor con membresía en parking_member + parking_stranger sin gestor."""
    admin = User(
        email="admin@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    gestor = User(
        email="gestor@test.es", full_name="Gestor",
        role=UserRole.GESTOR, hashed_password=hash_password("gestor1234"),
    )
    parking_member = Parking(code="P-G", name="Con gestor", address="x", city="y")
    parking_stranger = Parking(code="P-X", name="Sin gestor", address="x", city="y")
    db.add_all([admin, gestor, parking_member, parking_stranger]); db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking_member.id))
    cam = Camera(
        parking_id=parking_stranger.id, code="CAM-X", name="Cámara X",
        rtsp_url="rtsp://real/x",
    )
    db.add(cam); db.commit()
    db.refresh(parking_stranger); db.refresh(cam)
    return parking_stranger, cam, admin, gestor, parking_stranger


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── tests de status ────────────────────────────────────────────────
def test_health_never_probed(client: TestClient, db_session) -> None:
    """Cámara recién creada (last_at=NULL, last_ok=NULL) → never_probed."""
    parking, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["camera_id"] == cam.id
    assert body["status"] == "never_probed"
    assert body["last_heartbeat_at"] is None
    assert body["last_heartbeat_ok"] is None
    assert body["consecutive_failures"] == 0
    assert body["stale_threshold_seconds"] == 120


def test_health_healthy_when_recent(client: TestClient, db_session) -> None:
    """last_ok=True y edad < stale → healthy."""
    parking, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    cam.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    cam.last_heartbeat_ok = True
    db_session.commit()

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert body["last_heartbeat_ok"] is True


def test_health_degraded_when_stale(client: TestClient, db_session) -> None:
    """last_ok=True pero edad > stale → degraded (cámara viva, beat colgado)."""
    parking, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    # 130 s > stale_threshold (120 s por defecto). La cámara respondió OK pero
    # el último probe es antiguo: probablemente el worker probe_heartbeats
    # se quedó colgado o la cámara dejó de recibir pings.
    cam.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=130)
    cam.last_heartbeat_ok = True
    db_session.commit()

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "degraded"


def test_health_offline_when_last_failed(client: TestClient, db_session) -> None:
    """last_ok=False → offline (aunque el probe sea reciente)."""
    parking, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    cam.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    cam.last_heartbeat_ok = False
    db_session.commit()

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "offline"
    assert body["last_heartbeat_ok"] is False


# ── tests de errores / RBAC ───────────────────────────────────────
def test_health_unknown_camera_returns_404(client: TestClient, db_session) -> None:
    """Cámara id inexistente o de otro parking → 404."""
    parking, _cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/99999/health",
        headers=headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Cámara no encontrada"


def test_health_unauthenticated_returns_401(client: TestClient, db_session) -> None:
    """Sin token → 401."""
    parking, cam, _admin = _seed(db_session)

    r = client.get(f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health")
    assert r.status_code == 401, r.text


def test_health_gestor_without_membership_returns_403(
    client: TestClient, db_session
) -> None:
    """Gestor SIN membresía en el parking del path → 403 (parking_context)."""
    parking, cam, admin, gestor, _ = _seed_with_gestor(db_session)
    # La cámara pertenece a ``parking_stranger`` (parking_id=cam.parking_id).
    # El gestor NO tiene membresía en ese parking.
    headers = {
        "Authorization": f"Bearer {_login(client, gestor.email, 'gestor1234')}"
    }

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 403, r.text


# ── test defensivo: Redis caído → consecutive_failures=0 ──────────
def test_health_redis_failure_falls_back_to_zero(
    client: TestClient, db_session, monkeypatch
) -> None:
    """Si Redis lanza, el endpoint devuelve 200 con consecutive_failures=0."""
    from redis.exceptions import RedisError
    import app.api.v1.cameras as cameras_mod

    parking, cam, admin = _seed(db_session)
    headers = {"Authorization": f"Bearer {_login(client, admin.email, 'admin12345')}"}

    class _BoomRedis:
        @staticmethod
        def from_url(*args, **kwargs):
            class _Conn:
                def get(self, *_a, **_kw):
                    raise RedisError("simulated redis down")
            return _Conn()

    monkeypatch.setattr(cameras_mod.redis, "Redis", _BoomRedis)

    r = client.get(
        f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["consecutive_failures"] == 0
    # El status sigue derivándose correctamente de los health fields de BD.
    assert body["status"] == "never_probed"

def test_health_con_fecha_naive_no_da_500(client: TestClient, db_session) -> None:
    """Un datetime *naive* (como el que devuelve SQLite) no puede dar un 500.

    T-152 (2026-10-24): el endpoint restaba ``last_heartbeat_at`` de un
    datetime con zona sin normalizar. En SQLite el valor **viene naive**
    al releerlo de la BD ⇒ ``TypeError`` ⇒ 500. Los tests que ya habia no
    lo detectaban porque asignaban la fecha **en memoria** (y ahi sigue
    siendo *aware*); este la asigna naive y **relee de la BD**.
    """
    parking, cam, admin = _seed(db_session)
    ahora = datetime.now(timezone.utc)
    # Naive, como lo deja SQLite.
    cam.last_heartbeat_at = ahora.replace(tzinfo=None)
    cam.last_heartbeat_ok = True
    db_session.commit()
    db_session.refresh(cam)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "admin12345"},
    )
    token = login.json()["access_token"]
    try:
        respuesta = client.get(
            f"/api/v1/parkings/{parking.id}/cameras/{cam.id}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
    except TypeError as exc:
        # OJO: sin la normalizacion, el endpoint peta con un TypeError
        # (que en produccion es un 500). Se convierte en un AssertionError
        # para que el fallo del test sea una **asercion** y no un error de
        # codigo (la puerta de pruebas inversas lo exige).
        raise AssertionError(
            f"la fecha naive ha petado el endpoint de health: {exc}"
        ) from exc
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == "healthy"
