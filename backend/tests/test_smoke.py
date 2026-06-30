"""Tests smoke: health + login + RBAC + 401 sin token."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_unauthorized_users_listing(client: TestClient) -> None:
    resp = client.get("/api/v1/users")
    assert resp.status_code == 401


def test_unauthorized_parkings_listing(client: TestClient) -> None:
    resp = client.get("/api/v1/parkings")
    assert resp.status_code == 401


def test_login_and_admin_can_list_users(client: TestClient) -> None:
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User

    admin = User(
        email="admin@test.es",
        full_name="Admin",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin12345"),
    )

    db_gen = client.app.dependency_overrides[__import__("app.core.db", fromlist=["get_db"]).get_db]()
    db = next(db_gen)
    db.add(admin)
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.es", "password": "admin12345"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "admin@test.es" in emails


def test_operador_cannot_list_users(client: TestClient) -> None:
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User

    operador = User(
        email="operador@test.es",
        full_name="Operador",
        role=UserRole.OPERADOR,
        hashed_password=hash_password("oper12345"),
    )

    db_gen = client.app.dependency_overrides[__import__("app.core.db", fromlist=["get_db"]).get_db]()
    db = next(db_gen)
    db.add(operador)
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "operador@test.es", "password": "oper12345"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 403