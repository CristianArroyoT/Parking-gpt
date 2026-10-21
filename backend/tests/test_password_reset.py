"""Tests del flujo de recuperación de contraseña (T-22 · plan maestro).

Cubre los criterios de aceptación del ítem:

  1. ``POST /auth/forgot-password`` manda un correo con token de un solo
     uso y caducidad.
  2. ``POST /auth/reset-password`` cambia la contraseña e invalida los
     tokens previos.
  3. El token se guarda **hasheado** y se invalida al usarlo.
  4. Plantilla de correo en español.
  5. Auditoría ``password_reset_requested`` / ``password_reset_completed``.
  6. Anti-abuso: rate-limit por IP y por email.

Reglas del repo que se respetan aquí:

- **Nunca se abre un socket SMTP**: el envío se intercepta con
  ``monkeypatch.setattr(email_module, "send_password_reset_email", ...)``
  (el router llama al atributo del módulo, así que el parche es efectivo).
- Los tests corren igual contra SQLite y PostgreSQL: no se usa ninguna
  función exclusiva de un motor (``strftime()``, etc.) y las fechas se
  normalizan a UTC antes de comparar.
"""

from __future__ import annotations

import hashlib
import itertools
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import password_reset as pr_mod
from app.models.password_reset_token import PasswordResetToken
from app.services import password_reset_email as email_module
from tests._audit_helpers import _seed_cliente, assert_audit_log

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _limpiar_buckets_rate_limit():
    """Limpia los buckets Redis propios de este flujo.

    ``conftest.py`` barre ``rl:login:*``, ``rl:users_*``… pero no conoce
    los buckets nuevos (``rl:forgot_password:*`` / ``rl:reset_password:*``),
    y no podemos tocarlo (fichero propiedad de otro agente). Redis NO se
    resetea entre tests, así que sin esta limpieza un test dejaría el
    bucket lleno y el siguiente recibiría un 429 inesperado.
    """
    try:
        import redis

        from app.core.config import get_settings

        cliente_redis = redis.Redis.from_url(
            get_settings().redis_url, decode_responses=True,
        )
        for prefijo in ("rl:forgot_password:*", "rl:reset_password:*"):
            for clave in cliente_redis.scan_iter(prefijo):
                cliente_redis.delete(clave)
    except Exception:  # pragma: no cover - si Redis no está, los tests lo notan
        pass
    return


@pytest.fixture()
def correos(monkeypatch) -> list[dict]:
    """Intercepta el envío de correo y guarda lo que se habría enviado."""
    enviados: list[dict] = []

    def _fake(*, to_email, full_name, raw_token, expires_minutes):
        enviados.append(
            {
                "to_email": to_email,
                "full_name": full_name,
                "raw_token": raw_token,
                "expires_minutes": expires_minutes,
            }
        )
        return True

    monkeypatch.setattr(email_module, "send_password_reset_email", _fake)
    return enviados


def _pedir_reset(client: TestClient, email: str) -> dict:
    """Llama a forgot-password y comprueba que devuelve 200."""
    r = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1 · forgot-password: correo con token y caducidad ─────────────────────


