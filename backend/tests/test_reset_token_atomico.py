"""El token de reset se reclama de forma atómica: un solo uso real (T-107).

POR QUÉ existe este fichero: hasta T-107 el endpoint **miraba** el token
(``used_at is None``) y luego lo consumía al final. Entre el «mirar» y el
«consumir» hay una ventana (revocar sesiones, hacer el bcrypt...), así
que **dos peticiones con el mismo token a la vez** podían pasar las dos
comprobaciones y las dos cambiar la contraseña: la segunda machacaba la
primera y las dos respondían «contraseña actualizada».

Ahora el token se **reclama** con un UPDATE condicional
(``used_at IS NULL``): solo una petición lo consigue.

Estos tests comprueban:

1. el UPDATE condicional: dos consumidores, el segundo no toca ninguna fila;
2. el endpoint: si otra petición consumió el token entre medias, esta se
   rechaza **y no cambia la contraseña**.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import password_reset as reset_mod
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User

EMAIL = "atomico@test.es"


def _sembrar(db: Session) -> User:
    user = User(
        email=EMAIL, full_name="Cliente", role=UserRole.CLIENTE,
        hashed_password=hash_password("clave-antigua-1"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _crear_token(db: Session, user: User) -> tuple[PasswordResetToken, str]:
    token_bruto = reset_mod.generar_token_bruto()
    fila = PasswordResetToken(
        user_id=user.id,
        token_hash=reset_mod.hashear_token(token_bruto),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila, token_bruto


def test_el_update_condicional_solo_consume_una_vez(db_session: Session) -> None:
    """Dos consumidores del mismo token: el segundo no toca ninguna fila."""
    user = _sembrar(db_session)
    fila, _token = _crear_token(db_session, user)
    ahora = datetime.now(timezone.utc)

    # Dos sesiones distintas sobre la misma base (como dos peticiones).
    Session1 = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False,
    )
    Session2 = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False,
    )
    with Session1() as s1, Session2() as s2:
        primero = (
            s1.query(PasswordResetToken)
            .filter(
                PasswordResetToken.id == fila.id,
                PasswordResetToken.used_at.is_(None),
            )
            .update({"used_at": ahora}, synchronize_session=False)
        )
        s1.commit()
        segundo = (
            s2.query(PasswordResetToken)
            .filter(
                PasswordResetToken.id == fila.id,
                PasswordResetToken.used_at.is_(None),
            )
            .update({"used_at": ahora}, synchronize_session=False)
        )
        s2.commit()

    assert primero == 1, "el primer consumidor consume el token"
    assert segundo == 0, "el segundo consumidor NO puede consumirlo"


def test_si_otro_consume_el_token_entre_medias_el_reset_se_rechaza(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si otra petición consumió el token, esta se rechaza y no cambia nada.

    Se simula la carrera en el punto exacto: el hook ``revoke_all`` (que
    el endpoint llama entre el «mirar» el token y el reclamarlo) consume
    el token desde otra sesión, como lo haría la petición que ganó.
    """
    user = _sembrar(db_session)
    fila, token = _crear_token(db_session, user)
    hash_antes = user.hashed_password

    Session2 = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False,
    )

    def _otro_consume(*_args, **_kwargs) -> int:
        """La otra peticion gana la carrera y consume el token."""
        with Session2() as s2:
            s2.query(PasswordResetToken).filter(
                PasswordResetToken.id == fila.id,
            ).update(
                {"used_at": datetime.now(timezone.utc)},
                synchronize_session=False,
            )
            s2.commit()
        return 1

    monkeypatch.setattr(
        reset_mod.session_tracker, "revoke_all", _otro_consume,
    )

    respuesta = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "clave-nueva-99"},
    )
    assert respuesta.status_code == 400, respuesta.text
    assert "no es válido o ha caducado" in respuesta.json()["detail"]

    db_session.expire_all()
    fila_usuario = db_session.get(User, user.id)
    assert fila_usuario.hashed_password == hash_antes, (
        "la contrasena no debe cambiar si el token ya lo consumio otra "
        "peticion"
    )
