"""Tests de los ADJUNTOS de incidentes (T-21 del plan maestro 2026-10-21).

Qué se verifica aquí:

1. **Subida**: hasta 3 fotos por incidente; el binario va al volumen
   local (nombre por hash) y en la BD sólo queda la metadata.
2. **Tipo real**: un fichero que se disfraza de imagen (extensión ``.jpg``
   y ``Content-Type: image/jpeg`` pero bytes de HTML) se rechaza con
   415. El SVG, además, no se acepta (es XML ejecutable).
3. **Tamaño**: por encima del límite se rechaza con 413.
4. **Descarga saneada**: ``Content-Type`` correcto, ``Content-Disposition:
   attachment`` y ``nosniff``. La miniatura se sirve como ``image/jpeg``
   en línea (nunca ``text/html``).
5. **RBAC**: sólo el gestor y el admin **de la sucursal** ven los
   adjuntos; el operador que los sube no puede volver a listarlos, y un
   gestor de otra sucursal tampoco.
6. **LOPDGDD**: retención (purga por antigüedad) y **derecho al olvido**
   (al borrar el usuario se borran su incidente y sus fotos, filas y
   ficheros).

Los tests corren contra el motor que marque ``TEST_DATABASE_URL``
(SQLite en memoria por defecto, PostgreSQL en la CI): no hay nada en
ellos que dependa del dialecto.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import LargeBinary

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.audit import Alert
from app.models.enums import UserRole
from app.models.incident import IncidentAttachment
from app.models.parking import Parking, ParkingSpace
from app.models.user import ParkingMembership, User
from app.services import incident_attachments as adjuntos


# ── Utilidades ──────────────────────────────────────────────────────────
def _imagen(formato: str = "JPEG", color=(200, 30, 30), size=(64, 48)) -> bytes:
    """Genera una imagen REAL (la valida Pillow, no sólo la firma)."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=formato, quality=90)
    return buffer.getvalue()


def _seed(db) -> dict[str, object]:
    admin = User(
        email="admin_adj@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    gestor = User(
        email="gestor_adj@test.es", full_name="Gestor",
        role=UserRole.GESTOR, hashed_password=hash_password("gest12345"),
    )
    gestor_otro = User(
        email="gestor_otro_adj@test.es", full_name="Gestor Otro",
        role=UserRole.GESTOR, hashed_password=hash_password("gest12345"),
    )
    operador = User(
        email="operador_adj@test.es", full_name="Operador",
        role=UserRole.OPERADOR, hashed_password=hash_password("oper12345"),
    )
    cliente = User(
        email="cliente_adj@test.es", full_name="Cliente",
        role=UserRole.CLIENTE, hashed_password=hash_password("cli12345"),
    )
    parking_a = Parking(code="P-ADJ", name="A", address="x", city="y")
    parking_b = Parking(code="P-ADJ-B", name="B", address="x", city="y")
    db.add_all([admin, gestor, gestor_otro, operador, cliente, parking_a, parking_b])
    db.flush()
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking_a.id))
    db.add(ParkingMembership(user_id=gestor_otro.id, parking_id=parking_b.id))
    db.add(ParkingMembership(user_id=operador.id, parking_id=parking_a.id))
    db.add(ParkingMembership(user_id=cliente.id, parking_id=parking_a.id))
    db.add(ParkingSpace(parking_id=parking_a.id, lane="A", number="A-01"))
    db.commit()
    for obj in (admin, gestor, gestor_otro, operador, cliente, parking_a, parking_b):
        db.refresh(obj)
    return {
        "admin": admin, "gestor": gestor, "gestor_otro": gestor_otro,
        "operador": operador, "cliente": cliente,
        "parking_a": parking_a, "parking_b": parking_b,
    }


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(email: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {email}"}


def _crear_incidente(client: TestClient, token: str, parking_id: int) -> int:
    """Crea un incidente de robo y devuelve su ``alert_id``."""
    r = client.post(
        f"/api/v1/incidents/parkings/{parking_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "robery_reported", "reason": "theft_attempt", "notes": "test"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _subir(
    client: TestClient, token: str, alert_id: int,
    ficheros: list[tuple[str, bytes, str]],
):
    return client.post(
        f"/api/v1/incidents/{alert_id}/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", (nombre, contenido, mime)) for nombre, contenido, mime in ficheros],
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
    """Semilla + tokens de todos los roles."""
    semilla = _seed(db_session)
    tokens = {
        "admin": _login(client, "admin_adj@test.es", "admin12345"),
        "gestor": _login(client, "gestor_adj@test.es", "gest12345"),
        "gestor_otro": _login(client, "gestor_otro_adj@test.es", "gest12345"),
        "operador": _login(client, "operador_adj@test.es", "oper12345"),
        "cliente": _login(client, "cliente_adj@test.es", "cli12345"),
    }
    return {**semilla, "tokens": tokens}


