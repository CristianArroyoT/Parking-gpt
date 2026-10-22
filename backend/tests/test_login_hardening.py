"""Endurecimiento del login (T-85, T-86 y T-87).

Tres defectos medidos contra el sistema en marcha el 2026-10-23:

1. **T-85 · La via OAuth2 no comprobaba ``is_active``.** Cada via de
   login repetia su propio codigo y se desincronizaron: la JSON
   rechazaba las cuentas desactivadas (403) y la OAuth2 las aceptaba
   (200 con tokens y un ``login_success`` en la auditoria que decia que
   un usuario desactivado habia entrado). Ahora hay **una sola**
   implementacion (``_autenticar``) y las dos vias la usan.

2. **T-86 · El tiempo de respuesta del login filtraba que cuentas
   existen.** Medido contra la API real: **13,9 ms** con un email
   inexistente frente a **207,6 ms** con un email real y contrasena
   incorrecta (el bcrypt no se ejecutaba si el usuario no existia: 15
   veces de diferencia). Ahora se verifica siempre, contra un hash
   senuelo cuando no hay usuario.

3. **T-87 · bcrypt trunca en silencio a 72 bytes.** Medido en el
   contenedor real: ``bcrypt.verify("a" * 100 + "b", bcrypt.hash("a" *
   100))`` devuelve ``True``: dos contrasenas con los mismos 72
   primeros bytes eran **la misma contrasena**. Los esquemas permitian
   128 caracteres, asi que el sistema aceptaba contrasenas que en
   realidad protegian menos de lo que el usuario creia.
"""
from __future__ import annotations

import time

import bcrypt as bcrypt_lib
import pytest
import redis
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.user import User

PASSWORD = "admin12345"


def _clean_login_buckets() -> None:
    """Borra los buckets Redis del rate-limit de login (ver test_auth_audit)."""
    try:
        r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        for key in r.scan_iter(match="rl:login:*"):
            r.delete(key)
    except Exception:
        pass


def _seed_user(
    db: Session,
    *,
    email: str,
    is_active: bool = True,
    password: str = PASSWORD,
) -> User:
    """Usuario con contraseña conocida (helper local, no compartido)."""
    user = User(
        email=email,
        full_name="Usuario T85",
        role=UserRole.ADMIN,
        is_active=is_active,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _latest_audit(db: Session, action: str) -> AuditLog | None:
    db.expire_all()
    db.commit()
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action)
        .order_by(AuditLog.id.desc())
        .first()
    )


# ── T-85 · una sola autenticacion para las dos vias ──────────────────────


def test_login_json_rechaza_usuario_inactivo(
    client: TestClient, db_session: Session,
) -> None:
    """La via JSON rechazaba las cuentas desactivadas (se mantiene)."""
    user = _seed_user(db_session, email="inactivo-json@test.es", is_active=False)
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 403, response.text
    assert _latest_audit(db_session, "login_success") is None


def test_login_oauth_rechaza_usuario_inactivo(
    client: TestClient, db_session: Session,
) -> None:
    """La via OAuth2 tambien rechaza las cuentas desactivadas (T-85).

    Antes de T-85 esta via **no** miraba ``is_active``: devolvia 200 con
    tokens y decia ``login_success`` en la auditoria. El token no servia
    para nada (todo endpoint protegido vuelve a comprobar ``is_active``),
    pero la auditoria moria.
    """
    user = _seed_user(db_session, email="inactivo-oauth@test.es", is_active=False)
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": user.email, "password": PASSWORD},
    )
    assert response.status_code == 403, response.text
    assert "inactivo" in response.text.lower()


def test_login_oauth_de_usuario_inactivo_no_audita_login_success(
    client: TestClient, db_session: Session,
) -> None:
    """Un intento sobre una cuenta desactivada NO deja ``login_success``."""
    user = _seed_user(db_session, email="inactivo-oauth2@test.es", is_active=False)
    _clean_login_buckets()
    client.post(
        "/api/v1/auth/login/oauth",
        data={"username": user.email, "password": PASSWORD},
    )
    fila = _latest_audit(db_session, "login_failure")
    assert fila is not None, "un intento denegado debe auditarse como fallo"
    assert fila.result == "failure"


def test_login_oauth_de_usuario_activo_sigue_funcionando(
    client: TestClient, db_session: Session,
) -> None:
    """El arreglo de T-85 no rompe la via OAuth2 de una cuenta normal."""
    user = _seed_user(db_session, email="activo-oauth@test.es")
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


# ── T-86 · el login no revela que cuentas existen ────────────────────────


def test_verify_password_or_dummy_devuelve_false_sin_hash() -> None:
    """Sin hash (usuario inexistente) el resultado es ``False``."""
    from app.core.security import verify_password_or_dummy

    assert verify_password_or_dummy("LoQueSea1!", None) is False


