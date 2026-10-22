"""Fixtures compartidas: cliente HTTP contra la app en memoria + BD de test.

La BD de test se elige con la variable de entorno ``TEST_DATABASE_URL``:

- **Sin valor** (default local): SQLite en memoria. Es rápido y no
  necesita ningún servicio levantado.
- **Con valor**: PostgreSQL. Es el motor de producción y el único que
  detecta los fallos de dialecto SQL.

Por qué existe este parametrizado (T-04, 2026-10-21)
---------------------------------------------------
Hasta ahora la suite corría SIEMPRE contra SQLite, incluso en el CI, que
levantaba un PostgreSQL real que no se usaba para nada. Un ``strftime()``
(función que sólo existe en SQLite) pasó el CI, llegó a ``main`` y
devolvió HTTP 500 en Docker, donde PostgreSQL lo rechaza con
``function strftime(character varying, timestamp with time zone) does not
exist``. Los tests tienen que poder correr contra el motor real.

Aislamiento entre tests
-----------------------
- **SQLite**: motor nuevo por test (la BD en memoria muere con el motor)
  → cada test arranca con la BD vacía.
- **PostgreSQL**: una única BD para toda la sesión (crear y destruir el
  esquema en cada test sería lentísimo) y ``TRUNCATE ... RESTART IDENTITY
  CASCADE`` entre tests → cada test arranca con las tablas vacías y los
  contadores de ID a cero.

Ninguna suite debe poder tocar la BD de desarrollo: por eso
``DATABASE_URL`` se fuerza aquí al motor de la BD de test ANTES de
importar nada de ``app`` (``get_settings`` cachea la configuración en el
primer import).
"""

from __future__ import annotations

import os

import redis  # sólo el paquete: no depende de las variables de entorno

# ──────────────────────────────────────────────────────────────────────────
# Motor de la BD de test
# ──────────────────────────────────────────────────────────────────────────

SQLITE_URL = "sqlite+pysqlite:///:memory:"

#: URL de la BD de test. Vacía ⇒ SQLite en memoria (default local).
TEST_DATABASE_URL: str = os.environ.get("TEST_DATABASE_URL", "").strip()

#: URL efectiva contra la que corre la suite.
URL_BD_TEST: str = TEST_DATABASE_URL or SQLITE_URL

#: ¿Estamos contra PostgreSQL? Lo consultan los tests de integración.
ES_POSTGRES: bool = URL_BD_TEST.startswith("postgresql")

#: Dialecto efectivo, para los tests que lo necesiten ("postgresql" / "sqlite").
DIALECTO_TEST: str = "postgresql" if ES_POSTGRES else "sqlite"


def _url_async(url: str) -> str:
    """Deriva la URL asíncrona equivalente a una URL síncrona.

    ``psycopg`` (síncrono) → ``asyncpg`` (asíncrono); ``pysqlite`` →
    ``aiosqlite``. Si la URL no se reconoce se devuelve tal cual.
    """
    if url.startswith("sqlite+pysqlite"):
        return "sqlite+aiosqlite:///:memory:"
    if "+psycopg" in url:
        return url.replace("+psycopg", "+asyncpg", 1)
    return url


# Forzamos el motor de la app al de la BD de test. Sin esto, un test que
# se escape del override de sesión escribiría datos de prueba en la BD de
# desarrollo (en el contenedor, ``DATABASE_URL`` apunta a la BD real).
os.environ["DATABASE_URL"] = URL_BD_TEST
os.environ["ASYNC_DATABASE_URL"] = _url_async(URL_BD_TEST)
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ENVIRONMENT", "test")