# ── 1. Subida y almacenamiento ──────────────────────────────────────────
def test_subida_ok_guarda_fichero_y_solo_metadata(client, db_session, datos, volumen):
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    contenido = _imagen()

    r = _subir(
        client, token, alert_id,
        [("foto.jpg", contenido, "image/jpeg")],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body) == 1
    adjunto = body[0]
    assert adjunto["mime_type"] == "image/jpeg"
    assert adjunto["size_bytes"] == len(contenido)
    assert adjunto["content_hash"] == hashlib.sha256(contenido).hexdigest()
    assert adjunto["original_filename"] == "foto.jpg"
    assert adjunto["thumbnail_url"].endswith("/thumbnail")
    assert adjunto["download_url"].endswith("/download")

    # El binario está en el volumen, con el nombre derivado del hash.
    fila = db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto["id"]
    ).one()
    ruta_original = volumen / fila.storage_path
    assert ruta_original.exists()
    assert ruta_original.read_bytes() == contenido
    assert hashlib.sha256(contenido).hexdigest() in fila.storage_path
    # Y la miniatura aparte.
    assert fila.thumbnail_path
    assert (volumen / fila.thumbnail_path).exists()

    # En la BD NO hay el binario (ni bytea, ni base64).
    assert not any(
        isinstance(column.type, LargeBinary)
        for column in IncidentAttachment.__table__.columns
    )


def test_subida_acepta_png_y_webp(client, db_session, datos):
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)

    r = _subir(
        client, token, alert_id,
        [
            ("a.png", _imagen("PNG", color=(10, 200, 10)), "image/png"),
            ("b.webp", _imagen("WEBP", color=(10, 10, 200)), "image/webp"),
        ],
    )
    assert r.status_code == 201, r.text
    mimes = {a["mime_type"] for a in r.json()}
    assert mimes == {"image/png", "image/webp"}


def test_tipo_falsificado_se_rechaza(client, db_session, datos, volumen):
    """Un HTML disfrazado de foto (extensión y Content-Type falsos)."""
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    html = b"<html><script>alert('xss')</script></html>"

    r = _subir(
        client, token, alert_id,
        [("foto.jpg", html, "image/jpeg")],
    )
    assert r.status_code == 415, r.text
    assert db_session.query(IncidentAttachment).count() == 0
    # No se dejó nada en el volumen.
    assert not list(volumen.rglob("*.jpg"))


def test_png_falsificado_se_rechaza(client, db_session, datos):
    """Firma de PNG correcta pero contenido basura: lo rechaza Pillow."""
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    falso = b"\x89PNG\r\n\x1a\n" + b"esto no es una imagen"

    r = _subir(
        client, token, alert_id,
        [("trucada.png", falso, "image/png")],
    )
    assert r.status_code == 415, r.text
    assert db_session.query(IncidentAttachment).count() == 0


def test_svg_se_rechaza(client, db_session, datos):
    """El SVG es XML ejecutable: no se admite como adjunto."""
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    r = _subir(
        client, token, alert_id,
        [("vector.svg", svg, "image/svg+xml")],
    )
    assert r.status_code == 415, r.text
    assert db_session.query(IncidentAttachment).count() == 0


def test_maximo_tres_ficheros_por_peticion(client, db_session, datos):
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)

    r = _subir(
        client, token, alert_id,
        [
            (f"f{i}.jpg", _imagen(color=(i * 10, 0, 0)), "image/jpeg")
            for i in range(4)
        ],
    )
    assert r.status_code == 400, r.text
    assert db_session.query(IncidentAttachment).count() == 0


def test_maximo_tres_ficheros_en_total(client, db_session, datos):
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)

    r1 = _subir(
        client, token, alert_id,
        [
            ("a.jpg", _imagen(color=(1, 0, 0)), "image/jpeg"),
            ("b.jpg", _imagen(color=(2, 0, 0)), "image/jpeg"),
        ],
    )
    assert r1.status_code == 201, r1.text

    r2 = _subir(
        client, token, alert_id,
        [
            ("c.jpg", _imagen(color=(3, 0, 0)), "image/jpeg"),
            ("d.jpg", _imagen(color=(4, 0, 0)), "image/jpeg"),
        ],
    )
    assert r2.status_code == 400, r2.text
    assert db_session.query(IncidentAttachment).count() == 2


