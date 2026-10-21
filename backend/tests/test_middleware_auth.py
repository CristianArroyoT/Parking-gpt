"""Tests de regresión del middleware de autenticación (T-11 · plan maestro 2026-10-21).

POR QUÉ existe este fichero: en la QA del 2026-10-21 se descubrió que
el bloque ``try/except`` que decodifica el JWT en el ``AuditMiddleware``
había quedado ANIDADO dentro de un ``elif`` del parseo del header
``Authorization``. En el camino normal ``Authorization: Bearer <token>``
el token se extraía pero NO se decodificaba nunca. Las consecuencias
fueron dos, y las dos son silenciosas:

  1. ``request.state.audit["user_id"]`` quedaba SIEMPRE a ``None`` → toda
     la auditoría operativa perdía la atribución del usuario.
  2. ``jti``/``exp`` nunca se leían → el check de blacklist no se
     ejecutaba nunca, la blacklist no revocaba nada y ``logout``
     respondía 401 ("Token no soportado para logout").

Lo grave no es el bug en sí, sino que NINGÚN test lo detectaba: los
tests de auditoría miraban la *acción* registrada, no el ``user_id``.
Este fichero es el guardián de ese fix.

Cobertura:

  A. Contrato del parseo del header ``Authorization`` (unitario, con los
     bytes EXACTOS del header): ``Bearer <tok>``, ``bearer <tok>``,
     ``Bearer`` (sin token) y ``Bearer `` (prefijo vacío).
  B. El mismo contrato visto desde HTTP (end-to-end): 200 / 200 / 401 /
     401 — y NUNCA 500.
  C. La regresión funcional: ``logout`` blacklistea de verdad y una
     acción autenticada graba ``user_id`` (no ``None``).

Helpers propios: NO se tocan ``tests/_audit_helpers.py``, que comparten
otros tests.
"""
from __future__ import annotations

import asyncio

import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.middleware import AuditMiddleware
from app.core.security import create_access_token, hash_password
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.user import User

PASSWORD = "admin12345"


def _clean_login_buckets() -> None:
    """Borra los buckets Redis del rate-limit de login.

    El login está rate-limiteado por IP y por email (``rl:login:*``). Si
    queda un contador vivo de otro test, este login recibiría un 429 en
    lugar de un 200 y el fallo no tendría nada que ver con lo que
    estamos comprobando.
    """
    try:
        r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        for key in r.scan_iter(match="rl:login:*"):
            r.delete(key)
    except Exception:
        pass


# ── helpers ────────────────────────────────────────────────────────────

def _seed_admin(db: Session, *, email: str = "admin-t11@test.es") -> User:
    """Admin con contraseña conocida (helper local, no compartido)."""
    admin = User(
        email=email,
        full_name="Admin T11",
        role=UserRole.ADMIN,
        hashed_password=hash_password(PASSWORD),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    """Login limpio de contadores de rate-limit (ver ``_clean_login_buckets``)."""
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _audit_context(raw_authorization: bytes | None) -> dict:
    """Ejecuta el ``AuditMiddleware`` con un header ``Authorization`` crudo.

    Se monta el scope ASGI a mano para poder enviar los bytes EXACTOS
    del header (p. ej. ``b"Bearer "`` con el espacio final), cosa que
    un cliente HTTP no garantiza: el stack HTTP normaliza los espacios
    sobrantes y no se podría distinguir ``"Bearer"`` de ``"Bearer "``.

    Devuelve el dict que el middleware deja en ``request.state.audit``.
    """
    headers = [(b"host", b"testserver")]
    if raw_authorization is not None:
        headers.append((b"authorization", raw_authorization))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/users/me",
        "raw_path": b"/api/v1/users/me",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    async def _call_next(_request: Request) -> Response:
        return Response(status_code=200)

    middleware = AuditMiddleware(app=_call_next)
    asyncio.run(middleware.dispatch(request, _call_next))
    return request.state.audit


def _latest_audit(db: Session, action: str) -> AuditLog | None:
    """Última fila de auditoría con la acción dada (o ``None``)."""
    db.expire_all()
    db.commit()
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action)
        .order_by(AuditLog.id.desc())
        .first()
    )


# ── A. contrato del parseo del header (unitario) ───────────────────────

def test_middleware_decodes_bearer_with_token(db_session: Session) -> None:
    """``Bearer <token>``: el middleware decodifica el JWT.

    Este es EL camino normal. Si el bloque de decodificación vuelve a
    quedar anidado en una rama del parseo, aquí falla (y con él, toda
    la atribución de usuario de la auditoría).
    """
    admin = _seed_admin(db_session)
    token = create_access_token(admin.id, extra={"role": "admin"})

    ctx = _audit_context(b"Bearer " + token.encode())

    assert ctx["user_id"] == admin.id
    assert ctx["jti"] is not None
    assert ctx["type"] == "access"
    assert ctx["exp"] is not None
    assert ctx["decode_error"] is False


