"""RBAC por sucursal (T-178, ADR 0005).

El **rol global es el techo** y el rol de la sucursal
(``parking_memberships.role_in_parking``) es el **poder real**: el rol
efectivo en una sucursal es el **más restrictivo** entre los dos
(jerarquía ``admin > gestor > operador > cliente``).

Lo que se fija aquí:

1. Un ``admin`` global conserva poder global (no necesita membresía).
2. Un gestor global puede ser **gestor en una sucursal y operador en
   otra**: el rol de la sucursal decide, no el global.
3. ``role_in_parking`` **nunca** da más poder que el rol global: un
   ``operador`` global con ``role_in_parking='gestor'`` sigue siendo
   operador (aquí está el «techo» del ADR 0005, y es lo que impide que
   una fila de la tabla de membresías sea una escalada de privilegios).
4. El T-114 sigue intacto: un ``cliente`` global con
   ``role_in_parking='gestor'`` no es personal en ninguna sucursal.
5. Los endpoints que exigen un rol concreto («sólo gestor») miran el rol
   **de esa sucursal**.

Matriz: rol global × rol de sucursal × endpoint.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import ParkingMembership, User
from tests._audit_helpers import _login_headers, _seed_parking

#: Ventana de los informes (los informes exigen ``from`` y ``to``).
_VENTANA = {
    "from": "2026-01-01T00:00:00Z",
    "to": "2026-01-02T00:00:00Z",
}


def _usuario(db: Session, email: str, rol: UserRole, password: str) -> User:
    usuario = User(
        email=email,
        full_name=email.split("@")[0],
        role=rol,
        hashed_password=hash_password(password),
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _membresia(
    db: Session, usuario: User, parking_id: int, rol: str,
) -> ParkingMembership:
    """Membresía con el rol **de esa sucursal**."""
    membresia = ParkingMembership(
        user_id=usuario.id,
        parking_id=parking_id,
        role_in_parking=rol,
    )
    db.add(membresia)
    db.commit()
    db.refresh(membresia)
    return membresia


# ── Endpoints de prueba, por lo que exigen ───────────────────────────────
#
# - ``alerts``     → cualquier **personal** de la sucursal (listar alertas).
# - ``operadores`` → **gestor o admin de esa sucursal** (gestionar personal).
# - ``margins``    → **gestor o admin de esa sucursal** (los informes).


def _alerts(client: TestClient, headers: dict[str, str], parking_id: int):
    return client.get(f"/api/v1/parkings/{parking_id}/alerts", headers=headers)


def _operadores(client: TestClient, headers: dict[str, str], parking_id: int):
    return client.get(f"/api/v1/parkings/{parking_id}/operadores", headers=headers)


def _margins(client: TestClient, headers: dict[str, str], parking_id: int):
    return client.get(
        "/api/v1/admin/reports/margins",
        params={"parking_id": parking_id, **_VENTANA},
        headers=headers,
    )


# ── 1 · el admin global conserva el poder global ─────────────────────────


def test_admin_global_no_necesita_membresia(
    client: TestClient, db_session: Session
) -> None:
    """Regla 1 del ADR: el admin global no necesita membresía."""
    parking = _seed_parking(db_session, code="P-ADMIN")
    admin = _usuario(db_session, "admin@rbac.es", UserRole.ADMIN, "admin12345")

    headers = _login_headers(client, admin.email, "admin12345")
    assert _alerts(client, headers, parking.id).status_code == 200
    assert _operadores(client, headers, parking.id).status_code == 200
    assert _margins(client, headers, parking.id).status_code == 200


# ── 2 · el rol de la sucursal es el poder real ───────────────────────────


def test_gestor_en_una_sucursal_y_operador_en_otra(
    client: TestClient, db_session: Session
) -> None:
    """El poder **depende de la sucursal**: gestor en A, operador en B.

    Antes del T-178 el rol global mandaba: este gestor podía gestionar el
    personal de **las dos** sucursales.
    """
    parking_a = _seed_parking(db_session, code="P-A")
    parking_b = _seed_parking(db_session, code="P-B")
    gestor = _usuario(db_session, "gestor@rbac.es", UserRole.GESTOR, "gestor12345")
    _membresia(db_session, gestor, parking_a.id, UserRole.GESTOR.value)
    _membresia(db_session, gestor, parking_b.id, UserRole.OPERADOR.value)

    headers = _login_headers(client, gestor.email, "gestor12345")

    # En A es gestor: puede gestionar el personal y ver los informes.
    assert _operadores(client, headers, parking_a.id).status_code == 200
    assert _margins(client, headers, parking_a.id).status_code == 200

    # En B es operador: opera, pero no gestiona personal ni ve informes.
    assert _alerts(client, headers, parking_b.id).status_code == 200
    assert _operadores(client, headers, parking_b.id).status_code == 403
    assert _margins(client, headers, parking_b.id).status_code == 403


def test_el_rol_global_es_el_techo(
    client: TestClient, db_session: Session
) -> None:
    """``role_in_parking`` **no** da más poder que el rol global.

    Un ``operador`` global con ``role_in_parking='gestor'`` sigue siendo
    operador: la membresía no es una escalada de privilegios (ADR 0005,
    «Por qué el techo y no la unión»).
    """
    parking = _seed_parking(db_session, code="P-TECHO")
    operador = _usuario(
        db_session, "operador@rbac.es", UserRole.OPERADOR, "oper12345"
    )
    _membresia(db_session, operador, parking.id, UserRole.GESTOR.value)

    headers = _login_headers(client, operador.email, "oper12345")

    # Es personal de la sucursal (operador) → puede operar.
    assert _alerts(client, headers, parking.id).status_code == 200
    # Pero no gestiona personal ni ve informes: el techo lo recorta.
    assert _operadores(client, headers, parking.id).status_code == 403
    assert _margins(client, headers, parking.id).status_code == 403


def test_t114_cliente_con_membresia_sigue_sin_poder(
    client: TestClient, db_session: Session
) -> None:
    """El T-114 sigue intacto: un cliente es cliente en todas partes."""
    parking = _seed_parking(db_session, code="P-CLIENTE")
    cliente = _usuario(db_session, "cliente@rbac.es", UserRole.CLIENTE, "cliente12345")
    _membresia(db_session, cliente, parking.id, UserRole.GESTOR.value)

    headers = _login_headers(client, cliente.email, "cliente12345")
    assert _alerts(client, headers, parking.id).status_code == 403
    assert _operadores(client, headers, parking.id).status_code == 403
    assert _margins(client, headers, parking.id).status_code == 403


def test_rol_de_sucursal_cliente_veda_la_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """Regla 3: si el rol efectivo no es de personal, la sucursal está vedada.

    Un gestor global puede estar en una sucursal como simple conductor.
    """
    parking = _seed_parking(db_session, code="P-VEDADA")
    gestor = _usuario(db_session, "gestor2@rbac.es", UserRole.GESTOR, "gestor12345")
    _membresia(db_session, gestor, parking.id, UserRole.CLIENTE.value)

    headers = _login_headers(client, gestor.email, "gestor12345")
    assert _alerts(client, headers, parking.id).status_code == 403
    assert _operadores(client, headers, parking.id).status_code == 403


def test_sin_membresia_no_hay_acceso(
    client: TestClient, db_session: Session
) -> None:
    """Sin fila de membresía, esa sucursal no existe para el usuario."""
    parking = _seed_parking(db_session, code="P-SIN")
    gestor = _usuario(db_session, "gestor3@rbac.es", UserRole.GESTOR, "gestor12345")

    headers = _login_headers(client, gestor.email, "gestor12345")
    assert _alerts(client, headers, parking.id).status_code == 403
    assert _operadores(client, headers, parking.id).status_code == 403
    assert _margins(client, headers, parking.id).status_code == 403


def test_el_informe_mira_el_rol_de_la_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """El informe de A se puede ver; el de B no (aunque sea el mismo gestor)."""
    parking_a = _seed_parking(db_session, code="P-INF-A")
    parking_b = _seed_parking(db_session, code="P-INF-B")
    gestor = _usuario(db_session, "gestor4@rbac.es", UserRole.GESTOR, "gestor12345")
    _membresia(db_session, gestor, parking_a.id, UserRole.GESTOR.value)
    _membresia(db_session, gestor, parking_b.id, UserRole.OPERADOR.value)

    headers = _login_headers(client, gestor.email, "gestor12345")
    assert _margins(client, headers, parking_a.id).status_code == 200
    assert _margins(client, headers, parking_b.id).status_code == 403


# ── 3 · los endpoints de membresía (sólo admin) ──────────────────────────


def test_listar_membresias(client: TestClient, db_session: Session) -> None:
    parking = _seed_parking(db_session, code="P-MEM")
    admin = _usuario(db_session, "admin2@rbac.es", UserRole.ADMIN, "admin12345")
    gestor = _usuario(db_session, "gestor5@rbac.es", UserRole.GESTOR, "gestor12345")
    membresia = _membresia(db_session, gestor, parking.id, UserRole.GESTOR.value)

    headers = _login_headers(client, admin.email, "admin12345")
    r = client.get(f"/api/v1/users/{gestor.id}/memberships", headers=headers)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo == [
        {
            "id": membresia.id,
            "user_id": gestor.id,
            "parking_id": parking.id,
            "role_in_parking": "gestor",
            "created_at": cuerpo[0]["created_at"],
            "updated_at": cuerpo[0]["updated_at"],
        }
    ]
    # Los 4 campos que espera la interfaz del frontend.
    assert {"id", "user_id", "parking_id", "role_in_parking"} <= set(cuerpo[0])

    # Sólo admin.
    cabeceras_gestor = _login_headers(client, gestor.email, "gestor12345")
    assert client.get(
        f"/api/v1/users/{gestor.id}/memberships", headers=cabeceras_gestor
    ).status_code == 403


def test_listar_membresias_de_usuario_inexistente(
    client: TestClient, db_session: Session
) -> None:
    admin = _usuario(db_session, "admin3@rbac.es", UserRole.ADMIN, "admin12345")
    headers = _login_headers(client, admin.email, "admin12345")
    r = client.get("/api/v1/users/999999/memberships", headers=headers)
    assert r.status_code == 404


def test_crear_membresia_rechaza_admin_e_rol_invalido(
    client: TestClient, db_session: Session
) -> None:
    """``admin`` no es un rol por sucursal: 422. Y un rol inventado, 422."""
    parking = _seed_parking(db_session, code="P-VAL")
    admin = _usuario(db_session, "admin4@rbac.es", UserRole.ADMIN, "admin12345")
    gestor = _usuario(db_session, "gestor6@rbac.es", UserRole.GESTOR, "gestor12345")
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/users/{gestor.id}/memberships",
        json={"parking_id": parking.id, "role_in_parking": "admin"},
        headers=headers,
    )
    assert r.status_code == 422, r.text

    r = client.post(
        f"/api/v1/users/{gestor.id}/memberships",
        json={"parking_id": parking.id, "role_in_parking": "jefe"},
        headers=headers,
    )
    assert r.status_code == 422, r.text

    # Un rol de sucursal válido: se acepta.
    r = client.post(
        f"/api/v1/users/{gestor.id}/memberships",
        json={"parking_id": parking.id, "role_in_parking": "operador"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["role_in_parking"] == "operador"


def test_cambiar_el_rol_de_una_membresia(
    client: TestClient, db_session: Session
) -> None:
    parking = _seed_parking(db_session, code="P-PATCH")
    admin = _usuario(db_session, "admin5@rbac.es", UserRole.ADMIN, "admin12345")
    gestor = _usuario(db_session, "gestor7@rbac.es", UserRole.GESTOR, "gestor12345")
    otro = _usuario(db_session, "otro@rbac.es", UserRole.GESTOR, "gestor12345")
    membresia = _membresia(db_session, gestor, parking.id, UserRole.GESTOR.value)
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.patch(
        f"/api/v1/users/{gestor.id}/memberships/{membresia.id}",
        json={"role_in_parking": "operador"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role_in_parking"] == "operador"

    # El admin no puede dejar un admin "de sucursal".
    r = client.patch(
        f"/api/v1/users/{gestor.id}/memberships/{membresia.id}",
        json={"role_in_parking": "admin"},
        headers=headers,
    )
    assert r.status_code == 422, r.text

    # Una membresía de otro usuario: 404 (no 403: no se revela que existe).
    membresia_ajena = _membresia(db_session, otro, parking.id, UserRole.GESTOR.value)
    r = client.patch(
        f"/api/v1/users/{gestor.id}/memberships/{membresia_ajena.id}",
        json={"role_in_parking": "operador"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_borrar_membresia(client: TestClient, db_session: Session) -> None:
    parking = _seed_parking(db_session, code="P-DEL")
    admin = _usuario(db_session, "admin6@rbac.es", UserRole.ADMIN, "admin12345")
    gestor = _usuario(db_session, "gestor8@rbac.es", UserRole.GESTOR, "gestor12345")
    otro = _usuario(db_session, "otro2@rbac.es", UserRole.GESTOR, "gestor12345")
    membresia = _membresia(db_session, gestor, parking.id, UserRole.GESTOR.value)
    membresia_ajena = _membresia(db_session, otro, parking.id, UserRole.GESTOR.value)
    headers = _login_headers(client, admin.email, "admin12345")

    # Membresía ajena: 404.
    r = client.delete(
        f"/api/v1/users/{gestor.id}/memberships/{membresia_ajena.id}",
        headers=headers,
    )
    assert r.status_code == 404, r.text

    r = client.delete(
        f"/api/v1/users/{gestor.id}/memberships/{membresia.id}",
        headers=headers,
    )
    assert r.status_code == 204, r.text

    r = client.get(f"/api/v1/users/{gestor.id}/memberships", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_el_rol_pedido_por_encima_del_global_se_recorta(
    client: TestClient, db_session: Session
) -> None:
    """Escribir un rol más alto del global se **acepta** (queda recortado).

    El 422 es sólo para ``admin`` y para valores que no son roles: el
    techo se aplica al **leer**, no al escribir (ADR 0005).
    """
    parking = _seed_parking(db_session, code="P-RECORTE")
    admin = _usuario(db_session, "admin7@rbac.es", UserRole.ADMIN, "admin12345")
    operador = _usuario(
        db_session, "operador2@rbac.es", UserRole.OPERADOR, "oper12345"
    )
    headers = _login_headers(client, admin.email, "admin12345")

    r = client.post(
        f"/api/v1/users/{operador.id}/memberships",
        json={"parking_id": parking.id, "role_in_parking": "gestor"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["role_in_parking"] == "gestor"

    # Pero al operar en esa sucursal es operador: el techo lo recorta.
    cabeceras_operador = _login_headers(client, operador.email, "oper12345")
    assert _alerts(client, cabeceras_operador, parking.id).status_code == 200
    assert _operadores(client, cabeceras_operador, parking.id).status_code == 403
