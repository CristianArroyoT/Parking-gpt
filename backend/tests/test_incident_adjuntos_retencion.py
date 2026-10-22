"""La retención de las fotos de incidentes se aplica al leer (T-95).

POR QUÉ existe este fichero: la retención (90 días por defecto, por
minimización de datos) se calculaba al subir el adjunto (``expires_at``)
pero **nadie lo comprobaba al descargarlo**: la foto se servía igual
aunque su plazo hubiera vencido. Y la purga era un script manual, sin
tarea que lo llamara: nadie se acordaba de lanzarlo.

Estos tests comprueban las dos mitades:

1. **al leer**: un adjunto caducado da **410 Gone** (ni la foto ni su
   miniatura), y uno vigente se sigue sirviendo;
2. **al purgar**: la tarea de Celery borra los caducados y deja los
   vigentes.

Y que el ``DELETE`` siga funcionando con un adjunto caducado: para eso
está (para limpiarlo).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import pytest

from app.core.config import get_settings
from app.models.incident import IncidentAttachment
from app.workers import tasks as tasks_mod
from tests.test_incident_attachments import (
    _crear_incidente,
    _imagen,
    _login,
    _seed,
    _subir,
)


@pytest.fixture()
def volumen(tmp_path, monkeypatch):
    """Apunta el volumen de adjuntos a un directorio temporal."""
    settings = get_settings()
    ruta = tmp_path / "adjuntos"
    ruta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "incident_attachments_dir", str(ruta))
    return ruta


@pytest.fixture()
def datos(client: TestClient, db_session, volumen):
    """Semilla + tokens (los mismos roles que el resto de tests de adjuntos)."""
    semilla = _seed(db_session)
    tokens = {
        "admin": _login(client, "admin_adj@test.es", "admin12345"),
        "gestor": _login(client, "gestor_adj@test.es", "gest12345"),
        "gestor_otro": _login(client, "gestor_otro_adj@test.es", "gest12345"),
        "operador": _login(client, "operador_adj@test.es", "oper12345"),
        "cliente": _login(client, "cliente_adj@test.es", "cli12345"),
    }
    return {**semilla, "tokens": tokens}


def _subir_una(client: TestClient, db_session: Session, datos) -> int:
    """Sube una foto y devuelve el id del adjunto."""
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    respuesta = _subir(
        client, token, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()[0]["id"]


def _caducar(db_session: Session, adjunto_id: int) -> None:
    """Pone el ``expires_at`` del adjunto en el pasado."""
    fila = db_session.get(IncidentAttachment, adjunto_id)
    assert fila is not None
    fila.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()


def test_un_adjunto_caducado_no_se_descarga(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """Un adjunto caducado da 410 Gone (no se sirve el binario)."""
    adjunto_id = _subir_una(client, db_session, datos)
    _caducar(db_session, adjunto_id)

    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 410, respuesta.text


def test_un_adjunto_caducado_no_sirve_miniatura(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """La miniatura tampoco se sirve (también es la foto de la persona)."""
    adjunto_id = _subir_una(client, db_session, datos)
    _caducar(db_session, adjunto_id)

    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 410, respuesta.text


def test_un_adjunto_vigente_si_se_descarga(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """Un adjunto en plazo se sigue sirviendo (el arreglo no rompe nada)."""
    adjunto_id = _subir_una(client, db_session, datos)

    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 200, respuesta.text


def test_un_adjunto_caducado_si_se_puede_borrar(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """El DELETE de un adjunto caducado sigue funcionando (para limpiarlo)."""
    adjunto_id = _subir_una(client, db_session, datos)
    _caducar(db_session, adjunto_id)

    respuesta = client.delete(
        f"/api/v1/incidents/attachments/{adjunto_id}",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 204, respuesta.text


def test_la_tarea_de_purga_borra_los_caducados(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """La tarea programada borra los caducados y deja los vigentes."""
    caducado = _subir_una(client, db_session, datos)
    vigente = _subir_una(client, db_session, datos)
    _caducar(db_session, caducado)

    SessionLocalTest = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    original = tasks_mod.SessionLocal
    tasks_mod.SessionLocal = SessionLocalTest
    try:
        # Sin argumentos, como la llama el beat: el criterio es
        # ``expires_at`` (el mismo que usa el endpoint al servir).
        resultado = tasks_mod.purgar_adjuntos_incidentes()
    finally:
        tasks_mod.SessionLocal = original

    assert resultado.get("deleted", 0) >= 1, resultado
    db_session.expire_all()
    assert db_session.get(IncidentAttachment, caducado) is None, (
        "la purga debe borrar el adjunto caducado"
    )
    assert db_session.get(IncidentAttachment, vigente) is not None, (
        "la purga NO debe tocar un adjunto en plazo"
    )