def test_middleware_decodes_lowercase_bearer_with_token(
    db_session: Session,
) -> None:
    """``bearer <token>`` (esquema en minúsculas) también decodifica.

    RFC 7235: el esquema HTTP es case-insensitive. Un cliente que
    mande ``bearer`` no debe perder la atribución de usuario ni la
    revocación por blacklist.
    """
    admin = _seed_admin(db_session)
    token = create_access_token(admin.id, extra={"role": "admin"})

    ctx = _audit_context(b"bearer " + token.encode())

    assert ctx["user_id"] == admin.id
    assert ctx["jti"] is not None
    assert ctx["decode_error"] is False


def test_middleware_marks_bearer_without_token_as_decode_error(
    db_session: Session,
) -> None:
    """``Bearer`` sin token: error de decodificación, pero NUNCA 500.

    Antes del parseo defensivo, ``split(None, 1)[1]`` lanzaba
    ``IndexError`` y el endpoint devolvía 500. Ahora el middleware
    marca ``decode_error`` y sigue dejando la petición al handler
    (que responde 401).
    """
    ctx = _audit_context(b"Bearer")

    assert ctx["decode_error"] is True
    assert ctx["user_id"] is None
    assert ctx["jti"] is None


def test_middleware_marks_bearer_with_empty_token_as_decode_error(
    db_session: Session,
) -> None:
    """``Bearer `` (prefijo con espacio pero sin token): error, no 500."""
    ctx = _audit_context(b"Bearer ")

    assert ctx["decode_error"] is True
    assert ctx["user_id"] is None
    assert ctx["jti"] is None


def test_middleware_without_authorization_header_is_not_a_decode_error(
    db_session: Session,
) -> None:
    """Sin header ``Authorization`` la petición es ANÓNIMA, no malformada.

    Importa distinguirlos: ``decode_error`` sólo lo consume ``logout``
    para rechazar tokens ilegibles, y una petición anónima (login,
    health, docs) no puede tratarse como un token corrupto.
    """
    ctx = _audit_context(None)

    assert ctx["decode_error"] is False
    assert ctx["user_id"] is None
    assert ctx["jti"] is None


# ── B. el mismo contrato visto desde HTTP (end-to-end) ─────────────────

def test_http_bearer_with_token_is_accepted(
    client: TestClient, db_session: Session,
) -> None:
    """``Authorization: Bearer <token>`` → 200 en un endpoint autenticado."""
    admin = _seed_admin(db_session)
    token = _login(client, admin.email)

    response = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == admin.email


def test_http_lowercase_bearer_is_accepted(
    client: TestClient, db_session: Session,
) -> None:
    """``Authorization: bearer <token>`` → 200 (esquema case-insensitive)."""
    admin = _seed_admin(db_session)
    token = _login(client, admin.email)

    response = client.get(
        "/api/v1/users/me", headers={"Authorization": f"bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == admin.email


def test_http_bearer_without_token_returns_401_not_500(
    client: TestClient,
) -> None:
    """``Authorization: Bearer`` (sin token) → 401 y NUNCA 500."""
    response = client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer"},
    )
    assert response.status_code == 401, response.text
    assert response.status_code < 500


def test_http_bearer_with_empty_token_returns_401_not_500(
    client: TestClient,
) -> None:
    """``Authorization: Bearer `` (prefijo vacío) → 401 y NUNCA 500."""
    response = client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401, response.text
    assert response.status_code < 500


# ── C. regresión funcional (lo que el bug rompía de verdad) ───────────

def test_authenticated_action_audit_carries_user_id(
    client: TestClient, db_session: Session,
) -> None:
    """Una acción autenticada graba el ``user_id`` (no ``None``).

    Es la aserción que faltaba en la suite: los tests de auditoría
    miraban la acción y el resultado, pero no quién la hizo.
    """
    admin = _seed_admin(db_session)
    token = _login(client, admin.email)

    response = client.patch(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "nueva-clave-t11"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204, response.text

    row = _latest_audit(db_session, "change_my_password")
    assert row is not None, "la acción autenticada debe dejar auditoría"
    assert row.user_id is not None, (
        "la auditoría de una acción autenticada debe llevar user_id"
    )
    assert row.user_id == admin.id


def test_logout_blacklists_token_so_it_cannot_be_reused(
    client: TestClient, db_session: Session,
) -> None:
    """``logout`` blacklistea de verdad: reutilizar el token → 401.

    Con el bug del middleware, ``jti`` nunca llegaba al handler de
    logout, así que el logout respondía 401 ("Token no soportado") y
    el token SIGUÍA siendo válido: la revocación era una fiction.
    """
    admin = _seed_admin(db_session)
    token = _login(client, admin.email)
    headers = {"Authorization": f"Bearer {token}"}

    # 1) El token sirve antes del logout.
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200

    # 2) Logout → 200 (el middleware tuvo que extraer jti/exp/type).
    logout_response = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200, logout_response.text

    # 3) El MISMO token ya no vale: el middleware aborta con 401.
    reused = client.get("/api/v1/users/me", headers=headers)
    assert reused.status_code == 401, reused.text
    assert reused.headers.get("WWW-Authenticate", "").startswith("Bearer error=")

    # 4) Y la auditoría del logout identifica al usuario.
    row = _latest_audit(db_session, "logout_success")
    assert row is not None
    assert row.user_id == admin.id
