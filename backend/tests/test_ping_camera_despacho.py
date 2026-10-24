"""T-177 (2026-10-24): el ping a las cámaras se despacha cada 10 minutos.

El defecto
----------
``solidapp.ping_camera`` (agarra el frame RTSP, lo manda al OCR y crea el
ticket) **existía pero no se despachaba**: no estaba en el
``beat_schedule`` y nadie la encolaba. La puerta
``tools/verificar_tareas_celery.py`` lo tenía **exento** con el motivo
«despacharla es una decisión de producto».

El arreglo (decisión de producto del 2026-10-24)
-----------------------------------------------
1. Una tarea nueva, ``solidapp.ping_cameras``, vive en el ``beat_schedule``
   y encola un ``solidapp.ping_camera`` por **cada cámara activa**. El
   intervalo sale de un ajuste (``PING_CAMERA_INTERVAL_SECONDS``,
   600 s), no de un número escrito a fuego.
2. El fan-out es **resiliente**: una cámara que falle al encolarse no
   impide encolar las demás, y devuelve un recuento.
3. **No se acumula**: si el ping de una cámara ya está encolado o en
   marcha, no se encola otro (lock por cámara en Redis, TTL igual al
   intervalo).
4. Se distingue **«el OCR no respondió»** de **«el OCR respondió y no
   leyó nada»**: un servicio caído no puede generar una alarma
   ``OCR_FAILED`` por cámara (51 en este repo).
5. El TTL del contador de fallos de OCR es coherente con el intervalo
   **real** (600 s): una serie de fallos espaciados como el intervalo
   **sí** dispara la alarma.

Estos tests **fallan con el defecto** (el beat sin el despacho, el fan-out
sin lock, el OCR que no responde contado como fallo de cámara, el TTL
desalineado) y **pasan con el arreglo**.
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.parking import Camera, Parking
from app.services import alerts as alerts_mod
from app.services.ocr.client import OcrClient, OcrResultado
from tests._audit_helpers import monkeypatch_tasks_session

# ── Redis en memoria con reloj simulado ───────────────────────────────
#: Tope de los ids de cámara que usan los tests (el fixture de limpieza
#: del conftest barre 1..200; estos ids quedan fuera a propósito).
CAM_ID = 987654


class _FakeRedis:
    """Redis en memoria que respeta el TTL, con reloj simulado.

    Implements just what the locks (``set``/``eval``) and the alert
    counters (``incr``/``expire``/``set``/``delete``) use.
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.caducos: dict[str, float] = {}
        self.ahora = 0.0

    # -- reloj --
    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos
        self._caducar()

    def _caducar(self) -> None:
        for clave in list(self.caducos):
            if self.caducos[clave] <= self.ahora:
                del self.data[clave]
                del self.caducos[clave]

    def ttl(self, clave: str) -> int:
        self._caducar()
        if clave not in self.data:
            return -2
        return int(self.caducos.get(clave, 0) - self.ahora)

    # -- comandos --
    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self._caducar()
        if nx and key in self.data:
            return None
        self.data[key] = value
        if ex is not None:
            self.caducos[key] = self.ahora + ex
        return True

    def get(self, key: str) -> str | None:
        self._caducar()
        return self.data.get(key)

    def delete(self, *keys: str) -> int:
        self._caducar()
        borrados = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                borrados += 1
            self.caducos.pop(k, None)
        return borrados

    def incr(self, key: str) -> int:
        self._caducar()
        valor = int(self.data.get(key, "0")) + 1
        self.data[key] = str(valor)
        return valor

    def expire(self, key: str, ttl: int) -> bool:
        self._caducar()
        if key not in self.data:
            return False
        self.caducos[key] = self.ahora + ttl
        return True

    def eval(self, script: str, numkeys: int, *args):
        """Emula los dos scripts Lua que usa el worker (soltar/renovar)."""
        clave, token = args[0], args[1]
        if self.data.get(clave) != token:
            return 0
        if "expire" in script:
            self.caducos[clave] = self.ahora + int(args[2])
            return 1
        self.delete(clave)
        return 1


