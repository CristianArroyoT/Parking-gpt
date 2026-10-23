"""Si no se puede registrar la sesión, no se emite el token (T-109).

POR QUÉ existe este fichero: el registro de la sesión era **fail-open**
(si Redis caía, los tokens se devolvían igualmente). El problema no era
el token inútil (el middleware de auditoría ya es fail-closed y devuelve
401 a todo lo que lleva token mientras Redis está caído), sino lo que
pasaba **cuando Redis volvía**: ese token no estaba registrado, así que
un cambio de contraseña —que revoca las sesiones registradas— **no lo
revocaba**: el token sobrevivía al reset.

Ahora el login es fail-closed como el middleware: si la sesión no se
puede registrar, se responde 503 y **no se emite ningún token**. El
usuario recibe un mensaje claro en vez de un token que no funciona, y no
queda ningún token sin rastrear.

Y el aviso de auditoría se escribe **después** de construir los tokens,
para que no diga «login_success» de un login que en realidad salió con
503.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.user import User

EMAIL = "sin-redis@test.es"
PASSWORD = "clave-sin-redis-1"


def _sembrar(db: Session) -> User:
    user = User(
        email=EMAIL, full_name="Cliente", role=UserRole.CLIENTE,
        hashed_password=hash_password(PASSWORD),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_sin_registrar_la_sesion_no_se_emite_token(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Si la sesion no se puede registrar, el login responde 503."""
    from app.api.v1 import auth as auth_mod

    _sembrar(db_session)
    monkeypatch.setattr(
        auth_mod.session_tracker, "track_session", lambda **_kw: False,
    )

    respuesta = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD},
    )

    assert respuesta.status_code == 503, respuesta.text
    assert "access_token" not in respuesta.json()
    assert "refresh_token" not in respuesta.json()


def test_la_via_oauth2_tambien_es_fail_closed(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """La via OAuth2 se comporta igual (comparten ``_build_tokens``)."""
    from app.api.v1 import auth as auth_mod

    _sembrar(db_session)
    monkeypatch.setattr(
        auth_mod.session_tracker, "track_session", lambda **_kw: False,
    )

    respuesta = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": EMAIL, "password": PASSWORD},
    )

    assert respuesta.status_code == 503, respuesta.text
    assert "access_token" not in respuesta.json()


def test_el_aviso_no_dice_login_success(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Un login que salio con 503 no se audita como ``login_success``."""
    from app.api.v1 import auth as auth_mod

    _sembrar(db_session)
    monkeypatch.setattr(
        auth_mod.session_tracker, "track_session", lambda **_kw: False,
    )

    client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD},
    )

    db_session.expire_all()
    exitos = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "login_success")
        .count()
    )
    assert exitos == 0, (
        "el aviso no debe decir login_success de un login que salio con 503"
    )
