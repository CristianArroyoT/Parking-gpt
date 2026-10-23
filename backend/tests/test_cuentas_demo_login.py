"""Las cuentas de demostración no pueden entrar en staging/producción (T-98).

POR QUÉ existe este fichero: el seed ya se niega a crear las cuentas de
demostración fuera de desarrollo (T-83), pero el **login no las
filtraba**. Si la base de datos de una sucursal arrastraba cuentas de
una instalación de desarrollo (un dump, una copia, una restauración
vieja), las credenciales **publicas de este repositorio** —y del README—
servirían para entrar como administrador.

El rechazo es un **401 como el de cualquier contraseña incorrecta**: un
403 distinto ("cuenta de demostración") diría que ese correo existe, que
es justo el oráculo de enumeración que T-86 tapa.

En ``development`` y ``test`` **no** se bloquea: la QA visual y el
botón «rellenar demo» de la pantalla de login las usan a propósito.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User

EMAIL_DEMO = "admin@solidapp.es"
PASSWORD_DEMO = "admin12345"


def _sembrar_admin_demo(db: Session) -> None:
    db.add(
        User(
            email=EMAIL_DEMO,
            full_name="Administrador",
            role=UserRole.ADMIN,
            hashed_password=hash_password(PASSWORD_DEMO),
        )
    )
    db.commit()


def test_en_produccion_la_cuenta_demo_no_entra(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """En producción, la cuenta de demo responde 401 (como una contraseña mala)."""
    monkeypatch.setattr(get_settings(), "environment", "production")
    _sembrar_admin_demo(db_session)

    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL_DEMO, "password": PASSWORD_DEMO},
    )
    assert respuesta.status_code == 401, respuesta.text
    # Ni un 403: un codigo distinto revelaria que el correo existe.
    assert "demo" not in respuesta.text.lower()


def test_en_staging_la_cuenta_demo_no_entra(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """En staging, igual (un staging es un entorno real)."""
    monkeypatch.setattr(get_settings(), "environment", "staging")
    _sembrar_admin_demo(db_session)

    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL_DEMO, "password": PASSWORD_DEMO},
    )
    assert respuesta.status_code == 401, respuesta.text


def test_en_desarrollo_la_cuenta_demo_si_entra(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """En desarrollo la cuenta demo entra (la QA la usa a proposito)."""
    monkeypatch.setattr(get_settings(), "environment", "development")
    _sembrar_admin_demo(db_session)

    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL_DEMO, "password": PASSWORD_DEMO},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["access_token"]


def test_un_correo_normal_no_se_bloquea(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """El bloqueo es solo para las cuentas de demo: un admin normal entra."""
    monkeypatch.setattr(get_settings(), "environment", "production")
    db_session.add(
        User(
            email="admin-real@solidapp.es",
            full_name="Admin Real",
            role=UserRole.ADMIN,
            hashed_password=hash_password("admin12345"),
        )
    )
    db_session.commit()

    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": "admin-real@solidapp.es", "password": "admin12345"},
    )
    assert respuesta.status_code == 200, respuesta.text


def test_el_intento_queda_auditado(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """El intento con una cuenta de demo queda auditado con su motivo."""
    from tests._audit_helpers import assert_audit_log

    monkeypatch.setattr(get_settings(), "environment", "production")
    _sembrar_admin_demo(db_session)

    client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL_DEMO, "password": PASSWORD_DEMO},
    )

    fila = assert_audit_log(db_session, action="login_failure", result="failure")
    assert "demo_account" in str(fila.payload), fila.payload