# ── Utilidades ────────────────────────────────────────────────────────
def _sembrar_camaras(db: Session, n_activas: int = 3,
                     n_inactivas: int = 1) -> list[Camera]:
    parking = Parking(code="P-T177", name="P-T177", address="x", city="y")
    db.add(parking)
    db.flush()
    cams: list[Camera] = []
    for i in range(n_activas + n_inactivas):
        cam = Camera(
            parking_id=parking.id,
            code=f"CAM-T177-{i}",
            name=f"Camara {i}",
            # OJO (T-177, integración): una URL que **no** está en
            # ``HEARTBEAT_SKIP_URL_PREFIXES`` (que trae ``rtsp://demo.invalid``
            # por defecto): el ping respeta esa lista, igual que el
            # heartbeat, para no generar alertas de cámaras de mentira.
            rtsp_url=f"rtsp://cam-t177.invalid/t177/{i}",
            is_active=i < n_activas,
        )
        db.add(cam)
        cams.append(cam)
    db.commit()
    for cam in cams:
        db.refresh(cam)
    return cams


class _TareaFalsa:
    """Doble de ``ping_camera`` que registra lo que se encola."""

    def __init__(self, falla_en: int | None = None) -> None:
        self.encolados: list[tuple] = []
        self.intentos = 0
        self.falla_en = falla_en

    def delay(self, *args, **kwargs):
        # ``intentos`` (y no ``len(encolados)``): el fallo **no** cuenta
        # como encolado, así que si no se contara los intentos, la
        # cámara que falla fallaría también la siguiente.
        if self.falla_en is not None and self.intentos == self.falla_en:
            self.intentos += 1
            raise RuntimeError("el broker no responde")
        self.intentos += 1
        self.encolados.append(args)
        return None


class _Entorno:
    """Lo que devuelve el fixture: el módulo, el Redis y los dobles."""

    def __init__(self, tasks_mod, fake, tarea, db, ping_original) -> None:
        self.tasks_mod = tasks_mod
        self.fake = fake
        self.tarea = tarea
        self.db = db
        #: La tarea **real** (``ping_camera`` de Celery), que el fixture
        #: sustituye por el doble en ``tasks_mod.ping_camera``.
        self.ping_original = ping_original


@pytest.fixture()
def entorno_ping(monkeypatch, db_session):
    """BD de la suite + Redis en memoria + doble de la tarea ``ping_camera``."""
    from app.workers import tasks as tasks_mod

    monkeypatch_tasks_session(monkeypatch, db_session)
    fake = _FakeRedis()
    monkeypatch.setattr(tasks_mod, "_redis_client", lambda: fake)
    ping_original = tasks_mod.ping_camera
    tarea = _TareaFalsa()
    monkeypatch.setattr(tasks_mod, "ping_camera", tarea)
    return _Entorno(tasks_mod, fake, tarea, db_session, ping_original)


# ── 1. El beat ────────────────────────────────────────────────────────
def test_el_beat_despacha_el_ping_con_el_intervalo_del_ajuste() -> None:
    """El beat tiene que publicar ``ping_cameras`` con el **ajuste**.

    Con el intervalo escrito a fuego, cambiar el ritmo del ping
    obligaría a tocar dos ficheros (y a que se olvidaran de uno).
    """
    from app.workers.celery_app import celery_app

    entrada = celery_app.conf.beat_schedule.get("ping-cameras-every-10min")
    assert entrada is not None, (
        "el beat no publica el ping: solidapp.ping_cameras no está en el "
        "beat_schedule (el ping NO se despacharía)"
    )
    assert entrada["task"] == "solidapp.ping_cameras"
    settings = get_settings()
    assert entrada["schedule"] == settings.ping_camera_interval_seconds
    assert settings.ping_camera_interval_seconds == 600, (
        "el intervalo por defecto del ping no son 10 minutos"
    )