def test_forgot_password_envia_correo_con_token(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Una petición válida genera un correo con token y caducidad."""
    _seed_cliente(db_session, email="cliente.reset@test.es")

    _pedir_reset(client, "cliente.reset@test.es")

    assert len(correos) == 1
    correo = correos[0]
    assert correo["to_email"] == "cliente.reset@test.es"
    assert correo["full_name"] == "Cliente"
    assert correo["raw_token"], "el correo debe llevar un token"
    assert correo["expires_minutes"] == pr_mod.TOKEN_TTL_MINUTES
    assert correo["expires_minutes"] == 30


def test_forgot_password_no_devuelve_el_token(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """El token en claro NUNCA viaja en la respuesta HTTP."""
    _seed_cliente(db_session, email="secreto@test.es")

    respuesta = _pedir_reset(client, "secreto@test.es")

    assert correos[0]["raw_token"] not in respuesta["detail"]
    assert correos[0]["raw_token"] not in str(respuesta)


def test_no_revela_si_el_email_existe(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """La respuesta es idéntica exista o no la cuenta (anti-enumeración)."""
    _seed_cliente(db_session, email="existe@test.es")

    r_existe = client.post(
        "/api/v1/auth/forgot-password", json={"email": "existe@test.es"},
    )
    r_no_existe = client.post(
        "/api/v1/auth/forgot-password", json={"email": "noexiste@test.es"},
    )

    assert r_existe.status_code == r_no_existe.status_code == 200
    assert r_existe.json() == r_no_existe.json()
    # Sólo existe una cuenta: por eso sólo se envía un correo.
    assert len(correos) == 1


def test_usuario_inactivo_no_recibe_correo(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Una cuenta desactivada no genera correo (pero la respuesta es 200)."""
    usuario = _seed_cliente(db_session, email="inactivo@test.es")
    usuario.is_active = False
    db_session.commit()

    r = client.post("/api/v1/auth/forgot-password", json={"email": "inactivo@test.es"})

    assert r.status_code == 200
    assert correos == []


# ── 3 · el token se guarda hasheado y caduca ───────────────────────────────


def test_token_se_guarda_hasheado(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """En la BD sólo está el hash SHA-256: nunca el token en claro."""
    _seed_cliente(db_session, email="hasheado@test.es")

    _pedir_reset(client, "hasheado@test.es")
    token_bruto = correos[0]["raw_token"]

    db_session.expire_all()
    filas = db_session.query(PasswordResetToken).all()
    assert len(filas) == 1
    fila = filas[0]
    assert fila.token_hash != token_bruto
    assert fila.token_hash == hashlib.sha256(token_bruto.encode("utf-8")).hexdigest()
    assert token_bruto not in fila.token_hash


def test_token_tiene_caducidad(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """El token guardado caduca en 30 minutos."""
    _seed_cliente(db_session, email="caducidad@test.es")

    _pedir_reset(client, "caducidad@test.es")

    db_session.expire_all()
    fila = db_session.query(PasswordResetToken).one()
    expires = fila.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    restante = expires - datetime.now(timezone.utc)
    assert timedelta(minutes=25) < restante <= timedelta(minutes=30)


# ── 2 · reset-password: cambia la contraseña e invalida tokens previos ─────


def test_reset_password_cambia_la_contrasena(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Tras el reset, la clave nueva sirve y la vieja deja de servir."""
    _seed_cliente(db_session, email="reset@test.es", password="vieja-clave-1")

    _pedir_reset(client, "reset@test.es")
    token = correos[0]["raw_token"]

    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "nueva-clave-99"},
    )
    assert r.status_code == 200, r.text

    r_nueva = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@test.es", "password": "nueva-clave-99"},
    )
    assert r_nueva.status_code == 200, r_nueva.text

    r_vieja = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@test.es", "password": "vieja-clave-1"},
    )
    assert r_vieja.status_code == 401


def test_reset_invalida_los_tokens_jwt_previos(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Los JWT emitidos antes del reset dejan de valer."""
    _seed_cliente(db_session, email="jwt@test.es", password="vieja-clave-1")

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "jwt@test.es", "password": "vieja-clave-1"},
    )
    assert login.status_code == 200, login.text
    access = login.json()["access_token"]
    refresh = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # Antes del reset el token sirve.
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200

    _pedir_reset(client, "jwt@test.es")
    token = correos[0]["raw_token"]
    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "nueva-clave-99"},
    )
    assert r.status_code == 200, r.text

    # Después del reset, ni el access ni el refresh sirven.
    r_me = client.get("/api/v1/users/me", headers=headers)
    assert r_me.status_code == 401, r_me.text

    r_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"access_token": "", "expires_in": 0, "refresh_token": refresh},
    )
    assert r_refresh.status_code == 401, r_refresh.text


