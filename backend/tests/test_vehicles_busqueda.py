"""La búsqueda de matrículas no trata los comodines de LIKE como comodines (T-93).

POR QUÉ existe este fichero: el filtro era
``Vehicle.plate.ilike(f"%{plate}%")``, con el texto del usuario metido en
el patrón. Eso convierte los comodines de LIKE en comodines de verdad:

- ``?plate=%`` devolvía **todos** los vehículos de la flota;
- ``?plate=______`` hacía wildcard sobre cualquier matrícula de 6
  caracteres.

Con un rol de staff (admin, gestor u operador) la "búsqueda" era un
comodín para enumerar las matrículas enteras y para escanear la tabla.

El valor sigue yendo ligado como parámetro (no es inyección SQL: eso lo
hace SQLAlchemy); lo que se escapa aquí son los comodines **del propio
LIKE**, para que el usuario busque el texto que escribe.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests._audit_helpers import _login_headers, _seed_admin

MATRICULAS = ("1234ABC", "5678DEF", "9012GHI")


def _sembrar(client: TestClient, db_session: Session) -> dict[str, str]:
    """Crea tres vehículos y devuelve las cabeceras de un admin."""
    admin = _seed_admin(db_session)
    headers = _login_headers(client, admin.email, "admin12345")
    for matricula in MATRICULAS:
        respuesta = client.post(
            "/api/v1/vehicles",
            json={"plate": matricula, "brand": "Renault"},
            headers=headers,
        )
        assert respuesta.status_code == 201, respuesta.text
    return headers


def test_el_porcentaje_no_devuelve_toda_la_flota(
    client: TestClient, db_session: Session,
) -> None:
    """``?plate=%`` no puede ser un comodín."""
    headers = _sembrar(client, db_session)
    respuesta = client.get("/api/v1/vehicles?plate=%25", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == [], (
        "el porcentaje debe buscarse como un caracter literal, no como "
        "comodin: devolvio toda la flota"
    )


def test_el_subrayado_no_hace_wildcard(
    client: TestClient, db_session: Session,
) -> None:
    """``?plate=______`` no puede hacer wildcard sobre 6 caracteres."""
    headers = _sembrar(client, db_session)
    respuesta = client.get("/api/v1/vehicles?plate=______", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == [], (
        "el subrayado debe buscarse como un caracter literal, no como "
        "comodin de un caracter"
    )


def test_la_busqueda_normal_sigue_funcionando(
    client: TestClient, db_session: Session,
) -> None:
    """Buscar una parte de la matrícula sigue devuelve lo que debe."""
    headers = _sembrar(client, db_session)
    respuesta = client.get("/api/v1/vehicles?plate=34AB", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    matriculas = [v["plate"] for v in respuesta.json()]
    assert matriculas == ["1234ABC"], respuesta.text


def test_un_comodin_literal_si_se_encuentra(
    client: TestClient, db_session: Session,
) -> None:
    """Si una matrícula lleva un ``%`` de verdad, se encuentra con ``%``."""
    headers = _sembrar(client, db_session)
    respuesta = client.post(
        "/api/v1/vehicles",
        json={"plate": "50%50"},
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text

    respuesta = client.get("/api/v1/vehicles?plate=%25", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    matriculas = [v["plate"] for v in respuesta.json()]
    assert matriculas == ["50%50"], respuesta.text


def test_el_texto_largo_se_rechaza(
    client: TestClient, db_session: Session,
) -> None:
    """Un patrón de más de 16 caracteres se rechaza (422)."""
    headers = _sembrar(client, db_session)
    respuesta = client.get("/api/v1/vehicles?plate=" + "A" * 40, headers=headers)
    assert respuesta.status_code == 422, respuesta.text
