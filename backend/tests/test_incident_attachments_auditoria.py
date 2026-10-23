"""La lectura de una foto de incidente deja rastro en la auditoría (T-96).

POR QUÉ existe este fichero: la auditoría registraba la **subida** y el
**borrado** de las fotos de un incidente, pero no la **lectura**. O sea:
la auditoría decía quién subió una foto de una matrícula y quién la
borró, pero no quién la **vio**. Y en un incidente por una matrícula
(más, si aparece una persona), esa es justamente la pregunta que se
hace en una revisión (LOPDGDD).

Estos tests comprueban las dos lecturas (el original y la miniatura) y
que la fila dice **quién**, **desde dónde** y **qué** photo.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests._audit_helpers import assert_audit_log, assert_no_audit_log
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
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    respuesta = _subir(
        client, token, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()[0]["id"]


def test_la_descarga_deja_rastro(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """Descargar el original deja una fila de auditoría con el usuario."""
    adjunto_id = _subir_una(client, db_session, datos)

    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 200, respuesta.text

    fila = assert_audit_log(
        db_session,
        action="incident_attachment_downloaded",
        resource=f"incident_attachment:{adjunto_id}",
        user_id=datos["gestor"].id,
        result="success",
    )
    assert fila.parking_id == datos["parking_a"].id
    assert fila.ip, "la fila debe decir desde dónde se descargó"


def test_la_miniatura_deja_rastro(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """Ver la miniatura también deja rastro (es la misma foto)."""
    adjunto_id = _subir_una(client, db_session, datos)

    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor']}"},
    )
    assert respuesta.status_code == 200, respuesta.text

    assert_audit_log(
        db_session,
        action="incident_attachment_thumbnail_viewed",
        resource=f"incident_attachment:{adjunto_id}",
        user_id=datos["gestor"].id,
        result="success",
    )


def test_una_descarga_que_no_pasa_no_deja_rastro(
    client: TestClient, db_session: Session, datos, volumen,
) -> None:
    """Lo que no se sirve, no se audita (ni ruido ni rastro falso)."""
    adjunto_id = _subir_una(client, db_session, datos)

    # Un gestor de OTRA sucursal: 403, y por tanto nada que auditar.
    respuesta = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        headers={"Authorization": f"Bearer {datos['tokens']['gestor_otro']}"},
    )
    assert respuesta.status_code == 403, respuesta.text
    assert_no_audit_log(db_session, action="incident_attachment_downloaded")