def test_los_dos_intervalos_por_defecto_no_se_desvían() -> None:
    """``OCR_PING_INTERVAL_SECONDS`` y ``PING_CAMERA_INTERVAL_SECONDS``.

    El TTL del contador de fallos de OCR se deriva del **primer** y el
    ping se despacha con el **segundo**: si uno se cambia y el otro no,
    la alarma ``OCR_FAILED`` vuelve a no saltar (o salta antes de tiempo).
    """
    por_defecto_ocr = Settings.model_fields["ocr_ping_interval_seconds"].default
    por_defecto_ping = Settings.model_fields["ping_camera_interval_seconds"].default
    assert por_defecto_ocr == por_defecto_ping == 600, (
        "los dos intervalos por defecto han divergido "
        f"(OCR={por_defecto_ocr}, PING={por_defecto_ping})"
    )


# ── 2. El fan-out ─────────────────────────────────────────────────────
def test_el_fanout_encola_un_ping_por_camara_activa(entorno_ping) -> None:
    """Una cámara activa = un ping encolado (y las inactivas, ninguno)."""
    _sembrar_camaras(entorno_ping.db, n_activas=3, n_inactivas=1)

    resultado = entorno_ping.tasks_mod.ping_cameras()

    assert resultado["encoladas"] == 3, resultado
    assert resultado["omitidas"] == 0, resultado
    assert resultado["camaras"] == 3, resultado
    assert len(entorno_ping.tarea.encolados) == 3
    encoladas = {args[0] for args in entorno_ping.tarea.encolados}
    activas = {
        cam.id
        for cam in entorno_ping.db.query(Camera)
        .filter(Camera.is_active.is_(True))
        .all()
    }
    assert encoladas == activas


def test_el_fanout_se_salta_las_urls_de_la_lista(entorno_ping) -> None:
    """Las URLs de ``HEARTBEAT_SKIP_URL_PREFIXES`` no se pingean.

    Es la misma lista que usa el heartbeat. Sin esto, en desarrollo el
    ping generaba una alerta ``CAMERA_OFFLINE`` por cada una de las 49
    cámaras de mentira del seed (medido: 206 -> 255 alertas).
    """
    _sembrar_camaras(entorno_ping.db, n_activas=2, n_inactivas=0)

    # Una de las dos cámaras pasa a tener una URL de la lista.
    camara = (
        entorno_ping.db.query(Camera)
        .filter(Camera.is_active.is_(True))
        .order_by(Camera.id)
        .first()
    )
    assert camara is not None
    camara.rtsp_url = "rtsp://demo.invalid/t177/saltada"
    entorno_ping.db.commit()

    resultado = entorno_ping.tasks_mod.ping_cameras()

    assert resultado["saltadas"] == 1, resultado
    assert resultado["encoladas"] == 1, resultado
    encoladas = {args[0] for args in entorno_ping.tarea.encolados}
    assert camara.id not in encoladas, "se ha pingeado una cámara de la lista"


def test_el_fanout_no_encola_dos_veces_la_misma_camara(entorno_ping) -> None:
    """El ping encolado y **en marcha** bloquea el siguiente.

    Sin el lock por cámara, con una cámara colgada la cola se llenaba
    sola: cada ronda añadiría otro mensaje para la misma cámara.
    """
    _sembrar_camaras(entorno_ping.db, n_activas=2, n_inactivas=0)

    primera = entorno_ping.tasks_mod.ping_cameras()
    assert primera["encoladas"] == 2, primera

    # La segunda ronda: los pings anteriores ni siquiera han empezado
    # (el doble de la tarea no ejecuta nada), así que están encolados.
    segunda = entorno_ping.tasks_mod.ping_cameras()
    assert segunda["encoladas"] == 0, segunda
    assert segunda["omitidas"] == 2, segunda
    assert len(entorno_ping.tarea.encolados) == 2, "se ha encolado un ping de más"