# La suite usa una base de Redis APARTE para que los buckets de
# rate-limit no se mezclen con los de la app que está en marcha en el
# mismo Redis (backend en :8000, worker de Celery, QA manual). Con la
# base compartida, un POST de la app real incrementa el mismo bucket que
# mide el test y éste ve un 429 antes de tiempo (fallo intermitente, medido
# el 2026-10-21). En CI el job tiene su propio Redis, pero aun así se
# aísla: si la suite y la app comparten base, el resultado de los tests
# depende de lo que esté haciendo la app en ese momento.
#
# La base se elige **por PID** (de la 8 a la 15) y no fija: con dos
# suites lanzadas a la vez (el job replicado en local y otro motor de
# pruebas, por ejemplo) las dos acababan en la 15 y los tests de
# rate-limit de una veían los contadores de la otra. Medido el
# 2026-10-21: con las dos suites en paralelo, ``test_rate_limit_blocks_
# after_max_attempts`` fallaba; en solitario pasa.
#
# Redis tiene 16 bases por defecto (0-15); la 0 la usa la app, así que
# la suite se queda entre la 8 y la 15.
#: Candidatos a URL de Redis, por orden de preferencia:
#:
#: 1. La que venga en el entorno (en el CI es ``redis://localhost:6379/0``).
#: 2. El **nombre del servicio de Docker** (``redis://redis:6379/0``): es
#:    lo que funciona DENTRO de la red de Docker, que es donde corre la
#:    suite cuando va en el contenedor.
#: 3. El **puerto publicado en el host** (``redis://127.0.0.1:6379/0``):
#:    es a donde se llega desde el host (Windows).
#:
#: POR QUÉ la lista (2026-10-22): con el nombre del servicio de Docker
#: como único candidato, desde el host la URL **no resuelve** y cada test
#: pagaba **2,7 s** de timeout de DNS (el fixture de limpieza corre en
#: TODOS los tests: 585 × 2,7 s ≈ 26 minutos de espera pura). Peor: la
#: limpieza **no se hacía**, así que los buckets de rate-limit no se
#: aislaban y los tests de rate-limit veían los contadores de la app
#: que está en marcha en el mismo Redis (el "fallo intermitente" del
#: comentario de arriba).
_CANDIDATOS_REDIS = (
    os.environ.get("REDIS_URL", ""),
    "redis://redis:6379/0",
    "redis://127.0.0.1:6379/0",
)


def _redis_alcanzable(url: str) -> bool:
    """¿Este Redis responde? (con timeout corto: es una comprobación)"""
    try:
        redis.Redis.from_url(
            url, socket_connect_timeout=1, socket_timeout=1
        ).ping()
        return True
    except Exception:
        return False


_URL_REDIS_REAL = next(
    (url for url in _CANDIDATOS_REDIS if url and _redis_alcanzable(url)),
    "redis://127.0.0.1:6379/0",
)

#: Clave con la que una ejecucion reclama una base de Redis.
CLAVE_LOCK_SUITE = "solidapp:suite:lock"
#: Bases de Redis que puede usar la suite (la 0 la usa la app real).
BASES_SUITE = range(8, 16)
#: Caducidad del lock: si el proceso muere sin soltarlo, la base queda
#: libre al cabo de una hora (las suites duran 7-10 minutos).
CADUCIDAD_LOCK = 3600


def _elegir_base_redis_suite(url_base: str) -> int:
    """Toma una base de Redis libre para esta ejecución de la suite.

    POR QUÉ (T-65, 2026-10-22): antes se elegía con ``8 + (pid % 8)``, que
    **no** garantiza que dos ejecuciones paralelas caigan en bases
    distintas: dos PIDs que difieren en un múltiplo de 8 comparten base.
    Medido: con dos suites del host en paralelo (SQLite y PostgreSQL) los
    tests de rate-limit se rompieron mutuamente (5 fallos en cada una:
    "esperaba 429, obtuve 201"), porque compartían base y cada una
    borraba los contadores de la otra al limpiar.

    Ahora cada ejecución **reclama** una base con un lock (``SET NX``): si
    está ocupada, se prueba la siguiente.
    """
    for base in BASES_SUITE:
        cliente = redis.Redis.from_url(
            f"{url_base}/{base}", socket_connect_timeout=1, socket_timeout=1
        )
        try:
            if cliente.set(
                CLAVE_LOCK_SUITE, os.getpid(), nx=True, ex=CADUCIDAD_LOCK
            ):
                return base
        except Exception:
            continue
    raise RuntimeError(
        "no hay ninguna base de Redis libre (8-15) para la suite: hay "
        "demasiadas ejecuciones en paralelo"
    )


