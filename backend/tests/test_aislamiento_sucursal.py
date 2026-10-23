"""Aislamiento por sucursal: las cuatro fugas medidas y arregladas.

Contexto
--------
El modelo de datos **no** tiene ``client_id``: el aislamiento entre
sucursales se hace con ``parking_memberships`` (el usuario pertenece a
una sucursal) y con los roles (``admin`` / ``gestor`` / ``operador`` /
``cliente``). Este fichero fija el contrato de ese aislamiento.

Los cuatro defectos (medidos contra el sistema en marcha, no ledos):

- **T-113**: ``POST /api/v1/tickets`` aceptaba el ``parking_id`` del body
  sin mirar la membresía -> un gestor escribía en la contabilidad de otra
  sucursal (y el ticket creado ya no lo podía ni ver).
- **T-114**: ``enforce_parking_membership`` miraba la fila de membresía
  pero **no el rol** -> un conductor (rol ``cliente``) con una membresía
  se convertía en gestor: creaba plazas, creaba cámaras y **fijaba el
  precio** de la sucursal.
- **T-115**: los endpoints de geocercas validaban la membresía del
  ``parking_id`` del path pero no que la **cámara** fuera de esa
  sucursal -> un gestor leía y **modificaba** las geocercas de otra
  sucursal (y con ello apagaba la detección de su entrada).
- **T-116**: la flota de vehículos era global -> cualquier gestor
  recibía todas las matrículas del sistema, podía editarlas y podía
  vincular usuarios ajenos a vehículos ajenos (y ese vínculo decide
  **qué tickets ve cada cliente**).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, ParkingSpace
from app.models.ticket import Ticket
from app.models.user import ParkingMembership
from app.models.vehicle import Vehicle
from tests._audit_helpers import (
    _login_headers,
    _seed_admin,
    _seed_cliente,
    _seed_gestor,
    _seed_parking,
)


def _camara(db: Session, parking_id: int, code: str = "CAM-1") -> Camera:
    camara = Camera(
        parking_id=parking_id,
        code=code,
        name=f"Camara {code}",
        rtsp_url="rtsp://ejemplo.invalid/x",
    )
    db.add(camara)
    db.commit()
    db.refresh(camara)
    return camara


def _plaza(db: Session, parking_id: int, numero: str = "A-01") -> ParkingSpace:
    plaza = ParkingSpace(parking_id=parking_id, lane="A", number=numero)
    db.add(plaza)
    db.commit()
    db.refresh(plaza)
    return plaza


def _geocerca(db: Session, camara: Camera, plaza: ParkingSpace) -> CameraGeofence:
    geocerca = CameraGeofence(
        camera_id=camara.id,
        parking_space_id=plaza.id,
        x=0.1,
        y=0.2,
        w=0.3,
        h=0.4,
    )
    db.add(geocerca)
    db.commit()
    db.refresh(geocerca)
    return geocerca


def _vehiculo(db: Session, plate: str) -> Vehicle:
    vehiculo = Vehicle(plate=plate)
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def _ticket_activo(db: Session, *, parking_id: int, vehicle_id: int) -> Ticket:
    ticket = Ticket(
        parking_id=parking_id,
        vehicle_id=vehicle_id,
        status=TicketStatus.ACTIVO,
        entry_at=datetime.now(timezone.utc),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _escenario(db: Session):
    """Dos sucursales, un gestor de una y un cliente (con y sin membresía)."""
    parking_a = _seed_parking(db, code="P-A")
    parking_b = _seed_parking(db, code="P-B")
    gestor = _seed_gestor(db, email="gestor@aisla.es")
    db.add(ParkingMembership(user_id=gestor.id, parking_id=parking_a.id))
    db.commit()
    return parking_a, parking_b, gestor


# ── T-113 · el alta de tickets se acota a la sucursal del usuario ─────────


def test_alta_de_ticket_en_sucursal_ajena_da_403(
    client: TestClient, db_session: Session
) -> None:
    """Un gestor NO puede crear un ticket en una sucursal que no es suya.

    Medido antes del arreglo (sistema en marcha, gestor de la sucursal 11
    y la 12 sin miembros): ``POST /api/v1/tickets`` con ``parking_id`` de
    la 12 devolvia **201** y creaba el ticket 617.
    """
    parking_a, parking_b, gestor = _escenario(db_session)
    vehiculo = _vehiculo(db_session, "1111-AAA")
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.post(
        "/api/v1/tickets",
        headers=headers,
        json={
            "parking_id": parking_b.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert r.status_code == 403, r.text
    assert db_session.query(Ticket).filter(
        Ticket.parking_id == parking_b.id
    ).count() == 0, "el ticket se escribio en la sucursal ajena"


def test_alta_de_ticket_en_su_sucursal_sigue_funcionando(
    client: TestClient, db_session: Session
) -> None:
    """Control: el camino bueno no se ha roto."""
    parking_a, _parking_b, gestor = _escenario(db_session)
    vehiculo = _vehiculo(db_session, "2222-BBB")
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.post(
        "/api/v1/tickets",
        headers=headers,
        json={
            "parking_id": parking_a.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert r.status_code == 201, r.text
    assert r.json()["parking_id"] == parking_a.id


def test_alta_de_ticket_duplicado_da_409_y_no_un_500(
    client: TestClient, db_session: Session
) -> None:
    """Un vehiculo no puede tener dos tickets activos en la misma sucursal.

    El indice unico parcial (T-105) es lo que lo prohibe; antes el
    ``IntegrityError`` no se capturaba y la API devolvia un 500.
    """
    parking_a, _parking_b, gestor = _escenario(db_session)
    vehiculo = _vehiculo(db_session, "3333-CCC")
    _ticket_activo(db_session, parking_id=parking_a.id, vehicle_id=vehiculo.id)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.post(
        "/api/v1/tickets",
        headers=headers,
        json={
            "parking_id": parking_a.id,
            "vehicle_id": vehiculo.id,
            "entry_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert r.status_code == 409, r.text


# ── T-114 · una membresía NO convierte a un cliente en gestor ─────────────


def test_un_cliente_con_membresia_no_gestiona_la_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """Un conductor con membresía no puede crear plazas, cámaras ni tarifas.

    Medido antes del arreglo: los tres POST devolvian **201**, y el de
    tarifas además fijaba el precio (fraude de ingresos).
    """
    parking_a, _parking_b = _escenario(db_session)[:2]
    cliente = _seed_cliente(db_session, email="cliente@aisla.es")
    db_session.add(
        ParkingMembership(user_id=cliente.id, parking_id=parking_a.id)
    )
    db_session.commit()
    headers = _login_headers(client, cliente.email, "cliente1234")

    r = client.post(
        f"/api/v1/parkings/{parking_a.id}/spaces",
        headers=headers,
        json={"lane": "X", "number": "X-01"},
    )
    assert r.status_code == 403, f"el cliente creo una plaza: {r.text}"

    r = client.post(
        f"/api/v1/parkings/{parking_a.id}/cameras",
        headers=headers,
        json={
            "code": "PIRATE",
            "name": "Camara pirata",
            "rtsp_url": "rtsp://ejemplo.invalid/x",
        },
    )
    assert r.status_code == 403, f"el cliente creo una camara: {r.text}"

    r = client.post(
        f"/api/v1/parkings/{parking_a.id}/tariffs",
        headers=headers,
        json={
            "parking_id": parking_a.id,
            "name": "Tarifa pirata",
            "price_per_hour": 0.01,
            "price_per_fraction": 0.01,
            "fraction_minutes": 15,
            "max_daily": 0.01,
            "valid_from": "2026-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 403, f"el cliente fijo el precio: {r.text}"


def test_un_gestor_con_membresia_sigue_gestionando_su_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """Control: el gestor no pierde nada con el arreglo."""
    parking_a, _parking_b, gestor = _escenario(db_session)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.post(
        f"/api/v1/parkings/{parking_a.id}/spaces",
        headers=headers,
        json={"lane": "A", "number": "A-77"},
    )
    assert r.status_code == 201, r.text


# ── T-115 · las geocercas tienen que ser de la cámara de esa sucursal ─────


def test_no_se_leen_las_geocercas_de_una_camara_de_otra_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """GET de geocercas con una cámara ajena: 404, no 200 con datos.

    Medido antes del arreglo: ``GET /parkings/11/cameras/91/geofences``
    devolvia **200** con la geocerca de la sucursal 12.
    """
    parking_a, parking_b, gestor = _escenario(db_session)
    camara_b = _camara(db_session, parking_b.id, "CAM-B")
    plaza_b = _plaza(db_session, parking_b.id)
    _geocerca(db_session, camara_b, plaza_b)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        f"/api/v1/parkings/{parking_a.id}/cameras/{camara_b.id}/geofences",
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_no_se_modifican_las_geocercas_de_una_camara_de_otra_sucursal(
    client: TestClient, db_session: Session
) -> None:
    """PATCH de una geocerca ajena: 404 y la geocerca no cambia.

    Medido antes del arreglo: el PATCH devolvia **200** y movia la
    geocerca (x=0.99, y=0.99, w=0.01, h=0.01): el OCR de la otra
    sucursal dejaba de detectar la entrada.
    """
    parking_a, parking_b, gestor = _escenario(db_session)
    camara_b = _camara(db_session, parking_b.id, "CAM-B")
    plaza_b = _plaza(db_session, parking_b.id)
    geocerca = _geocerca(db_session, camara_b, plaza_b)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.patch(
        f"/api/v1/parkings/{parking_a.id}/cameras/{camara_b.id}"
        f"/geofences/{geocerca.id}",
        headers=headers,
        json={"x": 0.99, "y": 0.99, "w": 0.01, "h": 0.01},
    )
    assert r.status_code == 404, r.text

    db_session.expire_all()
    geocerca = db_session.get(CameraGeofence, geocerca.id)
    assert geocerca is not None
    assert geocerca.x == 0.1, "la geocerca de la otra sucursal se modifico"


def test_las_geocercas_de_la_suya_siguen_funcionando(
    client: TestClient, db_session: Session
) -> None:
    """Control: el camino bueno no se ha roto."""
    parking_a, _parking_b, gestor = _escenario(db_session)
    camara_a = _camara(db_session, parking_a.id, "CAM-A")
    plaza_a = _plaza(db_session, parking_a.id)
    geocerca = _geocerca(db_session, camara_a, plaza_a)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        f"/api/v1/parkings/{parking_a.id}/cameras/{camara_a.id}/geofences",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [g["id"] for g in r.json()] == [geocerca.id]

    r = client.patch(
        f"/api/v1/parkings/{parking_a.id}/cameras/{camara_a.id}"
        f"/geofences/{geocerca.id}",
        headers=headers,
        json={"x": 0.5},
    )
    assert r.status_code == 200, r.text
    assert r.json()["x"] == 0.5


# ── T-116 · la flota de vehículos deja de ser global ─────────────────────


def test_el_listado_completo_de_la_flota_es_de_admin(
    client: TestClient, db_session: Session
) -> None:
    """Sin ``plate``, el listado global es sólo del administrador.

    Medido antes del arreglo: el gestor de la sucursal 11 recibia las 6
    matriculas del sistema, 3 de las cuales no aparecen en sus propios
    movimientos.
    """
    _parking_a, _parking_b, gestor = _escenario(db_session)
    _vehiculo(db_session, "1111-AAA")
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get("/api/v1/vehicles", headers=headers)
    assert r.status_code == 403, r.text

    admin = _seed_admin(db_session, email="admin@aisla.es")
    headers_admin = _login_headers(client, admin.email, "admin12345")
    r = client.get("/api/v1/vehicles", headers=headers_admin)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_la_busqueda_dirigida_por_matricula_sigue_siendo_del_personal(
    client: TestClient, db_session: Session
) -> None:
    """Con ``plate`` es una búsqueda dirigida: la puede hacer el personal."""
    _parking_a, _parking_b, gestor = _escenario(db_session)
    _vehiculo(db_session, "1111-AAA")
    _vehiculo(db_session, "2222-BBB")
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get("/api/v1/vehicles?plate=1111", headers=headers)
    assert r.status_code == 200, r.text
    assert [v["plate"] for v in r.json()] == ["1111-AAA"]


def test_el_personal_puede_buscar_por_matricula_pero_no_enumerar_la_flota(
    client: TestClient, db_session: Session
) -> None:
    """La búsqueda dirigida es del personal, pero no sirve para enumerar.

    T-93 (ya arreglado): los comodines de LIKE van escapados, así que
    ``?plate=%`` busca el signo literal. Y T-116: el listado **completo**
    (sin ``plate``) es de admin, que es donde estaba la fuga de verdad.
    """
    _parking_a, _parking_b, gestor = _escenario(db_session)
    _vehiculo(db_session, "1111-AAA")
    _vehiculo(db_session, "2222-BBB")
    headers = _login_headers(client, gestor.email, "gestor1234")

    # Busqueda dirigida: si.
    r = client.get("/api/v1/vehicles?plate=1111", headers=headers)
    assert r.status_code == 200, r.text
    assert [v["plate"] for v in r.json()] == ["1111-AAA"]

    # El comodin no es un comodin: no devuelve la flota.
    r = client.get("/api/v1/vehicles?plate=%25", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == [], "el comodin devolvio la flota entera"


def test_el_personal_no_puede_crear_editar_ni_vincular_vehiculos(
    client: TestClient, db_session: Session
) -> None:
    """Alta, edicion y vinculo de vehiculos: sólo admin.

    Con staff, un gestor de la sucursal A podia ocupar la matricula de un
    cliente de B, editar su marca y (lo mas grave) **vincular un cliente
    de B a un vehiculo**: ese vinculo decide que tickets ve cada cliente.
    """
    _parking_a, _parking_b, gestor = _escenario(db_session)
    vehiculo = _vehiculo(db_session, "1111-AAA")
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.post(
        "/api/v1/vehicles",
        headers=headers,
        json={"plate": "9999-ZZZ"},
    )
    assert r.status_code == 403, r.text

    r = client.patch(
        f"/api/v1/vehicles/{vehiculo.id}",
        headers=headers,
        json={"brand": "Marca ajena"},
    )
    assert r.status_code == 403, r.text

    cliente = _seed_cliente(db_session, email="cliente@aisla.es")
    r = client.post(
        f"/api/v1/vehicles/{vehiculo.id}/users",
        headers=headers,
        json={"user_id": cliente.id, "role": "propietario"},
    )
    assert r.status_code == 403, r.text


def test_los_vehiculos_de_la_sucursal_son_los_del_listado_acotado(
    client: TestClient, db_session: Session
) -> None:
    """El listado por sucursal: los vehiculos con ticket en ESA sucursal."""
    parking_a, parking_b, gestor = _escenario(db_session)
    veh_a = _vehiculo(db_session, "1111-AAA")
    veh_b = _vehiculo(db_session, "2222-BBB")
    _ticket_activo(db_session, parking_id=parking_a.id, vehicle_id=veh_a.id)
    _ticket_activo(db_session, parking_id=parking_b.id, vehicle_id=veh_b.id)
    headers = _login_headers(client, gestor.email, "gestor1234")

    r = client.get(
        f"/api/v1/parkings/{parking_a.id}/vehicles", headers=headers
    )
    assert r.status_code == 200, r.text
    assert [v["plate"] for v in r.json()] == ["1111-AAA"]

    # Y el gestor de otra sucursal recibe 403 (no una lista vacia).
    gestor_b = _seed_gestor(db_session, email="gestor.b@aisla.es")
    db_session.add(
        ParkingMembership(user_id=gestor_b.id, parking_id=parking_b.id)
    )
    db_session.commit()
    headers_b = _login_headers(client, gestor_b.email, "gestor1234")
    r = client.get(
        f"/api/v1/parkings/{parking_a.id}/vehicles", headers=headers_b
    )
    assert r.status_code == 403, r.text