def test_una_camara_que_falla_no_impide_encolar_las_demas(entorno_ping) -> None:
    """El fan-out es resiliente: una cámara rota no tumba la ronda."""
    _sembrar_camaras(entorno_ping.db, n_activas=3, n_inactivas=0)

    tarea = _TareaFalsa(falla_en=1)  # falla la segunda
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(entorno_ping.tasks_mod, "ping_camera", tarea)

    resultado = entorno_ping.tasks_mod.ping_cameras()

    assert resultado["encoladas"] == 2, resultado
    assert resultado["omitidas"] == 1, resultado
    assert len(tarea.encolados) == 2
    monkeypatch.undo()


def test_el_ping_suelta_el_lock_al_terminar(entorno_ping) -> None:
    """Al terminar, la cámara queda libre para la siguiente ronda.

    Si el lock no se soltara, la cámara no volvería a pingarse hasta
    que el TTL (600 s) caducara: el doble de intervalo.
    """
    tasks_mod = entorno_ping.tasks_mod
    cams = _sembrar_camaras(entorno_ping.db, n_activas=1, n_inactivas=0)
    cam = cams[0]

    # Se encola a mano, como lo hace el fan-out (con su token).
    token = "token-de-prueba"
    tasks_mod._tomar_lock(f"ping_camera:{cam.id}", ttl=600, token=token)
    assert entorno_ping.fake.get(f"celery:lock:ping_camera:{cam.id}") == token

    # El ping termina (el frame falla: la cámara está caída).
    async def _grab_falla(_cam):
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tasks_mod, "grab_frame", _grab_falla)
    monkeypatch.setattr(
        tasks_mod, "record_camera_offline", lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(
        tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None,
    )

    entorno_ping.ping_original(cam.id, token)
    monkeypatch.undo()

    assert entorno_ping.fake.get(f"celery:lock:ping_camera:{cam.id}") is None, (
        "el lock de la cámara no se ha soltado: esa cámara no volvería a "
        "pingarse hasta que caducase el TTL"
    )


# ── 3. El OCR: «no respondió» ≠ «respondió y no leyó nada» ─────────────
def test_el_ocr_que_no_responde_cuenta_como_fallo_de_la_lectura(
    monkeypatch, db_session,
) -> None:
    """Un servicio OCR que no contesta **sí** es un fallo de la lectura.

    T-181 (2026-10-24): antes esto no contaba, y el motivo era no culpar
    a las cámaras de un problema del servicio. Pero entonces **nadie
    detectaba** que el motor OCR estaba muerto, que es justo lo que el
    usuario decidió al activar el ping (D7). Ahora cuenta, y el mensaje
    de la alarma dice que el problema fue el **servicio** (eso lo
    comprueba ``test_la_alarma_dice_que_fue_el_servicio``).
    """
    from app.workers import tasks as tasks_mod

    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = Parking(code="P-T177B", name="P-T177B", address="x", city="y")
    db_session.add(parking)
    db_session.flush()
    cam = Camera(
        parking_id=parking.id, code="CAM-T177B", name="c",
        rtsp_url="rtsp://demo.invalid/t177b",
    )
    db_session.add(cam)
    db_session.commit()
    db_session.refresh(cam)

    async def _grab_ok(_cam):
        return b"\xff\xd8\xff\xe0"

    class _OcrMuerto:
        async def reconocer(self, frame):
            return OcrResultado(hits=[], respondio=False, motivo="no_disponible")

    fallos: list = []
    monkeypatch.setattr(tasks_mod, "grab_frame", _grab_ok)
    monkeypatch.setattr(tasks_mod, "get_ocr_client", lambda: _OcrMuerto())
    monkeypatch.setattr(
        tasks_mod, "record_ocr_failure",
        lambda *a, **kw: fallos.append((a, kw)) or None,
    )
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    resultado = tasks_mod.ping_camera(cam.id)

    assert resultado["status"] == "ocr_no_disponible", resultado
    assert len(fallos) == 1, (
        "el OCR que no respondió no se ha contado como fallo de la lectura: "
        "nadie detectaría que el motor OCR está muerto"
    )
    # El motivo se pasa a la alarma: el mensaje dice que fue el servicio.
    assert fallos and fallos[0][1].get("motivo") == "no_disponible", fallos


def test_el_ocr_que_responde_y_no_lee_nada_no_cuenta_como_fallo(
    monkeypatch, db_session,
) -> None:
    """El OCR respondió y no leyó nada ⇒ **no** es un fallo de OCR.

    T-181 (2026-10-24), medido: el OCR responde ``[]`` (HTTP 200) a un
    frame **sin vehículos**, que es el caso normal de una entrada de
    parking vacía. Contarlo como fallo producía una falsa alarma por
    cámara cada hora (medido: alarma id=401 con una cámara sana).
    """
    from app.workers import tasks as tasks_mod

    monkeypatch_tasks_session(monkeypatch, db_session)
    parking = Parking(code="P-T177C", name="P-T177C", address="x", city="y")
    db_session.add(parking)
    db_session.flush()
    cam = Camera(
        parking_id=parking.id, code="CAM-T177C", name="c",
        rtsp_url="rtsp://demo.invalid/t177c",
    )
    db_session.add(cam)
    db_session.commit()
    db_session.refresh(cam)

    async def _grab_ok(_cam):
        return b"\xff\xd8\xff\xe0"

    class _OcrQueResponde:
        async def reconocer(self, frame):
            return OcrResultado(hits=[], respondio=True, motivo="sin_lecturas")

    fallos: list = []
    monkeypatch.setattr(tasks_mod, "grab_frame", _grab_ok)
    monkeypatch.setattr(tasks_mod, "get_ocr_client", lambda: _OcrQueResponde())
    monkeypatch.setattr(
        tasks_mod, "record_ocr_failure",
        lambda *a, **kw: fallos.append(a) or None,
    )
    monkeypatch.setattr(tasks_mod, "reset_ocr_failure", lambda *_a, **_kw: None)
    monkeypatch.setattr(tasks_mod, "reset_camera_offline", lambda *_a, **_kw: None)

    resultado = tasks_mod.ping_camera(cam.id)

    assert resultado["status"] == "ok", resultado
    assert not fallos, (
        "el OCR que respondió y no leyó nada se ha contado como fallo: "
        "una entrada de parking vacía daría una falsa alarma por cámara"
    )


def test_la_alarma_dice_que_fue_el_servicio(monkeypatch, motor_de_test) -> None:
    """La alarma ``OCR_FAILED`` no culpa a la cámara: dice «el servicio».

    OJO: ``alerts.py`` abre su **propia** sesión (``SessionLocal``), así
    que hay que apuntarla a la de test (el patrón del repo).
    """
    from sqlalchemy.orm import sessionmaker

    from app.services import alerts as alerts_mod

    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)

    import app.services.email as email_mod

    monkeypatch.setattr(
        email_mod, "encolar_correo_alerta", lambda **kw: True,
    )

    class _Ajustes:
        ocr_frames_before_fail = 5
        ocr_ping_interval_seconds = 600
        heartbeat_failures_before_alert = 3
        heartbeat_interval_seconds = 60
        redis_url = "redis://stub"

    monkeypatch.setattr("app.services.alerts.get_settings", lambda: _Ajustes())

    db = SessionLocal()
    try:
        parking = Parking(code="P-T177E", name="P-T177E", address="x", city="y")
        db.add(parking)
        db.flush()
        cam = Camera(
            id=CAM_ID + 1,
            parking_id=parking.id,
            code="CAM-T177E",
            name="c",
            rtsp_url="rtsp://cam-t177.invalid/t177e",
        )
        db.add(cam)
        db.commit()
        db.refresh(cam)

        # La alarma sale al llegar al umbral (``ocr_frames_before_fail``).
        alerta = None
        for _ in range(5):
            alerta = alerts_mod.record_ocr_failure(
                cam, None, motivo="no_disponible"
            )

        assert alerta is not None, "no se ha creado la alarma"
        assert "servicio OCR" in (alerta.message or ""), alerta.message
        assert (alerta.context or {}).get("motivo") == "no_disponible", (
            alerta.context
        )
    finally:
        db.close()


