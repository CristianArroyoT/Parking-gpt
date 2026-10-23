"""Los informes tienen tope de ventana y de filas (T-100).

POR QUÉ existe este fichero: los informes exportaban **todo** lo que
les pedían, sin ningún tope:

- la **ventana** no tenía límite: un gestor podía pedir 30 años;
- el **informe de ocupación** cargaba TODA la historia de la sucursal
  (el filtro se hacía en Python, no en SQL), así que pedir un informe de
  una hora traía los tickets de tres años en memoria;
- el PDF multiplica las filas por los objetos del dibujo.

El efecto: un par de peticiones puede dejar el proceso de la API sin
memoria, y si se queda sin memoria se cae la API **entera**.

Estos tests comprueban que los topes existen y que el informe sigue
diciendo lo mismo (que no se ha roto por acotar).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import TicketStatus, UserRole
from app.models.parking import Parking, ParkingSpace
from app.models.ticket import Ticket
from app.models.user import User
from app.models.vehicle import Vehicle


def _sembrar(db: Session) -> dict[str, object]:
    admin = User(
        email="admin-informes@test.es", full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password("admin12345"),
    )
    parking = Parking(code="P-INF", name="Informes", address="x", city="y")
    db.add_all([admin, parking])
    db.flush()
    espacio = ParkingSpace(
        parking_id=parking.id, lane="A", number="01",
    )
    vehiculo = Vehicle(plate="3333-CCC")
    db.add_all([espacio, vehiculo])
    db.flush()
    ahora = datetime.now(timezone.utc)
    # Un ticket viejo, cerrado hace un ano (no debe salir en la foto de
    # ocupacion de hoy) y uno abierto de hoy (si).
    db.add_all([
        Ticket(
            parking_id=parking.id, vehicle_id=vehiculo.id,
            status=TicketStatus.CERRADO, entry_at=ahora - timedelta(days=400),
            exit_at=ahora - timedelta(days=399), total=5.0,
        ),
        Ticket(
            parking_id=parking.id, vehicle_id=vehiculo.id,
            parking_space_id=espacio.id, status=TicketStatus.ACTIVO,
            entry_at=ahora - timedelta(hours=2),
        ),
    ])
    db.commit()
    return {"admin": admin, "parking": parking}


def _iso(dt: datetime) -> str:
    """ISO 8601 en UTC con "Z".

    OJO: el "+00:00" de ``isoformat()`` llega a la URL como un espacio
    (el "+" es un espacio en una query string) y el 422 que sale es
    engañoso ("unexpected extra characters at the end of the input").
    """
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_una_ventana_larga_se_rechaza(
    client: TestClient, db_session: Session,
) -> None:
    """Pedir 30 años de informe se rechaza con 422 (no se genera)."""
    datos = _sembrar(db_session)
    headers = _login(client, "admin-informes@test.es", "admin12345")
    ahora = datetime.now(timezone.utc)

    respuesta = client.get(
        "/api/v1/admin/reports/tickets.csv"
        f"?parking_id={datos['parking'].id}"
        f"&from={_iso(ahora - timedelta(days=3650))}"
        f"&to={_iso(ahora)}",
        headers=headers,
    )
    assert respuesta.status_code == 422, respuesta.text
    assert "acota" in respuesta.text.lower() or "dias" in respuesta.text.lower()


def test_una_ventura_normal_se_genera(
    client: TestClient, db_session: Session,
) -> None:
    """Una ventana de un mes se genera como siempre."""
    datos = _sembrar(db_session)
    headers = _login(client, "admin-informes@test.es", "admin12345")
    ahora = datetime.now(timezone.utc)

    respuesta = client.get(
        "/api/v1/admin/reports/tickets.csv"
        f"?parking_id={datos['parking'].id}"
        f"&from={_iso(ahora - timedelta(days=30))}"
        f"&to={_iso(ahora)}",
        headers=headers,
    )
    assert respuesta.status_code == 200, respuesta.text
    assert "ticket_id" in respuesta.text


def test_el_tope_de_filas_rechaza_el_informe(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el informe supera el tope de filas, se rechaza (413).

    Y **no** se recorta en silencio: un informe truncado sin avisar es
    peor que uno que no se genera.
    """
    from app.services import reports as reports_mod

    # Tope 0: cualquier fila supera el tope (asi no hace falta sembrar
    # 20.000 tickets para probar el camino).
    monkeypatch.setattr(reports_mod, "MAX_FILAS_INFORME", 0)
    datos = _sembrar(db_session)
    headers = _login(client, "admin-informes@test.es", "admin12345")
    ahora = datetime.now(timezone.utc)

    respuesta = client.get(
        "/api/v1/admin/reports/tickets.csv"
        f"?parking_id={datos['parking'].id}"
        f"&from={_iso(ahora - timedelta(days=30))}"
        f"&to={_iso(ahora)}",
        headers=headers,
    )
    assert respuesta.status_code == 413, respuesta.text
    assert "filas" in respuesta.text.lower()


def test_el_informe_de_ocupacion_sigue_diciendo_lo_mismo(
    client: TestClient, db_session: Session,
) -> None:
    """Acotar la carga no cambia lo que dice el informe.

    El informe de ocupacion es una **foto** en el instante ``to``: cuenta
    las plazas ocupadas por los tickets que siguen abiertos. Con el
    filtro puesto en SQL (y no en Python) el resultado tiene que ser el
    mismo: aqui hay un ticket abierto (ocupa) y uno cerrado de hace un
    ano (no ocupa).
    """
    datos = _sembrar(db_session)
    headers = _login(client, "admin-informes@test.es", "admin12345")
    ahora = datetime.now(timezone.utc)

    respuesta = client.get(
        "/api/v1/admin/reports/ocupacion.csv"
        f"?parking_id={datos['parking'].id}"
        f"&from={_iso(ahora - timedelta(days=1))}"
        f"&to={_iso(ahora)}",
        headers=headers,
    )
    assert respuesta.status_code == 200, respuesta.text
    lineas = respuesta.text.strip().splitlines()
    # El CSV tiene una columna "estado" con el estado de cada plaza.
    assert "estado" in lineas[0].lower(), lineas
    # La fila de la plaza con el ticket abierto dice "ocupada".
    assert any("ocupada" in linea.lower() for linea in lineas[1:]), lineas
    # Y el ticket cerrado de hace un ano (id=1) no aparece: no ocupa.
    # OJO: la matricula si aparece, pero por el ticket **abierto** (los dos
    # tickets son del mismo vehiculo).
    assert all(linea.split(",")[3] != "1" for linea in lineas[1:]), lineas


def test_el_lock_del_informe_es_por_actor(
    client: TestClient, db_session: Session,
) -> None:
    """Los informes tienen rate-limit propio (scope ``informe``)."""
    import redis

    from app.core.config import get_settings

    r = redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )
    for key in r.scan_iter("rl:informe*"):
        r.delete(key)
    datos = _sembrar(db_session)
    headers = _login(client, "admin-informes@test.es", "admin12345")
    ahora = datetime.now(timezone.utc)
    url = (
        "/api/v1/admin/reports/tickets.csv"
        f"?parking_id={datos['parking'].id}"
        f"&from={_iso(ahora - timedelta(days=30))}"
        f"&to={_iso(ahora)}"
    )

    # 30 peticiones seguidas: la 31 debe rebotar con 429.
    codigos = [client.get(url, headers=headers).status_code for _ in range(31)]
    assert codigos[-1] == 429, codigos
    assert 200 in codigos[:-1], codigos
    for key in r.scan_iter("rl:informe*"):
        r.delete(key)
