"""T-167 (2026-10-24): la alarma de OCR no puede depender del ritmo del ping.

El defecto
----------
``alerts.COUNT_TTL_SECONDS`` eran **600 s fijos**, el umbral son 5 fallos
(``settings.ocr_frames_before_fail``) y el TTL se ponía **sólo en el
primer ``INCR``** (``if count == 1``). O sea que la ventana iba **desde el
primer fallo**: si los fallos llegaban más espaciados que
``600/5 = 120 s``, el contador caducaba antes de poder llegar al umbral y
**la alerta ``OCR_FAILED`` nunca saltaba**.

Medido (2026-10-24, contra el Redis real del stack, dentro del
contenedor): una serie de 5 fallos separados 3 s (con un TTL escalado a
8 s para no esperar 10 minutos: ``3 s > 8/5 = 1,6 s``) dejó el contador
en 2 y **no creó ninguna alerta**; y el TTL de la clave **no se
renovaba** (600 → 597 → 597 tras el segundo fallo).

El arreglo
----------
1. El TTL se **deriva del umbral** (``umbral × intervalo esperado ×
   margen``): deja de ser un número mágico y escala con el umbral.
2. El TTL se **renueva en cada fallo** (ventana deslizante): el contador
   sobrevive mientras los fallos lleguen separados menos que el TTL, en
   vez de morir en el primero que se pase del TTL.

OJO: esto **no** contradice el T-150 (allí se renovaba el TTL de un
*lock*; aquí el de un *contador*, y la renovación es lo que lo convierte
en ventana deslizante).

OJO (2): ``ping_camera`` **no se despacha** hoy (T-164): el pipeline real
es el push externo. Esta ruta está **dormida**; el arreglo es correcto y
queda probado, pero no vigila nada hasta que alguien active el ping.
"""
from __future__ import annotations

import time

import pytest
import redis as redis_lib
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — fuerza el registro de tablas en Base.metadata
from app.models.audit import Alert
from app.models.parking import Camera, Parking
from app.services import alerts as alerts_mod

#: Cámara "de laboratorio": un id que ninguna otra fila usa (y que el
#: fixture de limpieza de Redis del conftest no toca, porque barre 1..200).
CAM_ID = 987654


