"""El correo de reset se envía FUERA del ciclo del request (T-94).

POR QUÉ existe este fichero: el envío del correo estaba **dentro** del
request de ``forgot-password``. Con un SMTP lento o caído, la petición
tardaba **5,03 s** (medido el 2026-10-23 con un SMTP de mentira que
acepta la conexión y no contesta nunca) y el worker de la API quedaba
bloado. Y esa misma latencia era un **oráculo**: con la cuenta existente
la respuesta tardaba hasta 5 s; sin la cuenta, era instantánea. O sea:
la petición decía si el correo estaba registrado, y de paso podía
tumbar el pool de workers.

Lo que se comprueba aquí:

1. el endpoint **encola** el envío y **no** llama al SMTP;
2. el endpoint responde en un tiempo **igual** exista o no la cuenta;
3. la tarea de Celery borra el token si el envío falla (un token que el
   usuario nunca recibió no debe quedar válido).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.password_reset_token import PasswordResetToken
from app.services import password_reset_email as email_module
from app.workers import tasks as tasks_mod

SUELO_MS = 350


def _sembrar_usuario(db_session: Session, email: str = "cliente.async@test.es") -> None:
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User

    db_session.add(
        User(
            email=email,
            full_name="Cliente",
            role=UserRole.CLIENTE,
            hashed_password=hash_password("cliente1234"),
        )
    )
    db_session.commit()


def _limpiar_buckets() -> None:
    import redis

    from app.core.config import get_settings

    try:
        cliente = redis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        for clave in cliente.scan_iter("rl:forgot_password:*"):
            cliente.delete(clave)
    except Exception:  # pragma: no cover
        pass


def test_el_endpoint_encola_y_no_llama_al_smtp(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """El request encola el envío; el SMTP no se toca."""
    _sembrar_usuario(db_session)
    llamadas_smtp: list[str] = []
    encolados: list[dict] = []

    def _smtp(**kwargs):
        llamadas_smtp.append(kwargs.get("to_email", "?"))
        return True

    def _encolar(**kwargs):
        encolados.append(kwargs)
        return True

    monkeypatch.setattr(email_module, "send_password_reset_email", _smtp)
    monkeypatch.setattr(email_module, "encolar_envio_reset", _encolar)
    _limpiar_buckets()

    respuesta = client.post(
        "/api/v1/auth/forgot-password", json={"email": "cliente.async@test.es"}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert encolados, "el endpoint debe encolar el envío del correo"
    assert llamadas_smtp == [], (
        "el SMTP no debe llamarse dentro del request: es lo que lo bloqueaba"
    )


def test_el_endpoint_no_es_mas_rapido_si_la_cuenta_no_existe(
    client: TestClient, db_session: Session, monkeypatch,
) -> None:
    """La respuesta tarda lo mismo exista o no la cuenta (suelo de latencia)."""
    _sembrar_usuario(db_session)
    monkeypatch.setattr(
        email_module, "encolar_envio_reset", lambda **kwargs: True
    )

    def _minimo(email: str) -> float:
        """El tiempo MAS CORTO de tres peticiones (el mas estable).

        Con la maquina saturada (medido el 2026-10-23: la suite del
        contenedor corria en paralelo con el CI del host) una sola
        medida puede comerse cientos de ms de ruido. El minimo de tres
        es la estimacion menos contaminada.
        """
        tiempos = []
        for _ in range(3):
            _limpiar_buckets()
            inicio = time.perf_counter()
            r = client.post("/api/v1/auth/forgot-password", json={"email": email})
            tiempos.append(time.perf_counter() - inicio)
            assert r.status_code == 200, r.text
        return min(tiempos)

    con_cuenta = _minimo("cliente.async@test.es")
    sin_cuenta = _minimo("nadie.async@test.es")

    assert con_cuenta >= SUELO_MS / 1000, (
        f"la respuesta tardó {con_cuenta:.3f}s: por debajo del suelo de "
        f"{SUELO_MS} ms el tiempo filtra si la cuenta existe"
    )
    assert abs(con_cuenta - sin_cuenta) < 0.15, (
        f"la respuesta tardó {con_cuenta:.3f}s con cuenta y {sin_cuenta:.3f}s "
        "sin ella: la diferencia delata si el correo está registrado"
    )


def test_la_tarea_borra_el_token_si_el_envio_falla(
    db_session: Session, monkeypatch,
) -> None:
    """Si el envío falla, el token se borra (nadie lo recibió)."""
    _sembrar_usuario(db_session, email="cliente.fallo@test.es")
    from app.core.security import hash_password  # noqa: F401

    fila = PasswordResetToken(
        user_id=1,
        token_hash="hash-de-prueba",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(fila)
    db_session.commit()
    token_id = fila.id

    monkeypatch.setattr(
        email_module, "send_password_reset_email", lambda **kwargs: False
    )
    # La tarea abre su propia sesion: se le da una contra el motor de
    # prueba (asi ve los mismos datos).
    SessionLocalTest = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(tasks_mod, "SessionLocal", SessionLocalTest)

    resultado = tasks_mod.enviar_correo_reset(
        to_email="cliente.fallo@test.es",
        full_name="Cliente",
        raw_token="token-bruto",
        expires_minutes=30,
        token_id=token_id,
    )
    assert resultado["enviado"] is False

    db_session.expire_all()
    assert (
        db_session.get(PasswordResetToken, token_id) is None
    ), "el token de un correo que no se envió no debe seguir válido"


def test_la_tarea_conserva_el_token_si_el_envio_va_bien(
    db_session: Session, monkeypatch,
) -> None:
    """Si el envío va bien, el token sigue ahí (el usuario lo recibió)."""
    _sembrar_usuario(db_session, email="cliente.ok@test.es")
    fila = PasswordResetToken(
        user_id=1,
        token_hash="hash-de-prueba",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(fila)
    db_session.commit()
    token_id = fila.id

    monkeypatch.setattr(
        email_module, "send_password_reset_email", lambda **kwargs: True
    )
    SessionLocalTest = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(tasks_mod, "SessionLocal", SessionLocalTest)

    resultado = tasks_mod.enviar_correo_reset(
        to_email="cliente.ok@test.es",
        full_name="Cliente",
        raw_token="token-bruto",
        expires_minutes=30,
        token_id=token_id,
    )
    assert resultado["enviado"] is True
    db_session.expire_all()
    assert db_session.get(PasswordResetToken, token_id) is not None
