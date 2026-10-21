"""Tests de la auditoría del login (T-08 · plan maestro 2026-10-21).

POR QUÉ existe este fichero: la fila de auditoría ``login_success`` se
grababa SIEMPRE con ``user_id=None``. La causa es estructural: la
petición de login NO lleva header ``Authorization`` (el cliente aún no
tiene token), así que el ``AuditMiddleware`` —que sólo puede deducir el
usuario del JWT— no tiene nada que decodificar. Pero el handler del
login, tras validar la contraseña, SÍ sabe quién entra. Sin ese dato,
la auditoría de accesos no permite responder a la pregunta más básica
en una revisión forense: "¿quién entró y desde dónde?".

Estos tests blindan el contrato:

  1. ``login_success`` identifica al usuario (``user_id`` NO nulo) y
     apunta al recurso ``users/{id}``.
  2. El login por formulario OAuth2 (``/auth/login/oauth``) también lo
     identifica: es el mismo flujo de negocio, debe auditar igual.
  3. El login fallido NO se atribuye a ningún usuario (semántica
     intacta: un intento con credenciales incorrectas no prueba quién
     intentó entrar).
  4. Enriquecer el ``user_id`` NO pierde el resto del contexto del
     middleware (``ip`` y ``correlation_id``).

Helpers propios (NO se tocan ``tests/_audit_helpers.py``, que comparten
otros tests).
"""
from __future__ import annotations

import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
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


def _seed_admin(db: Session, *, email: str = "admin-t08@test.es") -> User:
    """Admin con contraseña conocida (helper local, no compartido)."""
    admin = User(
        email=email,
        full_name="Admin T08",
        role=UserRole.ADMIN,
        hashed_password=hash_password(PASSWORD),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _login(
    client: TestClient, email: str, password: str = PASSWORD,
    headers: dict[str, str] | None = None,
):
    """Login limpio de contadores de rate-limit (ver ``_clean_login_buckets``)."""
    _clean_login_buckets()
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=headers,
    )


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


def test_login_success_audit_identifies_the_user(
    client: TestClient, db_session: Session,
) -> None:
    """``login_success`` graba el ``user_id`` del usuario que entra.

    Regresión de T-08: antes esta fila salía con ``user_id=None``.
    """
    admin = _seed_admin(db_session)

    response = _login(client, admin.email)
    assert response.status_code == 200, response.text

    row = _latest_audit(db_session, "login_success")
    assert row is not None, "el login OK debe dejar una fila de auditoría"
    assert row.user_id is not None, (
        "login_success debe identificar al usuario (user_id no puede ser None)"
    )
    assert row.user_id == admin.id
    assert row.resource == f"users/{admin.id}"
    assert row.result == "success"


def test_login_oauth_success_audit_identifies_the_user(
    client: TestClient, db_session: Session,
) -> None:
    """El login por formulario OAuth2 también identifica al usuario.

    Es el mismo flujo de negocio servido por otro endpoint (el que usa
    el botón "Authorize" de /docs): si uno identifica al usuario, el
    otro también.
    """
    admin = _seed_admin(db_session, email="admin-t08-oauth@test.es")

    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": admin.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text

    row = _latest_audit(db_session, "login_success")
    assert row is not None, "el login OAuth2 OK debe dejar fila de auditoría"
    assert row.user_id is not None, (
        "login_success (OAuth2) debe identificar al usuario"
    )
    assert row.user_id == admin.id
    assert row.resource == f"users/{admin.id}"


def test_login_failure_audit_is_not_attributed_to_a_user(
    client: TestClient, db_session: Session,
) -> None:
    """Un login fallido NO se atribuye a un usuario concreto.

    Semántica que NO debe cambiar al arreglar T-08: si las credenciales
    son incorrectas no hay forma de saber quién intentó entrar, así que
    la fila queda con ``user_id=None`` y la traza vive en el payload
    (``email`` + ``reason``).
    """
    _seed_admin(db_session)

    response = _login(client, "ghost-t08@test.es", password="incorrecta")
    assert response.status_code == 401, response.text

    row = _latest_audit(db_session, "login_failure")
    assert row is not None
    assert row.user_id is None
    assert row.result == "failure"
    assert row.payload is not None
    assert row.payload.get("email") == "ghost-t08@test.es"


def test_login_success_audit_keeps_ip_and_correlation_id(
    client: TestClient, db_session: Session,
) -> None:
    """Enriquecer el ``user_id`` no debe perder el contexto del middleware.

    El ``AuditMiddleware`` sigue siendo la fuente de ``ip`` y
    ``correlation_id``; el handler sólo añade el ``user_id`` que el
    middleware no puede conocer en un login.
    """
    admin = _seed_admin(db_session, email="admin-t08-ctx@test.es")
    correlation_id = "cid-t08-login-success"

    response = _login(
        client, admin.email, headers={"X-Request-ID": correlation_id},
    )
    assert response.status_code == 200, response.text

    row = _latest_audit(db_session, "login_success")
    assert row is not None
    assert row.user_id == admin.id
    assert row.correlation_id == correlation_id
    assert row.ip is not None