# ── Fake Redis con reloj simulado (el TTL de verdad, sin esperar) ──
class _FakeRedisConTTL:
    """Redis en memoria que **respeta el TTL**, con un reloj simulado.

    Sin esto no se puede comprobar el defecto de un vistazo: la ventana
    del contador depende de cuándo caduca la clave, y eso con un Redis
    de verdad son minutos de espera.
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.caducos: dict[str, float] = {}
        self.ahora = 0.0

    # -- reloj --
    def avanzar(self, segundos: float) -> None:
        """Pasa el tiempo y caduca lo que toque."""
        self.ahora += segundos
        self._caducar()

    def _caducar(self) -> None:
        for clave in list(self.caducos):
            if self.caducos[clave] <= self.ahora:
                del self.data[clave]
                del self.caducos[clave]

    # -- comandos de Redis --
    def incr(self, key: str) -> int:
        self._caducar()
        valor = int(self.data.get(key, "0")) + 1
        self.data[key] = str(valor)
        return valor

    def expire(self, key: str, ttl: int) -> bool:
        self.caducos[key] = self.ahora + ttl
        return True

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self._caducar()
        if nx and key in self.data:
            return None
        self.data[key] = value
        if ex is not None:
            self.caducos[key] = self.ahora + ex
        return True

    def delete(self, *keys: str) -> int:
        self._caducar()
        borrados = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                borrados += 1
            self.caducos.pop(k, None)
        return borrados


@pytest.fixture()
def entorno_alerta(monkeypatch, motor_de_test):
    """BD de la suite + Redis con reloj + stub de email y de ajustes."""
    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake = _FakeRedisConTTL()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)

    enviados: list[dict] = []

    def _stub(*args, **kwargs):
        enviados.append({"args": args, "kwargs": kwargs})
        return True

    import app.services.email as email_mod

    monkeypatch.setattr(email_mod, "encolar_correo_alerta", _stub)

    class _Ajustes:
        ocr_frames_before_fail = 5
        # El intervalo esperado: 1 s (para que el TTL quepa en la escala
        # del test). En producción son 60 s.
        ocr_ping_interval_seconds = 1
        heartbeat_failures_before_alert = 3
        heartbeat_interval_seconds = 60
        redis_url = "redis://stub"

    monkeypatch.setattr("app.services.alerts.get_settings", lambda: _Ajustes())
    # El suelo del TTL a 1 s: si no, el mínimo (60 s) mandaría sobre el
    # TTL calculado y el test tardaría 60 s por fallo.
    monkeypatch.setattr(alerts_mod, "MIN_COUNT_TTL_SECONDS", 1)

    db = SessionLocal()
    try:
        yield db, fake, enviados
    finally:
        db.close()
        engine.dispose()


def _camara(db) -> Camera:
    parking = Parking(code="P-T167", name="P-T167", address="x", city="y")
    db.add(parking)
    db.flush()
    cam = Camera(
        id=CAM_ID,
        parking_id=parking.id,
        code="CAM-T167",
        name="Cámara T167",
        rtsp_url="rtsp://demo.invalid/t167",
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def test_una_serie_de_fallos_mas_espaciada_que_el_umbral_dispara_la_alerta(
    entorno_alerta,
) -> None:
    """El caso que no disparaba: fallos más separados que TTL/umbral.

    TTL = 5 × 1 s × 2 (margen) = 10 s; separación 3 s (> 10/5 = 2 s).
    Con el TTL anclado al primer fallo, el contador caduca en el cuarto
    fallo y la alerta **no** salta.
    """
    db, fake, enviados = entorno_alerta
    cam = _camara(db)

    umbral = 5
    ttl = alerts_mod.ttl_contador_fallos(umbral, 1)
    assert ttl == 10, f"el TTL del test no es el esperado (era {ttl})"
    separacion = 3.0
    assert separacion > ttl / umbral, "el caso no reproduce el defecto"

    alerta = None
    for _ in range(umbral):
        alerta = alerts_mod.record_ocr_failure(cam)
        fake.avanzar(separacion)

    assert alerta is not None, (
        "5 fallos seguidos (uno cada 3 s, con un TTL de 10 s) NO dispararon "
        "la alerta: la ventana del contador no llega al umbral"
    )
    assert alerta.type == "ocr_failed"
    assert alerta.context["consecutive_fails"] == umbral
    assert db.query(Alert).count() == 1
    assert len(enviados) == 1


def test_el_contador_no_caduca_si_los_fallos_siguen_llegando(entorno_alerta) -> None:
    """Con el TTL renovado, el contador **no** se reinicia por el camino."""
    db, fake, _enviados = entorno_alerta
    cam = _camara(db)

    for _ in range(4):
        alerts_mod.record_ocr_failure(cam)
        fake.avanzar(3.0)

    contador = fake.data[alerts_mod._consecutive_key(cam.id)]
    assert contador == "4", (
        f"el contador se reinició (vale {contador}): el TTL no se renueva "
        "en cada fallo"
    )


def test_el_ttl_crece_con_el_umbral() -> None:
    """El TTL tiene que ser coherente con el umbral (ya no es un fijo)."""
    assert alerts_mod.ttl_contador_fallos(5, 60) == 600
    assert alerts_mod.ttl_contador_fallos(20, 60) == 2400
    assert alerts_mod.ttl_contador_fallos(5, 60) < alerts_mod.ttl_contador_fallos(
        20, 60
    )
    # Con un umbral de 1 el TTL no puede ser menor que el suelo.
    assert alerts_mod.ttl_contador_fallos(1, 1) >= alerts_mod.MIN_COUNT_TTL_SECONDS


def test_el_ttl_del_contador_se_renueva_en_cada_fallo(
    monkeypatch, motor_de_test,
) -> None:
    """Contra el Redis **real**, por el camino real (``record_ocr_failure``).

    El TTL de la clave tiene que **volver a su valor** tras cada fallo:
    con el TTL anclado al primer fallo, el contador se queda con la
    ventana que le queda del primer INCR y una serie de fallos más
    espaciada que ``TTL/umbral`` nunca llega al umbral.
    """
    try:
        from app.core.config import get_settings

        rds = redis_lib.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        rds.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no hay Redis en este entorno: {exc}")

    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: rds)

    import app.services.email as email_mod

    monkeypatch.setattr(email_mod, "encolar_correo_alerta", lambda **kw: True)

    class _Ajustes:
        ocr_frames_before_fail = 5
        ocr_ping_interval_seconds = 60
        heartbeat_failures_before_alert = 3
        heartbeat_interval_seconds = 60
        redis_url = "redis://stub"

    monkeypatch.setattr("app.services.alerts.get_settings", lambda: _Ajustes())

    db = SessionLocal()
    clave = alerts_mod._consecutive_key(CAM_ID)
    rds.delete(clave)
    try:
        cam = _camara(db)
        alerts_mod.record_ocr_failure(cam)
        ttl_antes = rds.ttl(clave)
        assert 0 < ttl_antes <= 600, (
            f"el TTL del contador no es el esperado (era {ttl_antes})"
        )

        # Redis devuelve el TTL redondeado al segundo, así que se espera
        # lo suficiente para que **baje** de forma visible.
        time.sleep(3.0)
        ttl_medio = rds.ttl(clave)
        assert ttl_medio < ttl_antes, (
            f"el TTL no ha bajado ({ttl_antes} -> {ttl_medio})"
        )

        # Un fallo nuevo tiene que **renovar** el TTL.
        alerts_mod.record_ocr_failure(cam)
        ttl_despues = rds.ttl(clave)
        assert ttl_despues > ttl_medio, (
            f"el TTL no se ha renovado ({ttl_medio} -> {ttl_despues}): la "
            "ventana del contador sigue anclada en el primer fallo"
        )
    finally:
        rds.delete(clave)
        db.close()
        engine.dispose()
