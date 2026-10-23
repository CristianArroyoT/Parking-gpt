"""El correo de alerta se encola y lo manda el worker (T-103).

POR QUÉ existe este fichero: el envío del correo de alerta estaba
**dentro** de la ronda de heartbeat, con el SMTP en medio. Medido el
2026-10-23 con un SMTP de mentira (acepta la conexión y no contesta):

- **antes**: 2,42 s por alerta (7,25 s por tres) — con 50 cámaras caídas
  la ronda tardaba más de dos minutos, y el beat la lanza cada 60 s;
- **después**: 0,01 s por tres alertas. La ronda no toca la red.

Y un detalle que salió al medir: al publicar el mensaje, Celery abría
conexión con el **result store** (Redis) para reservar sitio para el
resultado. Si ese Redis no responde, la llamada se quedaba reintentando
(**23 s**, peor que el SMTP) y el que encolaba se quedaba bloqueado.
Por eso las tareas de «dispara y olvida» van con ``ignore_result=True``.

Estos tests comprueban las tres cosas: que la alerta **encola** (y no
manda), que la tarea **manda** el correo de verdad, y que las tareas de
fire-and-forget no guardan resultado.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType, UserRole
from app.models.parking import Camera, Parking
from app.models.user import User
from app.services import alerts as alerts_mod
from app.services import email as email_mod
from app.workers import tasks as tasks_mod
from tests._audit_helpers import monkeypatch_tasks_session


class _FakeRedis:
    """Redis de mentira: el contador de fallos y el lock."""

    def __init__(self) -> None:
        self.contador = 0
        self.lock = False

    def incr(self, key: str) -> int:
        self.contador += 1
        return self.contador

    def expire(self, key: str, ttl: int) -> bool:
        return True

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and self.lock:
            return None
        self.lock = True
        return True

    def delete(self, *keys: str) -> int:
        self.lock = False
        self.contador = 0
        return len(keys)

    def get(self, key: str) -> str | None:
        return None


def _camara(db: Session) -> Camera:
    parking = Parking(code="P-ASYNC", name="Async", address="x", city="y")
    db.add(parking)
    db.flush()
    # La alerta CRITICAL va al admin: sin admin, no hay destinatario.
    if db.query(User).filter(User.email == "admin-async@test.es").first() is None:
        db.add(
            User(
                email="admin-async@test.es",
                full_name="Admin",
                role=UserRole.ADMIN,
                hashed_password=hash_password("admin12345"),
            )
        )
    camara = Camera(
        parking_id=parking.id, code="CAM-ASYNC", name="Async",
        rtsp_url="rtsp://demo.invalid/a",
    )
    db.add(camara)
    db.commit()
    db.refresh(camara)
    return camara


def _alerta(db: Session) -> Alert:
    parking = db.query(Parking).first()
    if parking is None:
        parking = Parking(code="P-AL", name="Alerta", address="x", city="y")
        db.add(parking)
        db.commit()
        db.refresh(parking)
    alerta = Alert(
        parking_id=parking.id,
        type=AlertType.CAMERA_OFFLINE,
        severity=AlertSeverity.CRITICAL,
        message="camara caida",
        context={},
    )
    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta


def test_la_alerta_encola_el_correo_y_no_lo_manda(
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La alerta NO manda el correo: lo encola (lo manda el worker)."""
    # El MISMO redis de mentira en todas las llamadas: si fuera uno
    # nuevo cada vez, el contador de fallos se pondria a cero y la
    # alerta no llegaria nunca al umbral.
    fake = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)
    # ``alerts.py`` abre su propia sesion: se la apunta a la de test.
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(
        alerts_mod,
        "SessionLocal",
        sessionmaker(
            bind=db_session.get_bind(), autoflush=False, expire_on_commit=False,
        ),
    )

    enviados: list[dict[str, Any]] = []
    encolados: list[dict[str, Any]] = []

    def _fake_enviar(*args, **kwargs):
        enviados.append({"args": args, "kwargs": kwargs})
        return True

    monkeypatch.setattr(email_mod, "send_alert_email", _fake_enviar)
    monkeypatch.setattr(
        email_mod,
        "encolar_correo_alerta",
        lambda **kwargs: encolados.append(kwargs) or True,
    )

    camara = _camara(db_session)
    # Se dispara hasta pasar el umbral (3 por defecto); el lock de una
    # hora deja UNA sola alerta, y por tanto un solo correo.
    for _ in range(6):
        alerts_mod.record_camera_offline(camara)

    assert enviados == [], "el correo no debe mandarse en linea (bloquea)"
    assert len(encolados) == 1, encolados
    assert encolados[0]["template_kind"] == "camera_offline"
    assert encolados[0]["camera_code"] == "CAM-ASYNC"
    assert encolados[0]["destinatario"] == "admin-async@test.es"


def test_la_tarea_manda_el_correo_de_la_alerta(
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La tarea manda el correo de verdad, con la alerta leida de la BD."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    alerta = _alerta(db_session)

    enviados: list[dict[str, Any]] = []

    def _fake_enviar(alert, destinatario, **kwargs):
        enviados.append({"alert": alert, "destinatario": destinatario, **kwargs})
        return True

    monkeypatch.setattr(email_mod, "send_alert_email", _fake_enviar)

    resultado = tasks_mod.enviar_correo_alerta(
        alert_id=alerta.id,
        destinatario="admin@solidapp.es",
        template_kind="camera_offline",
        camera_code="CAM-01",
        count=3,
        threshold=3,
    )
    assert resultado["enviado"] is True, resultado
    assert len(enviados) == 1, enviados
    assert enviados[0]["destinatario"] == "admin@solidapp.es"
    assert enviados[0]["alert"].id == alerta.id
    assert enviados[0]["template_kind"] == "camera_offline"


def test_la_tarea_no_falla_si_la_alerta_no_existe(
    db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la alerta ya no esta (borrada), la tarea no rompe nada."""
    monkeypatch_tasks_session(monkeypatch, db_session)
    resultado = tasks_mod.enviar_correo_alerta(
        alert_id=999999, destinatario="admin@solidapp.es",
    )
    assert resultado["enviado"] is False, resultado
    assert resultado["motivo"] == "alerta_no_existe", resultado


def test_las_tareas_de_fire_and_forget_no_guardan_resultado() -> None:
    """``ignore_result=True``: publicar no abre el result store.

    Sin esto, Celery abre conexion con el result store al publicar (para
    reservar sitio para el resultado) y, si ese Redis no responde, el
    que encola se queda bloqueado reintentando: medido, **23 s** por
    envio (peor que el SMTP que queria quitar).
    """
    assert tasks_mod.enviar_correo_alerta.ignore_result is True
    assert tasks_mod.enviar_correo_reset.ignore_result is True
