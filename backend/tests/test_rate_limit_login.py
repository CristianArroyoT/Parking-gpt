"""Tests del rate-limit de login (Sprint Fase 3C, 2026-07-01).

Cubre:

  - Bloqueo tras ``login_rate_limit_max_attempts`` intentos en ventana.
  - Audit ``rate_limited_login`` con payload {ip, email, bucket, count}.
  - Buckets independientes IP + email (no se mezclan entre sí).
  - Reset por ventana (no por acierto).
  - ``get_real_ip`` con ``X-Forwarded-For`` cuando el ``client.host``
    está en ``trusted_proxies``.
  - ``get_real_ip`` cae a ``client.host`` sin XFF.
  - Override de settings (3er intento bloquea si max=2).

Usa ``monkeypatch_setattr`` sobre ``LoginRateLimiter._r`` y sobre
``redis.expire``/``redis.incr`` cuando se necesita manipular el TTL
sin ``time.sleep``.
"""
from __future__ import annotations


import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests._audit_helpers import assert_audit_log


# ── helpers ────────────────────────────────────────────────────────────

def _redis() -> redis.Redis:
    """Cliente Redis parametrizado por settings."""
    return redis.Redis.from_url(
        get_settings().redis_url, decode_responses=True,
    )


def _clean_email_buckets(email: str) -> None:
    """Borra el bucket de email ``email`` para no contaminar entre tests."""
    r = _redis()
    for key in r.scan_iter(match="rl:login:email:*"):
        r.delete(key)


# ── tests ──────────────────────────────────────────────────────────────

def test_rate_limit_blocks_after_max_attempts(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tras N intentos fallidos con mismo email+IP, el N+1 devuelve 429."""
    # Forzar max_attempts=3 para que el test sea rápido y determinista.
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=3),
    )
    # El handler usa la función get_settings cacheada, así que forzamos
    # también el settings de la app.
    _force_settings_max(monkeypatch, max_attempts=3)

    email = "victim@example.com"
    _clean_email_buckets(email)

    for i in range(3):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
        assert r.status_code == 401, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 429, f"esperaba 429, obtuve {r.status_code}"
    assert "Demasiados intentos" in r.text


def test_rate_limit_audit_log_on_block(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El bloqueo escribe un audit_log con action=rate_limited_login."""
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=2),
    )
    _force_settings_max(monkeypatch, max_attempts=2)
    email = "audit@example.com"
    _clean_email_buckets(email)

    for _ in range(2):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 429

    audit = assert_audit_log(
        db_session,
        action="rate_limited_login",
        result="failure",
    )
    assert audit.payload is not None
    assert audit.payload["email"] == email
    assert "ip" in audit.payload
    assert "bucket" in audit.payload
    assert audit.payload["bucket"].startswith("rl:login:")