_BASE_REDIS_SUITE = _elegir_base_redis_suite(_URL_REDIS_REAL.rsplit("/", 1)[0])
os.environ["REDIS_URL"] = (
    _URL_REDIS_REAL.rsplit("/", 1)[0] + f"/{_BASE_REDIS_SUITE}"
)

import pytest  # noqa: E402 — debe ir después de fijar las variables de entorno
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: F401,E402 — fuerza el registro de todas las tablas en Base.metadata
from app.core.db import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402


def _truncar(engine) -> None:
    """Deja la BD de test vacía (PostgreSQL).

    ``TRUNCATE ... RESTART IDENTITY CASCADE`` borra todas las filas y
    reinicia los contadores de ID (para que los tests que asumen IDs
    bajos se comporten igual que en SQLite) y cascada a las tablas que
    referencian a las truncadas.
    """
    tablas = [f'"{t.name}"' for t in Base.metadata.sorted_tables]
    if not tablas:
        return
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tablas)} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def test_engine():
    """Motor de la BD de test.

    En SQLite no se usa (cada test crea el suyo en memoria) pero se
    expone para que los tests de integración puedan consultar el
    dialecto real contra el que corren.
    """
    if not ES_POSTGRES:
        yield None
        return

    engine = create_engine(URL_BD_TEST, future=True, pool_pre_ping=True)
    # El esquema lo crea y destruye la propia sesión de tests: no
    # dependemos de Alembic (que en CI nadie ha ejecutado).
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def motor_de_test(test_engine):
    """Motor de BD **del dialecto contra el que corre la suite**.

    - SQLite (default local): motor propio en memoria, aislado por test.
    - PostgreSQL (CI): motor compartido, truncado antes de cada test.

    Los tests que necesitan su propia base de datos **deben** usar esta
    fixture en vez de crear un motor SQLite hardcodeado. Si lo hacen al
    revés, siguen corriendo contra SQLite aunque la suite completa esté
    en modo PostgreSQL, y el dialecto real de producción queda sin
    cubrir: es exactamente lo que pasó con ``strftime()``, que llegó a
    ``main`` porque la CI levantaba Postgres y no lo usaba.
    """
    if ES_POSTGRES:
        engine = test_engine
        _truncar(engine)
    else:
        engine = create_engine(
            SQLITE_URL,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        if not ES_POSTGRES:
            engine.dispose()


@pytest.fixture()
def db_session(monkeypatch, test_engine):
    """Sesión de BD aislada para el test.

    Sustituye ``SessionLocal`` que ``app.services.manual_tickets``,
    ``app.services.incidents`` y ``app.services.ingest_service`` abren
    internamente, para que apunten al motor de prueba y vean los datos
    sembrados.
    """
    if ES_POSTGRES:
        # Motor compartido + truncado: cada test ve las tablas vacías.
        engine = test_engine
        _truncar(engine)
    else:
        # Motor propio en memoria: la BD entera muere con él.
        engine = create_engine(
            SQLITE_URL,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    from app.services import manual_tickets as mt_mod
    from app.services import ingest_service as ingest_mod
    from app.services import incidents as inc_mod
    monkeypatch.setattr(mt_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ingest_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(inc_mod, "SessionLocal", SessionLocal)

    # También el ``SessionLocal`` de la app. Los endpoints que abren su
    # propia sesión corta (p.ej. el preview MJPEG, que no puede mantener
    # una conexión del pool durante todo el stream) usan
    # ``app.core.db.SessionLocal``: sin este parche apuntan al motor
    # original, que en SQLite en memoria es OTRA base distinta (cada
    # conexión abre su propia) y en PostgreSQL es la base de desarrollo.
    from app.core import db as db_mod
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        if not ES_POSTGRES:
            engine.dispose()


#: ``None`` = sin probar; ``False`` = Redis no es accesible desde aqui
#: (se deja de reintentar en cada test); ``True`` = accesible.
_REDIS_ACCESIBLE: bool | None = None


@pytest.fixture(autouse=True)
def _clean_redis_counters():
    """Limpia todas las claves de Redis usadas por ``app.services.alerts``.

    Sin esto, los contadores

    - ``camera:{id}:consecutive_fails`` y ``camera:{id}:ocr_alert_lock``
      (escritos por ``record_ocr_failure`` / ``reset_ocr_failure``),
    - ``camera:{id}:consecutive_offline`` y ``camera:{id}:offline_lock``
      (escritos por ``record_camera_offline`` / ``reset_camera_offline``),

    se acumulan entre tests porque la BD usa StaticPool (los IDs se
    reinician) pero Redis NO se resetea. Un test que cree cámara id=1
    después de otro que tocó cámara id=1 hereda su contador.

    Sólo barremos IDs 1..200 porque los tests crean cámaras con IDs
    bajos en la práctica. Si Redis no responde, ignoramos: el resto
    de la suite sigue funcionando y los tests que tocan Redis son
    tolerantes a fallos del broker.

    POR QUÉ el timeout corto y el flag (2026-10-22): en el host, la URL
    del compose (``redis://redis:6379``) **no resuelve** y el intento
    tardaba **2,7 s** en fallar (el resolver del sistema). Como este
    fixture corre en **todos** los tests, la suite del host pasaba de
    7 minutos a más de 25 (585 tests × 2,7 s de espera pura).
    Ahora: timeout de socket corto y, si Redis no está accesible, **no
    se reintenta en cada test** (en el CI sí está: redis://localhost).
    """
    global _REDIS_ACCESIBLE
    if _REDIS_ACCESIBLE is False:
        # Ya se comprobó que no hay Redis: no se vuelve a intentarlo.
        return
    try:
        from app.services.alerts import (
            _consecutive_key, _lock_key,
            _consecutive_offline_key, _offline_lock_key,
        )
        from app.core.config import get_settings

        # Timeout corto: si Redis no está, hay que enterarse deprisa.
        client = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        client.ping()
        for cam_id in range(1, 200):
            client.delete(
                _consecutive_key(cam_id), _lock_key(cam_id),
                _consecutive_offline_key(cam_id), _offline_lock_key(cam_id),
            )
        # Sprint Fase 3C: rate-limit de login. Las claves usan como
        # sufijo la IP y el email (no el cam_id), pero las borramos
        # también con un SCAN para no contaminar entre tests.
        for key in client.scan_iter("rl:login:*"):
            client.delete(key)
        # Sprint Fase 3D: token blacklist + rate-limit de endpoints.
        # - ``jwt:blacklist:*``: jti de tokens invalidados en logout.
        # - ``rl:{scope}:*``: buckets genéricos del ``EndpointRateLimiter``
        #   (``users_create``, ``users_update``, ``vehicles_create``,
        #   ``vehicles_update``, ...).
        for key in client.scan_iter("jwt:blacklist:*"):
            client.delete(key)
        for key in client.scan_iter("rl:users_*"):
            client.delete(key)
        for key in client.scan_iter("rl:vehicles_*"):
            client.delete(key)
        # Sprint R5 (2026-07-06): rate-limit en parkings/tariffs/cameras.
        for prefix in ("rl:parkings_*", "rl:tariffs_*", "rl:cameras_*",
                       "rl:geofences_*"):
            for key in client.scan_iter(prefix):
                client.delete(key)
        # Sprint R2-followup: set de jtis activos por usuario que mantiene
        # ``session_tracker`` para que el ``POST /auth/logout/all`` pueda
        # invalidarlos. Sin esto, los jtis de tests previos contaminan
        # el set del user_id usado por otros tests.
        for key in client.scan_iter("user:*:active_jtis"):
            client.delete(key)
    except Exception:
        # Redis no está accesible: no se reintenta en cada test.
        _REDIS_ACCESIBLE = False
        return
    _REDIS_ACCESIBLE = True
    return


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