def test_login_con_email_inexistente_ejecuta_bcrypt(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Aunque el usuario no exista, el login ejecuta el bcrypt (senuelo).

    Sin esto, el tiempo de respuesta del login delata que cuentas estan
    registradas (medido: 13,9 ms frente a 207,6 ms).
    """
    from app.core import security as sec

    llamadas: list[str] = []
    original = sec._bcrypt_verify

    def espia(plain: str, hashed: str) -> bool:
        llamadas.append(hashed)
        return original(plain, hashed)

    monkeypatch.setattr(sec, "_bcrypt_verify", espia)
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nadie-este-existe@test.es", "password": "LoQueSea1!"},
    )
    assert response.status_code == 401, response.text
    assert llamadas, "el login debe ejecutar bcrypt aunque el usuario no exista"
    assert llamadas[-1] == sec._HASH_SENUELO, (
        "con usuario inexistente hay que verificar contra el hash senuelo"
    )


def test_login_inexistente_no_es_mas_rapido_que_el_real(
    client: TestClient, db_session: Session,
) -> None:
    """El login de un email inexistente tarda lo mismo que el de uno real.

    Comparación **entre los dos casos** (medianas de 3), no un suelo
    absoluto: dentro del ``TestClient`` hay un overhead que no depende
    del bcrypt y un umbral fijo no distinguiría "tarda 14 ms" de "tarda
    200 ms" de forma fiable.

    - Con el hash señuelo: las dos medianas coinciden (~200 ms).
    - Sin él: la del email inexistente cae a ~14 ms y la otra no
      (medido el 2026-10-23 contra la API real: 13,9 ms frente a
      207,6 ms).
    """
    usuario = _seed_user(db_session, email="real-para-tiempo@test.es")

    # Calentamiento: el primer bcrypt de un proceso paga un extra que
    # no tiene el segundo, y aqui se comparan dos mediciones.
    from app.core.security import _HASH_SENUELO, verify_password

    verify_password("Calentamiento1!", _HASH_SENUELO)

    def mediana(email: str, contrasena: str) -> float:
        muestras: list[float] = []
        for _ in range(3):
            _clean_login_buckets()
            inicio = time.perf_counter()
            respuesta = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": contrasena},
            )
            muestras.append(time.perf_counter() - inicio)
            assert respuesta.status_code == 401, respuesta.text
        muestras.sort()
        return muestras[len(muestras) // 2]

    t_inexistente = mediana("nadie-este-existe@test.es", "LoQueSea1!")
    t_real = mediana(usuario.email, "ContrasenaIncorrecta1!")
    diferencia = abs(t_real - t_inexistente)
    assert diferencia < 0.10, (
        f"el login de un email inexistente tardo {t_inexistente:.3f}s y el de "
        f"un email real {t_real:.3f}s (diferencia {diferencia:.3f}s): el "
        "tiempo de respuesta filtra que cuentas existen"
    )


# ── T-87 · bcrypt solo tiene en cuenta 72 bytes ─────────────────────────


def test_esquema_rechaza_contrasena_de_mas_de_72_bytes() -> None:
    """El alta de usuario NO admite contrasenas de mas de 72 bytes."""
    from app.schemas.user import UserCreate

    with pytest.raises(ValidationError) as exc:
        UserCreate(
            email="largo@test.es", full_name="Alguien", password="x" * 100,
        )
    assert "72 bytes" in str(exc.value)


def test_cambio_de_contrasena_rechaza_contrasena_larga() -> None:
    """El cambio de contrasena tampoco la admite."""
    from app.schemas.user import PasswordChange

    with pytest.raises(ValidationError) as exc:
        PasswordChange(current_password="x" * 100, new_password="NuevaClave1!")
    assert "72 bytes" in str(exc.value)


def test_reset_de_contrasena_rechaza_contrasena_larga() -> None:
    """El reset por token tampoco la admite."""
    from app.schemas.password_reset import ResetPasswordRequest

    with pytest.raises(ValidationError) as exc:
        ResetPasswordRequest(token="abc", new_password="x" * 100)
    assert "72 bytes" in str(exc.value)


def test_hash_password_no_trunca_en_silencio() -> None:
    """``hash_password`` falla en vez de guardar una contrasena truncada."""
    with pytest.raises(ValueError, match="72"):
        hash_password("x" * 100)


def test_verify_password_no_acepta_el_prefijo_equivalente() -> None:
    """72 bytes + un sufijo NO es la misma contrasena (T-87).

    Este es el caso que antes era un agujero: con el hash de 72 bytes,
    la contrasena de 80 bytes (mismos 72 primeros) **entraba**.
    """
    hash_72 = bcrypt_lib.hashpw(b"A" * 72, bcrypt_lib.gensalt(rounds=12)).decode()
    assert verify_password("A" * 72, hash_72) is True
    assert verify_password("A" * 80, hash_72) is False, (
        "una contrasena mas larga con el mismo prefijo no puede ser la misma"
    )


def test_login_rechaza_contrasena_de_mas_de_72_bytes(
    client: TestClient, db_session: Session,
) -> None:
    """El login de una contrasena de mas de 72 bytes se rechaza (422).

    Con ``truncate_error=True`` el hash solo distingue el prefijo, asi
    que una contrasena larga no puede autenticarse: se rechaza en la
    puerta en vez de compararse truncada.
    """
    user = _seed_user(db_session, email="largo-login@test.es")
    _clean_login_buckets()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "A" * 80},
    )
    assert response.status_code == 422, response.text
    assert "72 bytes" in response.text