def test_token_es_de_un_solo_uso(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Un token consumido deja de valer aunque su caducidad no haya pasado."""
    _seed_cliente(db_session, email="unuso@test.es")

    _pedir_reset(client, "unuso@test.es")
    token = correos[0]["raw_token"]

    r1 = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "nueva-clave-99"},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "otra-clave-99"},
    )
    assert r2.status_code == 400, r2.text
    assert "no es válido o ha caducado" in r2.json()["detail"]


def test_solo_sirve_el_ultimo_token(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Pedir un reset nuevo invalida los tokens pendientes anteriores."""
    _seed_cliente(db_session, email="ultimo@test.es")

    _pedir_reset(client, "ultimo@test.es")
    _pedir_reset(client, "ultimo@test.es")
    token_1 = correos[0]["raw_token"]
    token_2 = correos[1]["raw_token"]

    r1 = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_1, "new_password": "nueva-clave-99"},
    )
    assert r1.status_code == 400, r1.text

    r2 = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_2, "new_password": "nueva-clave-99"},
    )
    assert r2.status_code == 200, r2.text


def test_token_caducado_se_rechaza(
    client: TestClient, db_session: Session,
) -> None:
    """Un token cuyo ``expires_at`` ya pasó → 400."""
    usuario = _seed_cliente(db_session, email="caduca@test.es")
    token_bruto = "token-ya-caducado-1234567890"
    db_session.add(
        PasswordResetToken(
            user_id=usuario.id,
            token_hash=pr_mod.hashear_token(token_bruto),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    db_session.commit()

    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_bruto, "new_password": "nueva-clave-99"},
    )
    assert r.status_code == 400, r.text


def test_token_desconocido_se_rechaza(
    client: TestClient, db_session: Session,
) -> None:
    """Un token que no existe en la BD → 400 (nada de traceback)."""
    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "token-que-no-existe", "new_password": "nueva-clave-99"},
    )
    assert r.status_code == 400, r.text


def test_contrasena_corta_se_rechaza(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """``new_password`` con menos de 8 caracteres → 422 (validación)."""
    _seed_cliente(db_session, email="corta@test.es")
    _pedir_reset(client, "corta@test.es")
    token = correos[0]["raw_token"]

    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "corta"},
    )
    assert r.status_code == 422


# ── 5 · auditoría ──────────────────────────────────────────────────────────


