"""Tests de la estructura preparada de reconocimiento facial (T-23).

**El reconocimiento facial está fuera del MVP.** Estos tests comprueban
justo eso:

  1. La tabla ``face_templates`` existe (modelo + migración).
  2. Los endpoints de alta/baja están **deshabilitados por feature flag**
     (con el flag apagado responden **404**) y no se puede escribir nada.
  3. Con el flag activo, el alta/baja funcionan (estructura preparada).
  4. **El login NO usa las plantillas**: el acceso sigue siendo usuario +
     contraseña y ninguna ruta de autenticación lee esa tabla.
  5. El README lo dice de forma explícita.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.face_template import FaceTemplate
from app.models.parking import Camera
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_parking,
    assert_audit_log,
    assert_no_audit_log,
)


@pytest.fixture()
def biometria_activa(monkeypatch) -> None:
    """Activa el feature flag ``FACE_TEMPLATES_ENABLED`` para el test."""
    monkeypatch.setattr(get_settings(), "face_templates_enabled", True)


def _crear_camara(db_session: Session, *, code: str = "CAM-FT") -> Camera:
    parking = _seed_parking(db_session, code=f"P-{code}")
    camara = Camera(
        parking_id=parking.id,
        code=code,
        name=f"Cámara {code}",
        rtsp_url="rtsp://localhost/test",
    )
    db_session.add(camara)
    db_session.commit()
    db_session.refresh(camara)
    return camara


# ── 1 · la estructura existe ───────────────────────────────────────────────


def test_el_flag_esta_apagado_por_defecto() -> None:
    """Sin ``FACE_TEMPLATES_ENABLED`` en el entorno, el flag es ``False``."""
    assert get_settings().face_templates_enabled is False


def test_el_modelo_tiene_los_campos_pedidos() -> None:
    """Usuario, embedding, cámara y fecha (created_at)."""
    columnas = FaceTemplate.__table__.columns
    assert "user_id" in columnas
    assert "embedding" in columnas
    assert "camera_id" in columnas
    assert "created_at" in columnas


# ── 2 · con el flag apagado todo responde 404 ──────────────────────────────


def test_alta_devuelve_404_con_el_flag_apagado(
    client: TestClient, db_session: Session,
) -> None:
    """Con el flag apagado, el alta no existe (404) y no se escribe nada."""
    _seed_admin(db_session, email="admin@test.es")
    headers = _login_headers(client, "admin@test.es", "admin12345")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1, 0.2, 0.3]},
        headers=headers,
    )

    assert r.status_code == 404, r.text
    db_session.expire_all()
    assert db_session.query(FaceTemplate).count() == 0


def test_baja_devuelve_404_con_el_flag_apagado(
    client: TestClient, db_session: Session,
) -> None:
    """Con el flag apagado, la baja tampoco existe."""
    _seed_admin(db_session, email="admin@test.es")
    headers = _login_headers(client, "admin@test.es", "admin12345")

    r = client.delete("/api/v1/face-templates/1", headers=headers)

    assert r.status_code == 404, r.text


def test_con_el_flag_apagado_no_se_audita(
    client: TestClient, db_session: Session,
) -> None:
    """El corte por feature flag ocurre antes del handler: no hay ruido en
    ``audit_logs`` por una funcionalidad que no existe."""
    _seed_admin(db_session, email="admin@test.es")
    headers = _login_headers(client, "admin@test.es", "admin12345")

    client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1, 0.2]},
        headers=headers,
    )

    assert_no_audit_log(db_session, action="create_face_template")


def test_sin_autenticacion_tampoco_hay_template(
    client: TestClient, db_session: Session,
) -> None:
    """Sin token, la respuesta es 401 (o 404 si el flag está apagado)."""
    r = client.post("/api/v1/face-templates", json={"embedding": [0.1]})
    assert r.status_code in (401, 404), r.text


# ── 3 · con el flag activo, la estructura funciona ─────────────────────────


def test_alta_crea_el_template(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """El alta guarda usuario, embedding, dimensión y fecha."""
    _seed_cliente(db_session, email="cli@test.es")
    headers = _login_headers(client, "cli@test.es", "cliente1234")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1, 0.2, 0.3]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["dimension"] == 3
    assert cuerpo["camera_id"] is None

    db_session.expire_all()
    fila = db_session.query(FaceTemplate).one()
    assert fila.embedding == [0.1, 0.2, 0.3]
    assert fila.dimension == 3
    assert fila.created_at is not None


def test_el_template_es_del_usuario_autenticado(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """El ``user_id`` sale de la sesión: nadie da de alta una biometría
    en nombre de otro (aunque lo mande en el body, se ignora)."""
    _seed_cliente(db_session, email="dueno@test.es")
    _seed_cliente(db_session, email="otro@test.es")
    headers = _login_headers(client, "dueno@test.es", "cliente1234")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.5], "user_id": 999},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    db_session.expire_all()
    fila = db_session.query(FaceTemplate).one()
    assert fila.user_id != 999
    dueno = db_session.query(FaceTemplate).one()
    assert dueno.id == fila.id


def test_alta_con_camara_de_la_sucursal(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """Se puede asociar el template a una cámara de la que el usuario es
    miembro (o a la que el admin tiene acceso)."""
    admin = _seed_admin(db_session, email="admin-cam@test.es")
    camara = _crear_camara(db_session)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1, 0.2], "camera_id": camara.id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["camera_id"] == camara.id


def test_alta_con_camara_inexistente(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """Una cámara que no existe → 404."""
    _seed_admin(db_session, email="admin-cam2@test.es")
    headers = _login_headers(client, "admin-cam2@test.es", "admin12345")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1], "camera_id": 9999},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_alta_con_camara_de_otra_sucursal(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """Un cliente sin membresía no puede colgar su template de una cámara
    ajena → 403."""
    _seed_cliente(db_session, email="intruso@test.es")
    camara = _crear_camara(db_session)
    headers = _login_headers(client, "intruso@test.es", "cliente1234")

    r = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1], "camera_id": camara.id},
        headers=headers,
    )
    assert r.status_code == 403, r.text


def test_baja_de_un_template_propio(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """El propietario puede dar de baja su template."""
    _seed_cliente(db_session, email="baja@test.es")
    headers = _login_headers(client, "baja@test.es", "cliente1234")

    alta = client.post(
        "/api/v1/face-templates", json={"embedding": [0.1]}, headers=headers,
    )
    assert alta.status_code == 201, alta.text
    template_id = alta.json()["id"]

    r = client.delete(f"/api/v1/face-templates/{template_id}", headers=headers)
    assert r.status_code == 204, r.text

    db_session.expire_all()
    assert db_session.query(FaceTemplate).count() == 0


def test_baja_de_un_template_ajeno_da_404(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """No se puede borrar el template de otro usuario (404, sin revelar)."""
    _seed_cliente(db_session, email="dueno2@test.es")
    _seed_cliente(db_session, email="tercero@test.es")
    headers_dueno = _login_headers(client, "dueno2@test.es", "cliente1234")

    alta = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1]},
        headers=headers_dueno,
    )
    assert alta.status_code == 201, alta.text
    template_id = alta.json()["id"]

    headers_tercero = _login_headers(client, "tercero@test.es", "cliente1234")
    r = client.delete(
        f"/api/v1/face-templates/{template_id}", headers=headers_tercero,
    )
    assert r.status_code == 404, r.text


def test_un_admin_puede_borrar_cualquier_template(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """El admin sí puede limpiar templates de otros usuarios."""
    _seed_cliente(db_session, email="dueno3@test.es")
    admin = _seed_admin(db_session, email="admin-borrar@test.es")
    headers_dueno = _login_headers(client, "dueno3@test.es", "cliente1234")

    alta = client.post(
        "/api/v1/face-templates",
        json={"embedding": [0.1]},
        headers=headers_dueno,
    )
    template_id = alta.json()["id"]

    headers_admin = _login_headers(client, admin.email, "admin12345")
    r = client.delete(f"/api/v1/face-templates/{template_id}", headers=headers_admin)
    assert r.status_code == 204, r.text


def test_el_alta_se_audita(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """Con el flag activo, el alta queda auditada."""
    _seed_cliente(db_session, email="audit-ft@test.es")
    headers = _login_headers(client, "audit-ft@test.es", "cliente1234")

    r = client.post(
        "/api/v1/face-templates", json={"embedding": [0.1]}, headers=headers,
    )
    assert r.status_code == 201, r.text

    assert_audit_log(db_session, action="create_face_template", result="success")


# ── 4 · el login NO usa las plantillas ─────────────────────────────────────


def test_el_login_sigue_siendo_usuario_contrasena(
    client: TestClient, db_session: Session, biometria_activa: None,
) -> None:
    """Aunque haya un template, el login sólo depende de la contraseña."""
    _seed_cliente(db_session, email="login-ft@test.es", password="clave-original-1")
    headers = _login_headers(client, "login-ft@test.es", "clave-original-1")

    alta = client.post(
        "/api/v1/face-templates", json={"embedding": [0.1, 0.2]}, headers=headers,
    )
    assert alta.status_code == 201, alta.text

    # El login funciona con usuario + contraseña.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "login-ft@test.es", "password": "clave-original-1"},
    )
    assert r.status_code == 200, r.text

    # Y sigue fallando si la contraseña no es la correcta: la plantilla
    # no sirve como sustituto de la contraseña.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "login-ft@test.es", "password": "clave-incorrecta"},
    )
    assert r.status_code == 401, r.text


def test_ninguna_ruta_de_autenticacion_usa_face_templates() -> None:
    """Comprobación estática: el camino de autenticación no menciona la
    tabla de biometría (ni el login ni el hashing de contraseñas)."""
    backend = Path(__file__).resolve().parents[1]
    for relativo in (
        "app/api/v1/auth.py",
        "app/core/security.py",
        "app/core/deps.py",
    ):
        contenido = (backend / relativo).read_text(encoding="utf-8").lower()
        assert "face_template" not in contenido, (
            f"{relativo} no debe hacer referencia a la tabla face_templates"
        )
        assert "facetemplate" not in contenido, (
            f"{relativo} no debe hacer referencia al modelo FaceTemplate"
        )


# ── 5 · el README lo documenta de forma explícita ─────────────────────────


def _buscar_readme() -> Path | None:
    """Busca el README.md del repo subiendo desde el fichero de test.

    En el contenedor de desarrollo sólo se monta ``backend/``, así que el
    README puede no estar disponible: en ese caso el test se salta (en la
    CI, que checkout el repo completo, sí se ejecuta).
    """
    here = Path(__file__).resolve()
    for carpeta in here.parents:
        candidato = carpeta / "README.md"
        if candidato.is_file():
            return candidato
    return None


def test_el_readme_dice_que_el_reconocimiento_facial_esta_fuera_del_mvp() -> None:
    """La nota del README es explícita (criterio de aceptación del ítem)."""
    readme_path = _buscar_readme()
    if readme_path is None:
        pytest.skip("README.md no disponible en este entorno")
    minusculas = readme_path.read_text(encoding="utf-8").lower()
    assert "reconocimiento facial" in minusculas
    assert "fuera del mvp" in minusculas
    # El feature flag y el 404 también están documentados.
    assert "face_templates_enabled" in minusculas
