"""Helpers reutilizables para tests de audit (Fase 3B).

Provee:

  - ``_login(client, email, password)``: wrapper sobre POST /auth/login.
  - ``_seed_admin(db)``: crea un admin con password conocido.
  - ``_seed_gestor(db)``: crea un gestor con password conocido.
  - ``_seed_operador(db)``: crea un operador con password conocido.
  - ``_seed_cliente(db)``: crea un cliente con password conocido.
  - ``_seed_parking(db)``: crea una Parking de prueba.
  - ``_seed_membership(db, user, parking)``: añade membresía gestor→parking.
  - ``assert_audit_log(db, *, action, ...)``: asserts sobre ``audit_logs``.
  - ``assert_no_audit_log(db, *, action)``: asegura que NO se creó audit.
  - ``monkeypatch_tasks_session(monkeypatch, db_session)``: hace que
    ``app.workers.tasks.SessionLocal`` apunte a la sesión de prueba.

Los helpers se importan explícitamente desde los tests (``from tests
import _audit_helpers`` o ``from tests._audit_helpers import _login``).
NO se registran como fixtures automáticas — son funciones puras.
"""
from __future__ import annotations

from typing import Optional

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.parking import Parking as ParkingModel
from app.models.user import ParkingMembership, User


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    """Variante que devuelve directamente el header Authorization."""
    return {"Authorization": f"Bearer {_login(client, email, password)}"}


def _seed_admin(db: Session, *, email: str = "admin@test.es",
                password: str = "admin12345") -> User:
    admin = User(
        email=email, full_name="Admin",
        role=UserRole.ADMIN, hashed_password=hash_password(password),
    )
    db.add(admin); db.commit(); db.refresh(admin)
    return admin


def _seed_gestor(db: Session, *, email: str = "gestor@test.es",
                 password: str = "gestor1234") -> User:
    gestor = User(
        email=email, full_name="Gestor",
        role=UserRole.GESTOR, hashed_password=hash_password(password),
    )
    db.add(gestor); db.commit(); db.refresh(gestor)
    return gestor


def _seed_cliente(db: Session, *, email: str = "cliente@test.es",
                  password: str = "cliente1234") -> User:
    cliente = User(
        email=email, full_name="Cliente",
        role=UserRole.CLIENTE, hashed_password=hash_password(password),
    )
    db.add(cliente); db.commit(); db.refresh(cliente)
    return cliente


def _seed_operador(db: Session, *, email: str = "operador@test.es",
                   password: str = "oper12345") -> User:
    operador = User(
        email=email, full_name="Operador",
        role=UserRole.OPERADOR, hashed_password=hash_password(password),
    )
    db.add(operador); db.commit(); db.refresh(operador)
    return operador


def _seed_parking(db: Session, *, code: str = "P-T") -> ParkingModel:
    parking = ParkingModel(code=code, name=f"Test {code}",
                           address="Calle Test 1", city="Madrid")
    db.add(parking); db.commit(); db.refresh(parking)
    return parking


def _seed_membership(db: Session, *, user: User, parking: ParkingModel) -> None:
    db.add(ParkingMembership(user_id=user.id, parking_id=parking.id))
    db.commit()


def assert_audit_log(
    db: Session,
    *,
    action: str,
    resource: Optional[str] = None,
    user_id: Optional[int] = None,
    result: Optional[str] = None,
    min_count: int = 1,
) -> AuditLog:
    """Verifica que existe al menos ``min_count`` audit_logs con la firma dada.

    Refresca la sesión y commitea explícitamente para sortear el problema
    de visibilidad con SQLite StaticPool (los handlers usan la misma sesión
    que el fixture, pero commits intermedios pueden no ser visibles sin
    este commit explícito).
    """
    db.expire_all()
    db.commit()
    q = db.query(AuditLog).filter(AuditLog.action == action)
    if resource is not None:
        q = q.filter(AuditLog.resource == resource)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    if result is not None:
        q = q.filter(AuditLog.result == result)
    rows = q.all()
    assert len(rows) >= min_count, (
        f"Expected ≥{min_count} audit_logs con action={action!r}, "
        f"got {len(rows)}. Filters: resource={resource} user_id={user_id} "
        f"result={result}"
    )
    return rows[0]


def assert_no_audit_log(db: Session, *, action: str) -> None:
    """Asegura que NO se creó un audit con esa action (path no mutado)."""
    db.expire_all()
    rows = db.query(AuditLog).filter(AuditLog.action == action).all()
    assert len(rows) == 0, f"Expected 0 audit_logs with action={action!r}, got {len(rows)}"


def monkeypatch_tasks_session(monkeypatch, db_session: Session) -> None:
    """Hace que ``app.workers.tasks.SessionLocal`` devuelva la sesión de prueba.

    El patrón es el mismo que usa ``conftest.py`` para
    ``manual_tickets.SessionLocal``, ``ingest_service.SessionLocal`` e
    ``incidents.SessionLocal``. Sin esto, los workers verían una sesión
    separada contra el motor de producción y los audit_logs NO
    aparecerían en ``db_session``.

    Uso::

        def test_algo(monkeypatch, db_session):
            monkeypatch_tasks_session(monkeypatch, db_session)
            ...
    """
    from app.workers import tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "SessionLocal", lambda: db_session)


__all__ = [
    "_login", "_login_headers",
    "_seed_admin", "_seed_gestor", "_seed_cliente", "_seed_operador",
    "_seed_parking", "_seed_membership",
    "assert_audit_log", "assert_no_audit_log",
    "monkeypatch_tasks_session",
]