def test_el_cliente_ocr_distingue_no_respondio_de_no_leyo() -> None:
    """El cliente dice si el servicio **contestó**."""
    import asyncio

    def _correr(handler):
        transporte = httpx.MockTransport(handler)
        cliente = OcrClient(base_url="http://ocr.test", transport=transporte)
        return asyncio.run(cliente.reconocer(b"frame"))

    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no hay nadie", request=request)

    def _vacio(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    caido = _correr(_timeout)
    assert caido.respondio is False, caido
    assert caido.hits == []

    leido = _correr(_vacio)
    assert leido.respondio is True, leido
    assert leido.hits == []
    assert leido.motivo == "sin_lecturas"


# ── 4. El TTL de la alarma, con el intervalo REAL ─────────────────────
def test_el_ttl_del_contador_aguanta_el_intervalo_real() -> None:
    """El TTL tiene que ser **mayor** que el intervalo real del ping.

    Con el TTL justo en el intervalo, el contador caducaría en el mismo
    momento en que llega el siguiente fallo (y la alarma no saltaría).
    """
    settings = get_settings()
    ttl = alerts_mod.ttl_contador_fallos(
        settings.ocr_frames_before_fail, settings.ping_camera_interval_seconds
    )
    assert ttl > settings.ping_camera_interval_seconds, (
        f"el TTL ({ttl} s) no aguanta el intervalo real del ping "
        f"({settings.ping_camera_interval_seconds} s)"
    )
    # Con el umbral por defecto hacen falta 5 fallos: la ventana tiene que
    # aguantar los 5 intervalos.
    assert ttl >= settings.ocr_frames_before_fail * settings.ping_camera_interval_seconds


def test_una_serie_de_fallos_espaciados_como_el_intervalo_real_dispara_la_alerta(
    monkeypatch, motor_de_test,
) -> None:
    """5 fallos separados **600 s** (el intervalo real) → la alerta salta.

    Es el caso que con el TTL de 60 s (o con el TTL anclado al primer
    fallo) **no** saltaba: el contador caducaba antes de poder llegar al
    umbral.
    """
    from sqlalchemy.orm import sessionmaker

    engine = motor_de_test
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(alerts_mod, "SessionLocal", SessionLocal)

    fake = _FakeRedis()
    monkeypatch.setattr(alerts_mod, "_redis_client", lambda: fake)

    import app.services.email as email_mod

    enviados: list[dict] = []
    monkeypatch.setattr(
        email_mod, "encolar_correo_alerta",
        lambda **kw: enviados.append(kw) or True,
    )

    class _Ajustes:
        ocr_frames_before_fail = 5
        ocr_ping_interval_seconds = 600
        heartbeat_failures_before_alert = 3
        heartbeat_interval_seconds = 60
        redis_url = "redis://stub"

    monkeypatch.setattr("app.services.alerts.get_settings", lambda: _Ajustes())

    db = SessionLocal()
    try:
        parking = Parking(code="P-T177D", name="P-T177D", address="x", city="y")
        db.add(parking)
        db.flush()
        cam = Camera(
            id=CAM_ID,
            parking_id=parking.id,
            code="CAM-T177D",
            name="c",
            rtsp_url="rtsp://demo.invalid/t177d",
        )
        db.add(cam)
        db.commit()
        db.refresh(cam)

        umbral = 5
        ttl = alerts_mod.ttl_contador_fallos(umbral, 600)
        assert ttl == 6000, f"el TTL no es el esperado (era {ttl})"

        alerta = None
        for _ in range(umbral):
            alerta = alerts_mod.record_ocr_failure(cam)
            fake.avanzar(600.0)  # un intervalo real entre fallos

        assert alerta is not None, (
            "5 fallos separados 600 s NO han disparado la alarma: el TTL "
            "no aguanta el intervalo real del ping"
        )
        assert alerta.context["consecutive_fails"] == umbral
        assert len(enviados) == 1
    finally:
        db.close()
        engine.dispose()