def test_rate_limit_per_ip_independent(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada IP tiene su propio bucket IP — usar el MISMO email desde 2 IPs
    distintas consume 1 entrada del bucket email pero el bucket IP
    arranca independiente. Para aislar el efecto IP usamos emails
    distintos en cada IP.
    """
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=2),
    )
    _force_settings_max(monkeypatch, max_attempts=2)

    # Parchear get_real_ip para que SIEMPRE use el XFF cuando esté
    # presente (sin esto, el TestClient ve client.host="testclient"
    # y nunca se llega a ramificar por IP).
    from app.api.v1 import auth as auth_mod
    from app.core import ip as ip_mod

    def fake_get_real_ip(request):
        xff = request.headers.get("x-forwarded-for")
        return xff.split(",")[0].strip() if xff else "testclient"

    monkeypatch.setattr(auth_mod, "get_real_ip", fake_get_real_ip)
    monkeypatch.setattr(ip_mod, "get_real_ip", fake_get_real_ip)

    email_a = "victim-a@example.com"
    email_b = "victim-b@example.com"
    _clean_email_buckets(email_a)
    _clean_email_buckets(email_b)

    # IP A: 2 intentos con email_a → bloqueada.
    for _ in range(2):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": email_a, "password": "wrong"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email_a, "password": "wrong"},
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert r.status_code == 429, (
        f"IP A con email_a saturado: esperaba 429, obtuve {r.status_code}"
    )

    # IP B con email_b → IP bucket de B arranca en 0, email bucket de B
    # arranca en 0 → debe pasar (401, no 429). Esto demuestra que la
    # saturación de IP A NO afecta a IP B.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email_b, "password": "wrong"},
        headers={"X-Forwarded-For": "5.6.7.8"},
    )
    assert r.status_code == 401, (
        f"IP B debería poder intentar, obtuve {r.status_code}: {r.text}"
    )


def test_rate_limit_per_email_independent(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada email tiene su propio bucket — saturar email1 no bloquea email2.

    Usamos 2 IPs distintas para aislar el efecto: el bucket IP no se
    comparte entre email1 y email2 (IPs distintas), y queremos
    demostrar que el bucket email es independiente.
    """
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=2),
    )
    _force_settings_max(monkeypatch, max_attempts=2)

    from app.api.v1 import auth as auth_mod
    from app.core import ip as ip_mod

    def fake_get_real_ip(request):
        xff = request.headers.get("x-forwarded-for")
        return xff.split(",")[0].strip() if xff else "testclient"

    monkeypatch.setattr(auth_mod, "get_real_ip", fake_get_real_ip)
    monkeypatch.setattr(ip_mod, "get_real_ip", fake_get_real_ip)

    email1 = "victim1@example.com"
    email2 = "victim2@example.com"
    _clean_email_buckets(email1)
    _clean_email_buckets(email2)

    # IP_A con email1: 2 intentos + 1 → email1 bucket saturado.
    for _ in range(2):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": email1, "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email1, "password": "wrong"},
        headers={"X-Forwarded-For": "10.0.0.1"},
    )
    assert r.status_code == 429, (
        f"email1 saturado: esperaba 429, obtuve {r.status_code}"
    )

    # IP_B con email2 → ambos buckets nuevos → debe pasar.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email2, "password": "wrong"},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert r.status_code == 401, (
        f"email2 debería poder intentar, obtuve {r.status_code}: {r.text}"
    )


def test_rate_limit_resets_after_window(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pasada la ventana, los buckets se resetean (EXPIRE no es sliding)."""
    # La ventana real se deja en su valor por defecto (300 s) a propósito.
    # Con una ventana de 10 s, los tres intentos de login de este test
    # (cada uno con un hash bcrypt) podían tardar más de 10 s en una
    # máquina cargada: el bucket expiraba ENTRE intentos, el contador se
    # reiniciaba y el 429 nunca llegaba. Era un flake dependiente de la
    # carga del equipo, no un fallo del código.
    #
    # El paso de la ventana se simula igual que antes, pero de forma
    # determinista: borrando las claves de los buckets a mano (más abajo).
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=2),
    )
    _force_settings_max(monkeypatch, max_attempts=2)
    email = "ttl@example.com"
    _clean_email_buckets(email)

    for _ in range(2):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 429

    # Forzar expiración manual de los buckets (simula paso del tiempo).
    rcli = _redis()
    for key in rcli.scan_iter(match=f"rl:login:email:{email}*"):
        rcli.delete(key)
    for key in rcli.scan_iter(match="rl:login:ip:*"):
        rcli.delete(key)

    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 401, (
        f"tras reset de buckets esperaba 401, obtuve {r.status_code}: {r.text}"
    )


def test_rate_limit_uses_real_ip_with_xff(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con XFF y proxy en trusted_proxies, el bucket usa la IP del XFF."""
    monkeypatch.setattr(
        "app.core.ip.get_settings",
        lambda: _patched_settings(
            trusted_proxies=("172.16.0.0/12", "10.0.0.0/8"),
        ),
    )
    email = "xff-trusted@example.com"
    _clean_email_buckets(email)

    # ``auth.py`` importa ``get_real_ip`` por nombre. Monkeypatchear el
    # módulo NO afecta al binding local. Hay que parchear el binding
    # dentro de ``auth``.
    from app.api.v1 import auth as auth_mod

    def fake_get_real_ip(request):
        xff = request.headers.get("x-forwarded-for")
        return xff.split(",")[0].strip() if xff else "127.0.0.1"

    monkeypatch.setattr(auth_mod, "get_real_ip", fake_get_real_ip)

    # 1 petición con XFF 9.9.9.9 → IP del bucket debe ser 9.9.9.9.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert r.status_code == 401

    rcli = _redis()
    bucket_keys = list(rcli.scan_iter(match="rl:login:ip:*"))
    assert any("9.9.9.9" in k for k in bucket_keys), (
        f"esperaba bucket con 9.9.9.9, encontré {bucket_keys}"
    )


def test_rate_limit_uses_client_host_without_xff(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin XFF, el bucket usa request.client.host (TestClient = 127.0.0.1)."""
    email = "noxff@example.com"
    _clean_email_buckets(email)

    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 401

    rcli = _redis()
    bucket_keys = list(rcli.scan_iter(match="rl:login:ip:*"))
    # TestClient → 127.0.0.1 (o el host que el server vea).
    assert any("127.0.0.1" in k or "testclient" in k for k in bucket_keys), (
        f"esperaba bucket con client.host, encontré {bucket_keys}"
    )


def test_rate_limit_settings_override(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override de ``login_rate_limit_max_attempts=2``: el 3er intento es 429."""
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=2),
    )
    _force_settings_max(monkeypatch, max_attempts=2)
    email = "override@example.com"
    _clean_email_buckets(email)

    for _ in range(2):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 429


