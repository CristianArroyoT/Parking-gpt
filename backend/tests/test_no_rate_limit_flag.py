"""T-68: el flag ``User.no_rate_limit`` no hacia NADA.

El modelo ``User`` tiene el campo ``no_rate_limit`` con un comentario que
promete que "service accounts (p.ej. cronjobs de carga inicial de datos)
pueden saltarse el rate-limit de CRUDs". Y el mecanismo existe:
``EndpointRateLimiter.check(..., skip=True)`` devuelve ``(True, "skipped",
0)`` sin tocar Redis (con un test propio:
``tests/test_endpoint_rate_limit_skip.py``).

Pero **ningun router pide el salto**: el flag nunca se leia, asi que una
cuenta de servicio se comia un 429 igual que un humano. El test del
mecanismo daba verde mientras la capacidad no existia.

Este fichero anade el test que mide el comportamiento REAL (por API), no
el mecanismo.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User


def _forzar_max(monkeypatch: pytest.MonkeyPatch, max_attempts: int) -> None:
    """Parchea ``get_settings`` donde el limitador lo tiene enlazado."""
    from app.core import config as cfg_mod
    from app.services import endpoint_rate_limit as erl_mod

    def _patched():
        real = cfg_mod.get_settings()
        field_names = (
            list(real.model_fields.keys())
            if hasattr(real, "model_fields")
            else [a for a in dir(real) if not a.startswith("_")]
        )
        data = {name: getattr(real, name) for name in field_names}
        data["endpoint_rate_limit_max_attempts"] = max_attempts
        return SimpleNamespace(**data)

    monkeypatch.setattr(erl_mod, "get_settings", _patched)


def test_un_usuario_con_no_rate_limit_no_es_bloqueado(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una cuenta de servicio NO recibe 429, por mas que se repita."""
    from tests._audit_helpers import _login_headers, _seed_admin

    _forzar_max(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    # Esto es lo que haria un cronjob de carga inicial de datos.
    admin.no_rate_limit = True
    db_session.commit()

    headers = _login_headers(client, admin.email, "admin12345")

    for i in range(5):
        r = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "email": f"servicio-{i}@solidapp.es",
                "full_name": f"Servicio {i}",
                "role": "cliente",
                "password": "servicio1234",
            },
        )
        assert r.status_code != 429, (
            f"intento {i}: la cuenta de servicio recibio un 429 "
            "(el flag User.no_rate_limit no hace nada)"
        )
        assert r.status_code == 201, r.text


def test_un_usuario_normal_sigue_siendo_bloqueado(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El caso contrario: sin el flag, el rate-limit sigue bloqueando."""
    from tests._audit_helpers import _login_headers, _seed_admin

    _forzar_max(monkeypatch, max_attempts=2)
    admin = _seed_admin(db_session)
    assert admin.no_rate_limit is False

    headers = _login_headers(client, admin.email, "admin12345")

    estados = []
    for i in range(5):
        r = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "email": f"humano-{i}@solidapp.es",
                "full_name": f"Humano {i}",
                "role": "cliente",
                "password": "humano12345",
            },
        )
        estados.append(r.status_code)

    assert 429 in estados, f"el rate-limit no bloqueo: {estados}"
    # Y el usuario debe existir: el flag solo affects al actor, no al
    # contenido de la base de datos.
    assert db_session.query(User).filter(
        User.email == "humano-0@solidapp.es"
    ).one_or_none() is not None