def test_auditoria_de_peticion(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Queda auditado ``password_reset_requested``."""
    _seed_cliente(db_session, email="audit-request@test.es")

    _pedir_reset(client, "audit-request@test.es")

    fila = assert_audit_log(
        db_session, action="password_reset_requested", result="success",
    )
    assert fila.payload["token_issued"] is True
    assert fila.payload["email"] == "audit-request@test.es"


def test_auditoria_de_peticion_para_email_inexistente(
    client: TestClient, db_session: Session,
) -> None:
    """También se audita la petición de un email sin cuenta."""
    _pedir_reset(client, "nadie@test.es")

    fila = assert_audit_log(
        db_session, action="password_reset_requested", result="success",
    )
    assert fila.payload["token_issued"] is False


def test_auditoria_de_completado(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """Queda auditado ``password_reset_completed``."""
    usuario = _seed_cliente(db_session, email="audit-done@test.es")
    _pedir_reset(client, "audit-done@test.es")
    token = correos[0]["raw_token"]

    r = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "nueva-clave-99"},
    )
    assert r.status_code == 200, r.text

    fila = assert_audit_log(
        db_session, action="password_reset_completed", result="success",
    )
    assert fila.payload["user_id"] == usuario.id


def test_auditoria_de_fallo_con_token_invalido(
    client: TestClient, db_session: Session,
) -> None:
    """Un token inválido deja audit de fallo (para detectar abuso)."""
    client.post(
        "/api/v1/auth/reset-password",
        json={"token": "token-invalido", "new_password": "nueva-clave-99"},
    )

    fila = assert_audit_log(
        db_session, action="password_reset_failed", result="failure",
    )
    assert fila.payload["reason"] == "unknown_token"


# ── 6 · anti-abuso: rate-limit por IP y por email ──────────────────────────


def test_rate_limit_por_email(
    client: TestClient, db_session: Session, monkeypatch, correos: list[dict],
) -> None:
    """El bucket por email corta aunque cada petición venga de otra IP."""
    # IP distinta en cada petición ⇒ el único bucket que se acumula es el
    # de email: así se aísla el comportamiento del bucket de email.
    contador = itertools.count(1)
    monkeypatch.setattr(
        pr_mod, "get_real_ip", lambda request: f"10.0.0.{next(contador)}",
    )
    _seed_cliente(db_session, email="rl-email@test.es")

    for _ in range(pr_mod.FORGOT_RATE_LIMIT_MAX_ATTEMPTS):
        r = client.post(
            "/api/v1/auth/forgot-password", json={"email": "rl-email@test.es"},
        )
        assert r.status_code == 200, r.text

    r = client.post(
        "/api/v1/auth/forgot-password", json={"email": "rl-email@test.es"},
    )
    assert r.status_code == 429, r.text


def test_rate_limit_por_ip(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """El bucket por IP corta aunque cada petición sea de un email distinto."""
    for i in range(pr_mod.FORGOT_RATE_LIMIT_MAX_ATTEMPTS):
        r = client.post(
            "/api/v1/auth/forgot-password", json={"email": f"user{i}@test.es"},
        )
        assert r.status_code == 200, r.text

    r = client.post(
        "/api/v1/auth/forgot-password", json={"email": "otro@test.es"},
    )
    assert r.status_code == 429, r.text


def test_rate_limit_audita_el_bloqueo(
    client: TestClient, db_session: Session, correos: list[dict],
) -> None:
    """El bloqueo por rate-limit queda auditado."""
    for _i in range(pr_mod.FORGOT_RATE_LIMIT_MAX_ATTEMPTS + 1):
        client.post("/api/v1/auth/forgot-password", json={"email": "auditoria-rl@test.es"})

    fila = assert_audit_log(
        db_session, action="password_reset_requested", result="failure",
    )
    assert fila.payload["reason"] == "rate_limited"


# ── 4 · plantilla de correo en español ─────────────────────────────────────


def test_plantilla_de_correo_en_espanol() -> None:
    """Las plantillas se renderizan en español e incluyen el enlace."""
    texto, html = email_module.render_password_reset_email(
        full_name="Ana Ruiz", raw_token="TOKEN-DE-PRUEBA", expires_minutes=30,
    )
    assert "Restablece tu contraseña" in texto
    assert "Ana Ruiz" in texto
    assert "30 minutos" in texto
    assert "TOKEN-DE-PRUEBA" in texto
    assert "un solo uso" in texto
    assert "Restablece tu contraseña" in html
    assert "TOKEN-DE-PRUEBA" in html


def test_existen_las_plantillas_en_el_disco() -> None:
    """Las plantillas viven en ``app/services/templates/password_reset/``."""
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "app" / "services" / "templates" / "password_reset"
    assert (base / "password_reset.txt.j2").is_file()
    assert (base / "password_reset.html.j2").is_file()


# ── robustez: el correo no puede reventar el endpoint ─────────────────────


def test_fallo_del_correo_devuelve_503_sin_traceback(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """Si el envío falla, el endpoint responde 503 y no deja tokens vivos."""
    _seed_cliente(db_session, email="smtp@test.es")
    monkeypatch.setattr(
        email_module, "send_password_reset_email", lambda **kwargs: False,
    )

    r = client.post("/api/v1/auth/forgot-password", json={"email": "smtp@test.es"})

    assert r.status_code == 503, r.text
    # No se ha quedado ningún token pendiente de usar.
    db_session.expire_all()
    assert db_session.query(PasswordResetToken).count() == 0


def test_correo_sin_configurar_devuelve_503(
    client: TestClient, db_session: Session, monkeypatch, correos: list[dict],
) -> None:
    """Sin transporte de correo configurado → 503 idéntico para cualquier email."""
    monkeypatch.setattr(
        email_module, "mail_transport_disponible", lambda: False,
    )

    r_existe = client.post(
        "/api/v1/auth/forgot-password", json={"email": "existe@test.es"},
    )
    r_no_existe = client.post(
        "/api/v1/auth/forgot-password", json={"email": "noexiste@test.es"},
    )

    assert r_existe.status_code == r_no_existe.status_code == 503
    assert r_existe.json() == r_no_existe.json()
    assert correos == []