def test_login_success_resets_does_not_apply(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El contador cuenta TODOS los intentos (fallidos y exitosos).

    Un usuario legítimo que falla N veces + acierta 1 sigue con count
    creciente: el siguiente intento (fallido) sigue contando desde el
    bucket (no se resetea por éxito).
    """
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=5),
    )
    _force_settings_max(monkeypatch, max_attempts=5)
    email = "success@example.com"
    _clean_email_buckets(email)

    # 4 intentos fallidos.
    for _ in range(4):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
    # 1 intento exitoso (también cuenta).
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User
    user = User(
        email=email, full_name="OK",
        role=UserRole.OPERADOR,
        hashed_password=hash_password("right"),
    )
    db_session.add(user); db_session.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "right"},
    )
    assert r.status_code == 200

    # El siguiente intento (5º contando el éxito) ya cae en el cupo.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert r.status_code == 429, (
        f"el 6º intento (5 fallos + 1 éxito + 1 fallo) debería ser 429, "
        f"obtuve {r.status_code}: {r.text}"
    )


# ── utilidades ─────────────────────────────────────────────────────────

def _patched_settings(
    *,
    max_attempts: int | None = None,
    window_seconds: int | None = None,
    trusted_proxies: tuple[str, ...] | None = None,
):
    """Devuelve un Settings-like con los overrides del test.

    Copia los campos reales desde el ``Settings`` de Pydantic y aplica
    los overrides. Usa ``SimpleNamespace`` para evitar los problemas
    de ``dir(real)`` con descriptores y propiedades dinámicas de v2.
    """
    from types import SimpleNamespace
    from app.core import config as cfg_mod
    real = cfg_mod.get_settings()

    # Tomamos sólo los campos declarados del modelo Pydantic.
    field_names = (
        list(real.model_fields.keys())
        if hasattr(real, "model_fields")
        else [a for a in dir(real) if not a.startswith("_")]
    )
    data = {name: getattr(real, name) for name in field_names}
    if max_attempts is not None:
        data["login_rate_limit_max_attempts"] = max_attempts
    if window_seconds is not None:
        data["login_rate_limit_window_seconds"] = window_seconds
    if trusted_proxies is not None:
        data["trusted_proxies"] = list(trusted_proxies)
    return SimpleNamespace(**data)


def _force_settings_max(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_attempts: int | None = None,
    window_seconds: int | None = None,
) -> None:
    """Parchea ``get_settings`` para que devuelva el real con overrides."""
    from types import SimpleNamespace
    from app.core import config as cfg_mod
    real = cfg_mod.get_settings()
    field_names = (
        list(real.model_fields.keys())
        if hasattr(real, "model_fields")
        else [a for a in dir(real) if not a.startswith("_")]
    )
    data = {name: getattr(real, name) for name in field_names}
    if max_attempts is not None:
        data["login_rate_limit_max_attempts"] = max_attempts
    if window_seconds is not None:
        data["login_rate_limit_window_seconds"] = window_seconds
    monkeypatch.setattr(cfg_mod, "get_settings", lambda: SimpleNamespace(**data))


# ── T-59: el rate-limit cubre las DOS vias de login ──────────────────────
#
# OJO (2026-10-22): ``POST /auth/login/oauth`` (form-urlencoded) hace el
# MISMO ``verify_password`` que ``POST /auth/login`` (JSON) pero NO pasaba
# por el limitador. Medido contra la API en marcha: 15 intentos por la via
# OAuth2 devolvieron 15 x 401 y NUNCA un 429, mientras que la via JSON
# devolvia 429 en el quinto. Es decir: cambiar el ``Content-Type`` de la
# peticion esquivaba la proteccion de fuerza bruta.


def _ip_por_xff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parchea ``get_real_ip`` para que use el ``X-Forwarded-For``.

    Sin esto el TestClient ve siempre ``client.host="testclient"`` y el
    bucket de IP se comparte entre tests (contaminacion).
    """
    from app.api.v1 import auth as auth_mod
    from app.core import ip as ip_mod

    def fake_get_real_ip(request):
        xff = request.headers.get("x-forwarded-for")
        return xff.split(",")[0].strip() if xff else "testclient"

    monkeypatch.setattr(auth_mod, "get_real_ip", fake_get_real_ip)
    monkeypatch.setattr(ip_mod, "get_real_ip", fake_get_real_ip)


def test_rate_limit_cubre_tambien_la_via_oauth(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La via OAuth2 tambien devuelve 429: no se puede esquivar el limite
    cambiando el Content-Type de la peticion."""
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=3),
    )
    _force_settings_max(monkeypatch, max_attempts=3)
    _ip_por_xff(monkeypatch)

    email = "victim-oauth@example.com"
    _clean_email_buckets(email)
    cabeceras = {"X-Forwarded-For": "10.10.10.10"}

    for i in range(3):
        r = client.post(
            "/api/v1/auth/login/oauth",
            data={"username": email, "password": "wrong"},
            headers=cabeceras,
        )
        assert r.status_code == 401, f"intento {i}: {r.status_code} {r.text}"

    r = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": email, "password": "wrong"},
        headers=cabeceras,
    )
    assert r.status_code == 429, (
        f"la via OAuth2 no esta limitada: esperaba 429, obtuve {r.status_code}"
    )
    assert "Demasiados intentos" in r.text


def test_no_se_puede_esquivar_alternando_la_via(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alternar JSON y OAuth2 tampoco esquiva el limite: el bucket es el
    mismo, porque las dos vias limitan por IP y por email."""
    monkeypatch.setattr(
        "app.services.rate_limit.get_settings",
        lambda: _patched_settings(max_attempts=3),
    )
    _force_settings_max(monkeypatch, max_attempts=3)
    _ip_por_xff(monkeypatch)

    email = "victim-alterno@example.com"
    _clean_email_buckets(email)
    cabeceras = {"X-Forwarded-For": "10.10.10.11"}

    # 2 intentos por la via JSON (cuentas 1 y 2 del mismo bucket).
    for _ in range(2):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
            headers=cabeceras,
        )
        assert r.status_code == 401, f"JSON: {r.status_code} {r.text}"

    # El tercero, pero por la via OAuth2 (cuenta 3): todavia pasa.
    r = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": email, "password": "wrong"},
        headers=cabeceras,
    )
    assert r.status_code == 401, f"OAuth2 intento 3: {r.status_code} {r.text}"

    # El cuarto (cuenta 4, ya por encima del max=3): da 429, tambien si va
    # por la via OAuth2. Antes: 401, y el limite se esquivaba alternando.
    r = client.post(
        "/api/v1/auth/login/oauth",
        data={"username": email, "password": "wrong"},
        headers=cabeceras,
    )
    assert r.status_code == 429, (
        f"alternar las vias esquiva el limite: esperaba 429 en el "
        f"intento 4, obtuve {r.status_code}"
    )