def test_tamano_maximo(client, db_session, datos, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "incident_attachment_max_bytes", 512)
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)

    r = _subir(
        client, token, alert_id,
        [("grande.jpg", _imagen(size=(400, 400)), "image/jpeg")],
    )
    assert r.status_code == 413, r.text
    assert db_session.query(IncidentAttachment).count() == 0


def test_subida_sin_token_401(client, datos):
    r = client.post(
        f"/api/v1/incidents/{_crear_incidente(client, datos['tokens']['operador'], datos['parking_a'].id)}/attachments",
        files=[("files", ("foto.jpg", _imagen(), "image/jpeg"))],
    )
    assert r.status_code == 401


def test_cliente_no_puede_subir(client, datos):
    token = datos["tokens"]["cliente"]
    alert_id = _crear_incidente(client, datos["tokens"]["operador"], datos["parking_a"].id)
    r = _subir(client, token, alert_id, [("foto.jpg", _imagen(), "image/jpeg")])
    assert r.status_code == 403


def test_operador_no_puede_subir_a_otra_sucursal(client, datos):
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    # El operador no es miembro de la sucursal B: no puede subir allí.
    alerta_b = Alert(
        parking_id=datos["parking_b"].id,
        type="robery_reported",
        severity="critical",
        message="incidente en B",
        context={},
    )
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        db.add(alerta_b)
        db.commit()
        db.refresh(alerta_b)
        id_b = alerta_b.id

    r = _subir(client, token, id_b, [("foto.jpg", _imagen(), "image/jpeg")])
    assert r.status_code == 403


# ── 2. Listado, descarga y miniatura ────────────────────────────────────
def test_gestor_lista_descarga_y_miniatura(client, db_session, datos):
    token_oper = datos["tokens"]["operador"]
    token_gestor = datos["tokens"]["gestor"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    contenido = _imagen()
    subida = _subir(client, token_oper, alert_id, [("foto.jpg", contenido, "image/jpeg")])
    assert subida.status_code == 201, subida.text
    adjunto_id = subida.json()[0]["id"]

    # Listado (sólo gestor/admin).
    r_list = client.get(
        f"/api/v1/incidents/{alert_id}/attachments",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert r_list.status_code == 200, r_list.text
    assert len(r_list.json()) == 1

    # Descarga: tipo correcto, como adjunto y con nosniff.
    r = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert "attachment" in r.headers["content-disposition"]
    assert "foto.jpg" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content == contenido

    # Miniatura: JPEG en línea, y más pequeña que el original.
    r_thumb = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert r_thumb.status_code == 200, r_thumb.text
    assert r_thumb.headers["content-type"] == "image/jpeg"
    assert "inline" in r_thumb.headers["content-disposition"]
    assert r_thumb.headers["x-content-type-options"] == "nosniff"
    assert r_thumb.content[:2] == b"\xff\xd8"
    assert len(r_thumb.content) < len(contenido)


def test_no_se_sirve_nunca_como_html(client, datos):
    token_oper = datos["tokens"]["operador"]
    token_gestor = datos["tokens"]["gestor"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]

    for url in (
        f"/api/v1/incidents/attachments/{adjunto_id}/download",
        f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail",
    ):
        r = client.get(url, headers={"Authorization": f"Bearer {token_gestor}"})
        assert r.status_code == 200
        assert "text/html" not in r.headers["content-type"]


def test_operador_no_puede_listar_ni_descargar(client, datos):
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]
    cabeceras = {"Authorization": f"Bearer {token_oper}"}

    r = client.get(f"/api/v1/incidents/{alert_id}/attachments", headers=cabeceras)
    assert r.status_code == 403
    r = client.get(f"/api/v1/incidents/attachments/{adjunto_id}/download", headers=cabeceras)
    assert r.status_code == 403
    r = client.get(f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail", headers=cabeceras)
    assert r.status_code == 403


def test_gestor_de_otra_sucursal_no_puede_ver(client, datos):
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]
    cabeceras = {"Authorization": f"Bearer {datos['tokens']['gestor_otro']}"}

    r = client.get(f"/api/v1/incidents/{alert_id}/attachments", headers=cabeceras)
    assert r.status_code == 403
    r = client.get(f"/api/v1/incidents/attachments/{adjunto_id}/download", headers=cabeceras)
    assert r.status_code == 403


def test_miniatura_por_query_token(client, datos):
    """El ``<img>`` del navegador no puede mandar cabeceras."""
    token_oper = datos["tokens"]["operador"]
    token_gestor = datos["tokens"]["gestor"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]

    r = client.get(
        f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail?token={token_gestor}"
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"

    # Sin token: 401.
    r = client.get(f"/api/v1/incidents/attachments/{adjunto_id}/thumbnail")
    assert r.status_code == 401


# ── 3. LOPDGDD: retención y derecho al olvido ───────────────────────────
def test_derecho_al_olvido_borra_incidente_y_fotos(client, db_session, datos, volumen):
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    assert subida.status_code == 201, subida.text
    fila = db_session.query(IncidentAttachment).one()
    ruta_original = volumen / fila.storage_path
    assert ruta_original.exists()

    # Se borra el usuario que reportó el incidente.
    db_session.delete(datos["operador"])
    db_session.commit()

    # Ya no está la foto (fila) ni el fichero (disco).
    assert db_session.query(IncidentAttachment).count() == 0
    assert not ruta_original.exists()
    # Ni el incidente que reportó.
    assert db_session.query(Alert).filter(Alert.id == alert_id).count() == 0


def test_purga_por_retencion(client, db_session, datos, volumen):
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]
    fila = db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto_id
    ).one()
    ruta_original = volumen / fila.storage_path

    # Envejecemos la foto 200 días (más que la retención de 90).
    db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto_id
    ).update({"created_at": datetime.now(timezone.utc) - timedelta(days=200)})
    db_session.commit()

    resultado = adjuntos.purgar_adjuntos_vencidos(db_session, retention_days=90)
    assert resultado["deleted"] == 1
    assert db_session.query(IncidentAttachment).count() == 0
    assert not ruta_original.exists()


