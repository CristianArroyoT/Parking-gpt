"""Tests del router de operadores acotado por sucursal (T-20).

Lo que se fija aquí, en orden de importancia:

1. Un gestor **sólo** puede actuar sobre sucursales de las que es miembro
   (403 en caso contrario).
2. El rol creado es **siempre** ``operador``: el payload no tiene campo
   ``role``, así que un gestor no puede crear un admin.
3. El operador creado **sólo** queda en esa sucursal.
4. Un operador o un cliente no pueden usar estos endpoints (403).
5. Los endpoints de admin (``/users``) **siguen** siendo admin-only: este
   router no los ha abierto.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import ParkingMembership, User
from tests._audit_helpers import (
    _login,
    _seed_admin,
    _seed_cliente,
    _seed_gestor,
    _seed_parking,
)


def _membresia(db: Session, user_id: int, parking_id: int) -> None:
    db.add(ParkingMembership(user_id=user_id, parking_id=parking_id))
    db.commit()


def _alta(
    client: TestClient, token: str, parking_id: int, email: str = "op@nuevo.es"
):
    return client.post(
        f"/api/v1/parkings/{parking_id}/operadores",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": email,
            "full_name": "Operador Nuevo",
            "password": "clave-larga-1",
            "phone": "+34 600 111 222",
        },
    )


def test_el_gestor_da_de_alta_un_operador_en_su_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """El wireframe del gestor pide poder dar de alta operadores."""
    parking = _seed_parking(db_session, code="P-GEST-1")
    gestor = _seed_gestor(db_session, email="gestor@g1.es")
    _membresia(db_session, gestor.id, parking.id)
    token = _login(client, gestor.email, "gestor1234")

    r = _alta(client, token, parking.id)

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["role"] == "operador"
    assert cuerpo["email"] == "op@nuevo.es"
    assert cuerpo["is_active"] is True

    # Queda como miembro de esa sucursal.
    memberias = (
        db_session.query(ParkingMembership)
        .filter(ParkingMembership.user_id == cuerpo["id"])
        .all()
    )
    assert [m.parking_id for m in memberias] == [parking.id]


def test_el_gestor_no_puede_actuar_sobre_otra_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """La membresía es la frontera: 403 si la sucursal no es suya."""
    parking_propia = _seed_parking(db_session, code="P-GEST-2")
    parking_ajena = _seed_parking(db_session, code="P-GEST-3")
    gestor = _seed_gestor(db_session, email="gestor@g2.es")
    _membresia(db_session, gestor.id, parking_propia.id)
    token = _login(client, gestor.email, "gestor1234")

    r = _alta(client, token, parking_ajena.id, email="op@ajeno.es")

    assert r.status_code == 403
    # Y no se ha creado ningún usuario.
    assert (
        db_session.query(User).filter(User.email == "op@ajeno.es").one_or_none()
        is None
    )


def test_el_rol_no_se_puede_elegir(client: TestClient, db_session: Session) -> None:
    """El payload no tiene ``role``: aunque se mande, se ignora."""
    parking = _seed_parking(db_session, code="P-GEST-4")
    gestor = _seed_gestor(db_session, email="gestor@g3.es")
    _membresia(db_session, gestor.id, parking.id)
    token = _login(client, gestor.email, "gestor1234")

    r = client.post(
        f"/api/v1/parkings/{parking.id}/operadores",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "intruso@g3.es",
            "full_name": "Intruso",
            "password": "clave-larga-1",
            "role": "admin",  # se ignora
            "is_active": False,  # se ignora
        },
    )

    assert r.status_code == 201, r.text
    assert r.json()["role"] == "operador"
    assert r.json()["is_active"] is True


def test_un_operador_o_un_cliente_no_pueden_gestionar_operadores(
    client: TestClient, db_session: Session
) -> None:
    """Sólo admin y gestor entran en este router."""
    parking = _seed_parking(db_session, code="P-GEST-5")
    operador = User(
        email="op@g4.es",
        full_name="Operador",
        role=UserRole.OPERADOR,
        hashed_password=hash_password("operador1234"),
    )
    db_session.add(operador)
    db_session.commit()
    _membresia(db_session, operador.id, parking.id)

    cliente = _seed_cliente(db_session, email="cli@g4.es")
    _membresia(db_session, cliente.id, parking.id)

    for email, password in (
        ("op@g4.es", "operador1234"),
        ("cli@g4.es", "cliente1234"),
    ):
        token = _login(client, email, password)
        r = _alta(client, token, parking.id, email=f"nuevo-{email}")
        assert r.status_code == 403, f"{email} pudo crear un operador: {r.text}"


def test_el_listado_solo_muestra_los_operadores_de_esa_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """Ni los clientes de la sucursal ni los de otras aparecen."""
    parking = _seed_parking(db_session, code="P-GEST-6")
    otra = _seed_parking(db_session, code="P-GEST-7")
    gestor = _seed_gestor(db_session, email="gestor@g5.es")
    _membresia(db_session, gestor.id, parking.id)
    token = _login(client, gestor.email, "gestor1234")

    # Operador de esta sucursal.
    creado = _alta(client, token, parking.id, email="op@listado.es")
    assert creado.status_code == 201

    # Operador de otra sucursal: no debe salir.
    gestor_otro = _seed_gestor(db_session, email="gestor@otro.es")
    _membresia(db_session, gestor_otro.id, otra.id)
    token_otro = _login(client, gestor_otro.email, "gestor1234")
    _alta(client, token_otro, otra.id, email="op@otra.es")

    r = client.get(
        f"/api/v1/parkings/{parking.id}/operadores",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    emails = [u["email"] for u in r.json()]
    assert "op@listado.es" in emails
    assert "op@otra.es" not in emails


def test_el_email_duplicado_da_409(client: TestClient, db_session: Session) -> None:
    """No se pueden crear dos operadores con el mismo email."""
    parking = _seed_parking(db_session, code="P-GEST-8")
    gestor = _seed_gestor(db_session, email="gestor@g6.es")
    _membresia(db_session, gestor.id, parking.id)
    token = _login(client, gestor.email, "gestor1234")

    assert _alta(client, token, parking.id, email="dup@g6.es").status_code == 201
    r = _alta(client, token, parking.id, email="dup@g6.es")
    assert r.status_code == 409


def test_los_endpoints_de_admin_siguen_siendo_admin_only(
    client: TestClient, db_session: Session
) -> None:
    """Este router NO abre ``/users``: el gestor sigue sin poder listarlos."""
    parking = _seed_parking(db_session, code="P-GEST-9")
    gestor = _seed_gestor(db_session, email="gestor@g7.es")
    _membresia(db_session, gestor.id, parking.id)
    token = _login(client, gestor.email, "gestor1234")

    assert client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    r = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "admin@forjado.es",
            "full_name": "Admin Forjado",
            "password": "clave-larga-1",
            "role": "admin",
        },
    )
    assert r.status_code == 403


def test_el_admin_tambien_puede_usar_el_router(
    client: TestClient, db_session: Session
) -> None:
    """El admin no pierde capacidades: puede usar el router acotado."""
    parking = _seed_parking(db_session, code="P-GEST-10")
    admin = _seed_admin(db_session, email="admin@g8.es")
    token = _login(client, admin.email, "admin12345")

    r = _alta(client, token, parking.id, email="op@admin.es")
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "operador"
