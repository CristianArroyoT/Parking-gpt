"""El correo se guarda y se compara en forma canónica (T-99).

POR QUÉ existe este fichero: un correo **no distingue** mayúsculas de
minúsculas, pero el código comparaba el texto tal como se escribía.
Medido el 2026-10-23 contra la API real en marcha:

- un usuario creado como ``Gestor.Mixto@solidapp.es`` se logueaba con
  ese correo exacto (200) y **no** con ``gestor.mixto@solidapp.es`` (401);
- ``ADMIN@solidapp.es`` tampoco entraba.

O sea: el mismo correo dependía de cómo lo escribieras, y un usuario que
teclea en mayúsculas se quedaba fuera sin entender por qué.

Aquí se comprueba que:

1. el login entra con el correo en cualquier forma;
2. el alta **guarda** el correo canónico (y el índice único de la base
   impide crear dos cuentas que solo se diferencien en las mayúsculas);
3. el «olvidé mi contraseña» encuentra la cuenta igual.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User

EMAIL = "Gestor.Mixto@solidapp.es"
PASSWORD = "ClaveDelGestor1"


def _sembrar(db: Session, email: str = EMAIL) -> User:
    """Un usuario cuyo email esta escrito en mayusculas y minusculas."""
    user = User(
        email=email,
        full_name="Gestor Mixto",
        role=UserRole.GESTOR,
        hashed_password=hash_password(PASSWORD),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_el_login_acepta_el_correo_en_cualquier_forma(
    client: TestClient, db_session: Session,
) -> None:
    """El correo no distingue mayusculas: el login tampoco."""
    _sembrar(db_session)
    for forma in (EMAIL, EMAIL.lower(), EMAIL.upper()):
        respuesta = client.post(
            "/api/v1/auth/login", json={"email": forma, "password": PASSWORD}
        )
        assert respuesta.status_code == 200, f"{forma}: {respuesta.text}"


def test_el_alta_guarda_el_correo_canonico(
    client: TestClient, db_session: Session,
) -> None:
    """El email se guarda en minusculas (forma canonica)."""
    admin = User(
        email="admin-canonico@test.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )
    db_session.add(admin)
    db_session.commit()
    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": "admin-canonico@test.es", "password": "admin12345"},
    )
    assert respuesta.status_code == 200, respuesta.text
    token = respuesta.json()["access_token"]

    alta = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "Nuevo.Gestor@Solidapp.ES",
            "full_name": "Nuevo Gestor",
            "password": "ClaveNueva1234",
            "role": "gestor",
        },
    )
    assert alta.status_code == 201, alta.text

    fila = (
        db_session.query(User)
        .filter(User.id == alta.json()["id"])
        .one_or_none()
    )
    assert fila is not None
    assert fila.email == "nuevo.gestor@solidapp.es", (
        f"el email se guardo como {fila.email!r}, no en la forma canonica"
    )


def test_no_se_pueden_crear_dos_cuentas_que_solo_difieran_en_mayusculas(
    client: TestClient, db_session: Session,
) -> None:
    """La base de datos prohibe el duplicado por mayusculas."""
    admin = User(
        email="admin-dup@test.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )
    db_session.add(admin)
    db_session.commit()
    respuesta = client.post(
        "/api/v1/auth/login",
        json={"email": "admin-dup@test.es", "password": "admin12345"},
    )
    token = respuesta.json()["access_token"]
    cabeceras = {"Authorization": f"Bearer {token}"}

    primero = client.post(
        "/api/v1/users",
        headers=cabeceras,
        json={
            "email": "Dup@Solidapp.es",
            "full_name": "Dup",
            "password": "ClaveNueva1234",
            "role": "gestor",
        },
    )
    assert primero.status_code == 201, primero.text

    segundo = client.post(
        "/api/v1/users",
        headers=cabeceras,
        json={
            "email": "dup@solidapp.es",
            "full_name": "Dup",
            "password": "ClaveNueva1234",
            "role": "gestor",
        },
    )
    assert segundo.status_code == 409, (
        f"la segunda alta deberia rebotar (409), dio {segundo.status_code}: "
        f"{segundo.text}"
    )


def test_el_reset_de_contrasena_encuentra_la_cuenta(
    client: TestClient, db_session: Session,
) -> None:
    """'Olvide mi contrasena' tambien habla del correo canonico."""
    _sembrar(db_session)
    respuesta = client.post(
        "/api/v1/auth/forgot-password", json={"email": EMAIL.upper()}
    )
    assert respuesta.status_code == 200, respuesta.text
    # Si no hubiera encontrado la cuenta, no habria ningun token creado.
    from app.models.password_reset_token import PasswordResetToken

    db_session.expire_all()
    assert db_session.query(PasswordResetToken).count() == 1, (
        "el reset deberia haber encontrado la cuenta y creado su token"
    )