def test_retencion_no_borra_fotos_recientes(client, db_session, datos, volumen):
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    _subir(client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")])

    resultado = adjuntos.purgar_adjuntos_vencidos(db_session, retention_days=90)
    assert resultado["deleted"] == 0
    assert db_session.query(IncidentAttachment).count() == 1
    assert list(volumen.rglob("*.jpg"))


def test_purga_de_huerfanos_limpia_ficheros_sin_fila(client, db_session, datos, volumen):
    """Red de seguridad: fichero en disco sin fila en la BD."""
    token_oper = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]
    fila = db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto_id
    ).one()
    ruta_original = volumen / fila.storage_path

    # Se borra la fila "a mano" (como si la BD se hubiera desincronizado).
    db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto_id
    ).delete(synchronize_session=False)
    db_session.commit()
    assert ruta_original.exists()

    resultado = adjuntos.purgar_ficheros_huerfanos(db_session)
    assert resultado["deleted"] >= 1
    assert not ruta_original.exists()


def test_borrado_explicito_de_un_adjunto(client, db_session, datos, volumen):
    token_oper = datos["tokens"]["operador"]
    token_gestor = datos["tokens"]["gestor"]
    alert_id = _crear_incidente(client, token_oper, datos["parking_a"].id)
    subida = _subir(
        client, token_oper, alert_id, [("foto.jpg", _imagen(), "image/jpeg")]
    )
    adjunto_id = subida.json()[0]["id"]
    fila = db_session.query(IncidentAttachment).filter(
        IncidentAttachment.id == adjunto_id
    ).one()
    ruta_original = volumen / fila.storage_path

    r = client.delete(
        f"/api/v1/incidents/attachments/{adjunto_id}",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert r.status_code == 204, r.text
    assert db_session.query(IncidentAttachment).count() == 0
    assert not ruta_original.exists()


def test_nombre_de_fichero_saneado(client, db_session, datos, volumen):
    """El nombre original no puede traer rutas ni comillas."""
    token = datos["tokens"]["operador"]
    alert_id = _crear_incidente(client, token, datos["parking_a"].id)
    r = _subir(
        client, token, alert_id,
        [("../../etc/pa\"sswd.jpg", _imagen(), "image/jpeg")],
    )
    assert r.status_code == 201, r.text
    nombre = r.json()[0]["original_filename"]
    assert "/" not in nombre
    assert '"' not in nombre
    assert nombre.endswith(".jpg")
