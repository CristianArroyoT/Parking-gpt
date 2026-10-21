"""Escenarios de carga de solidAPP con Locust (ítem T-13 del plan maestro).

POR QUÉ existe este fichero
---------------------------
El producto apunta a **50 streams simultáneos** (MVP: 5 sucursales × 10
cámaras) y a **50+ sucursales en producción**. Hasta ahora no había NINGÚN
escenario de carga en el repo: ninguna regresión de rendimiento (un ``await``
de más en un endpoint, un índice que se cae, un PDF que se genera dos
veces) se detectaba antes de producción. Este fichero fija los cuatro
recorridos críticos del producto y hace que una regresión de latencia
rompa el build (ver ``backend/locust/check_slo.py``).

Los cuatro escenarios (los mismos que el plan maestro pide)
------------------------------------------------------------
1. ``login``            → ``POST /api/v1/auth/login``.
2. ``sse_mapa``         → ``GET /api/v1/parkings/{id}/events`` (mapa en vivo).
3. ``ticket_cerrar``    → ``POST /api/v1/tickets`` + ``POST /api/v1/tickets/{id}/close``.
4. ``preview_mjpeg``    → ``GET /api/v1/parkings/{id}/cameras/{id}/live``.

Decisiones de diseño (y por qué)
--------------------------------
* **El login NO es el hot path**: en producción el usuario se autentica una
  vez y reutiliza el token 15 minutos. Por eso el token se pide UNA vez y
  se comparte entre todos los usuarios virtuales (ver ``_CacheTokens``).
 Además el login tiene rate-limit por IP y por email (10 intentos / 300 s),
  así que un escenario que haga login en bucle mediría su propio 429 en vez
  de la API: hay un **presupuesto de logins** (``SOLIDAPP_PRESUPUESTO_LOGINS``).
* **Los streams son infinitos**: el SSE y el MJPEG nunca terminan por sí
  solos. El cliente lee un número **acotado** de bytes y cierra; si
  esperase al final del stream la carga se quedaría colgada para siempre.
* **El MJPEG sólo admite un stream por cámara** (``live_streams`` devuelve
  409 si ya hay una vista en vivo abierta). Cada usuario virtual recibe una
  cámara distinta (reparto round-robin) para poder medir concurrencia real;
  si no quedan cámaras libres, el 409 se registra aparte y **no** cuenta
  como fallo de rendimiento (es una regla de negocio, no una degradación).
* **Se mide el "primer frame"/"primer evento"**, no sólo el ``time to
  headers``: en un stream la cabecera llega antes de que haya vídeo, así que
  la latencia útil es la del primer frame completo.

Cómo ejecutarlo
---------------
El ``locust`` NO es una dependencia del backend (a propósito: no se añade a
``pyproject.toml``). Dos formas, sin tocar las dependencias del proyecto:

  A) Contenedor (lo que se usa para la ejecución de referencia)::

       docker run --rm --network parking_default \\
         -v D:/Parking/backend:/carga -w /carga locustio/locust \\
         -f /carga/locustfile.py --headless --host http://parking-backend-1:8000 ...

  B) venv en el host::

       python -m venv .venv-locust
       .venv-locust/Scripts/pip install locust
       .venv-locust/Scripts/locust -f backend/locustfile.py --host http://localhost:8000

Ver ``backend/locust/README.md`` para el SLO, la ejecución de referencia y
el encaje en CI.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, events, task
from locust.exception import StopUser

log = logging.getLogger("solidapp.locust")


# ───────────────────────────── Configuración ─────────────────────────────


def _env_lista(nombre: str, defecto: str) -> list[str]:
    """Lee una lista separada por comas del entorno."""
    return [x.strip() for x in os.environ.get(nombre, defecto).split(",") if x.strip()]


def _env_float(nombre: str, defecto: float) -> float:
    """Lee un float del entorno (si no es válido, usa el defecto)."""
    try:
        return float(os.environ.get(nombre, str(defecto)))
    except (TypeError, ValueError):
        return defecto


def _env_int(nombre: str, defecto: int) -> int:
    """Lee un entero del entorno (si no es válido, usa el defecto)."""
    try:
        return int(os.environ.get(nombre, str(defecto)))
    except (TypeError, ValueError):
        return defecto


#: Sucursal sobre la que se carga (Madrid Centro A, la única con cámara
#: real en el entorno de pruebas).
PARKING_ID: int = _env_int("SOLIDAPP_PARKING_ID", 11)

#: Cámaras usadas por el escenario de preview. Cada una necesita su propio
#: ``rtsp_url`` REAL: el backend abre el RTSP al servir el preview, así que
#: una cámara con ``rtsp://demo.invalid`` devolvería el JPEG placeholder.
CAMARA_IDS: list[int] = [int(x) for x in _env_lista("SOLIDAPP_CAMARA_IDS", "81")]

#: Vehículos de la BD sembrada para crear tickets de prueba.
VEHICULO_IDS: list[int] = [int(x) for x in _env_lista("SOLIDAPP_VEHICLE_IDS", "1,11,13")]


def _camaras_ids() -> list[int]:
    """Cámaras del escenario de preview, leídas **en runtime**.

    POR QUÉ no se lee al importar el módulo: al importar, la variable de
    entorno ``SOLIDAPP_CAMERA_IDS`` se quedaba con su valor por defecto
    (la cámara 81) aunque en el proceso sí estuviera bien puesta; en
    cambio, al leerla cuando ya ha arrancado el escenario, sí llega el
    valor. Se comprobó con la ejecución de referencia: con la lectura
    al importar, todos los usuarios virtuales se peleaban por la misma
    cámara (la 81) y la mitad de los previews se descartaban con un 409.

    El valor se cachea en ``CAMARA_IDS`` para no releer el entorno en
    cada iteración.
    """
    global CAMARA_IDS
    ids = [
        int(x)
        for x in os.environ.get("SOLIDAPP_CAMERA_IDS", "81").split(",")
        if x.strip()
    ]
    if ids:
        CAMARA_IDS = ids
    return CAMARA_IDS


#: Ventana de lectura de cada stream (segundos). Acotada a propósito: el
#: stream no termina nunca y hay que cerrar la conexión.
VENTANA_SSE_S: float = _env_float("SOLIDAPP_VENTANA_SSE_S", 2.0)
VENTANA_MJPEG_S: float = _env_float("SOLIDAPP_VENTANA_MJPEG_S", 8.0)

#: Timeout de lectura del socket. El primero tiene que cubrir el arranque
#: del preview (abrir el RTSP + codificar el primer JPEG: ~2-4 s medidos),
#: y a partir de ahí se recorta al tiempo que queda de ventana.
TIMEOUT_LECTURA_S: float = _env_float("SOLIDAPP_TIMEOUT_LECTURA_S", 8.0)

#: Nº máximo de logins REALES por ejecución (ver ``_CacheTokens``).
PRESUPUESTO_LOGINS: int = _env_int("SOLIDAPP_PRESUPUESTO_LOGINS", 5)

#: Credenciales de la BD sembrada (roles distintos para no cargar siempre
#: la misma fila de auditoría).
CREDENCIALES: dict[str, tuple[str, str]] = {
    "gestor": ("gestor.madrid@solidapp.es", "gestor1234"),
    "admin": ("admin@solidapp.es", "admin12345"),
    "operador": ("operador.madrid@solidapp.es", "oper12345"),
}

#: Roles que pueden operar en la sucursal ``PARKING_ID`` (miembros de ella).
ROLES_SUCURSAL: tuple[str, ...] = ("gestor", "operador")


# ───────────────────────────── Utilidades ─────────────────────────────


def _es_timeout(exc: BaseException) -> bool:
    """¿La excepción es un timeout (o sea, "no hay datos todavía")?

    Un timeout de lectura NO es un corte de stream: el SSE sólo emite el
    ``ping`` inicial y luego puede estar 30 s en silencio (heartbeat). Un
    corte real es un EOF o un error de conexión.
    """
    nombre = type(exc).__name__
    if "Timeout" in nombre or "timeout" in str(exc).lower():
        return True
    return isinstance(exc, TimeoutError)


def _contar_frames(buffer: bytes) -> int:
    """Nº de frames JPEG recibidos en un stream multipart.

    Se cuentan por el **boundary** (``--frame``), que es el comienzo de
    cada parte del multipart, y no por el final del JPEG (``FFD9``): el
    frame llega troceado en varios paquetes de red y, con el marcador
    JPEG, un frame a medio recibir cuenta como "no ha llegado ningún
    frame" (falso negativo).
    """
    return buffer.count(b"--frame")


def _contar_eventos_sse(buffer: bytes) -> int:
    """Nº de eventos SSE recibidos (cada evento acaba en ``\\n\\n``)."""
    return buffer.count(b"\n\n")


def _timeout_socket(resp) -> float | None:
    """Timeout de lectura actual del socket de la respuesta (o ``None``)."""
    try:
        return resp.raw._fp.fp.raw._sock.gettimeout()  # noqa: SLF001 — cadena privada
    except Exception:  # noqa: BLE001
        return None


def _fijar_timeout_socket(resp, segundos: float | None) -> None:
    """Ajusta el timeout de lectura del socket que hay bajo la respuesta.

    POR QUÉ hace falta: el preview MJPEG tarda **2-4 s** en entregar su
    primer frame (abrir el RTSP + decodificar + codificar). Con un timeout
    de lectura corto, la primera lectura caduca, y al expirar un timeout de
    socket la conexión queda muerta: la lectura siguiente devuelve EOF y el
    escenario acaba marcando un "corte" que en realidad es del cliente.

    Por eso el timeout de la primera lectura es generoso y, a partir de
    ahí, se recorta al tiempo que queda de la ventana de lectura.

    **Hay que restaurarlo después**: ``requests`` reutiliza las conexiones
    del pool, así que un timeout de socket "prestado" se lo hereda la
    siguiente petición que use esa conexión (y falla con un timeout
    fantasma). Por eso ``_leer_stream`` guarda el valor original y lo
    devuelve al pool antes de cerrar.

    La cadena de objetos (``urllib3 → http.client → socket``) es privada
    de las librerías: si algún día cambia, la función degrada sin romper
    (deja el timeout original) y el escenario sigue funcionando.
    """
    try:
        socket_ = resp.raw._fp.fp.raw._sock  # noqa: SLF001 — cadena privada a propósito
        socket_.settimeout(None if segundos is None else max(0.05, segundos))
    except Exception:  # noqa: BLE001 — si no se puede ajustar, se deja el original
        pass


def _leer_stream(
    resp,
    *,
    ventana_s: float,
    timeout_primer_lectura_s: float,
    contador,
) -> tuple[float, int, int, str | None]:
    """Lee un stream infinito durante una ventana y lo cierra.

    Devuelve ``(ms_primer_elemento, bytes_leidos, elementos, corte)``:

    * ``ms_primer_elemento``: latencia hasta el primer frame/evento (0 si no
      llegó ninguno);
    * ``bytes_leidos``: tamaño de lo recibido (sirve para detectar un
      stream congelado);
    * ``elementos``: frames JPEG o eventos SSE;
    * ``corte``: motivo del corte (``None`` si la ventana terminó limpiamente).

    Un **timeout** no es un corte: el SSE puede estar 30 s en silencio
    (heartbeat) y el MJPEG puede tardar en su primer frame. Sólo cuentan
    como corte el EOF (la conexión se cerró) y los errores de red.
    """
    inicio = time.perf_counter()
    limite = time.monotonic() + ventana_s
    buffer = bytearray()
    elementos = 0
    primer_ms = 0.0
    corte: str | None = None
    primera = True
    timeout_original = _timeout_socket(resp)
    try:
        while True:
            restante = limite - time.monotonic()
            if restante <= 0 and not primera:
                break
            if primera:
                _fijar_timeout_socket(resp, timeout_primer_lectura_s)
            else:
                _fijar_timeout_socket(resp, min(restante, timeout_primer_lectura_s))
            try:
                trozo = resp.raw.read1(65536)  # noqa: SLF001 — lectura parcial
            except Exception as exc:  # noqa: BLE001 — defensiva
                if _es_timeout(exc):
                    if primera:
                        primer_ms = (time.perf_counter() - inicio) * 1000
                        corte = (
                            f"sin datos en {timeout_primer_lectura_s:.1f} s "
                            "(no llegó el primer frame/evento)"
                        )
                        break
                    if time.monotonic() >= limite:
                        # Fin de la ventana: no es un corte.
                        break
                    # Timeout intermedio: la conexión ya está muerta, la
                    # siguiente lectura devolverá EOF y lo marcaremos como corte.
                    continue
                corte = f"{type(exc).__name__}: {exc}"
                break
            if not trozo:
                corte = "EOF: la conexión se cerró con el stream sin terminar"
                break
            buffer.extend(trozo)
            nuevos = contador(bytes(buffer))
            if nuevos > elementos:
                if elementos == 0:
                    primer_ms = (time.perf_counter() - inicio) * 1000
                elementos = nuevos
            primera = False
    finally:
        # Devolver el timeout original ANTES de cerrar: la conexión vuelve
        # al pool de ``requests`` y la siguiente petición la reutiliza.
        _fijar_timeout_socket(resp, timeout_original)
        # Cerrar la conexión es obligatorio: si no, el backend sigue
        # emitiendo frames hacia un cliente que ya no está (y la cámara
        # queda bloqueada para el siguiente cliente: 409).
        resp.close()
    return primer_ms, len(buffer), elementos, corte


# ───────────────────────────── Tokens ─────────────────────────────


class _CacheTokens:
    """Tokens JWT compartidos entre los usuarios virtuales + presupuesto.

    POR QUÉ el presupuesto de logins
    ---------------------------------
    ``POST /api/v1/auth/login`` tiene rate-limit por IP **y** por email
    (10 intentos por ventana de 300 s, ver ``LoginRateLimiter``). Si cada
    usuario virtual hiciera login en cada iteración, la propia carga se
    comería su propio 429 y estaríamos midiendo el rate-limit en vez del
    backend. Dos medidas:

    * el token se pide **una vez** y se reutiliza (es lo que hace el
      cliente real: el login no es el hot path);
    * los logins "de escenario" (la tarea ``login``) consumen un
      **presupuesto** por ejecución. Cuando se agota, la tarea se salta
      (y lo dice en el log) en vez de provocar un 429 artificial.

    El presupuesto es por defecto 5: por debajo del límite de 10 del
    rate-limit, con margen para las rafas.
    """

    def __init__(self, presupuesto: int) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, str] = {}
        self._presupuesto = presupuesto
        self._logins = 0

    @property
    def logins_realizados(self) -> int:
        """Nº de logins HTTP reales lanzamientos en esta ejecución."""
        with self._lock:
            return self._logins

    def token(self, client, rol: str) -> str | None:
        """Token del rol indicado (login sólo si no hay uno cacheado)."""
        with self._lock:
            if rol in self._tokens:
                return self._tokens[rol]
            if self._logins >= self._presupuesto:
                # Sin presupuesto: se reusa el token de otro rol ya
                # autenticado en vez de provocar un 429 propio.
                for token in self._tokens.values():
                    return token
                log.warning("Sin presupuesto de logins ni token cacheado: no se puede autenticar")
                return None
            return self._login(client, rol)

    def login_real(self, client, rol: str) -> str | None:
        """Login explícito (escenario de carga del login). Respeta el presupuesto."""
        with self._lock:
            if self._logins >= self._presupuesto:
                log.warning(
                    "Presupuesto de logins agotado (%s): se omite el login de %s",
                    self._presupuesto,
                    rol,
                )
                return None
            return self._login(client, rol)

    def _login(self, client, rol: str) -> str | None:
        """Lanza el login HTTP. **El llamante debe mantener el lock.**"""
        email, password = CREDENCIALES[rol]
        self._logins += 1
        with client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            name="login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"login {email} -> HTTP {resp.status_code}")
                return None
            resp.success()
            token = (resp.json() or {}).get("access_token")
        if token:
            self._tokens[rol] = token
        return token


CACHE_TOKENS = _CacheTokens(PRESUPUESTO_LOGINS)


# ───────────────────────────── Usuarios virtuales ─────────────────────────────


class _UsuarioSolidApp(HttpUser):
    """Base de los usuarios virtuales: autenticación y cabeceras comunes."""

    abstract = True
    rol: str = "gestor"

    def on_start(self) -> None:
        self.token = CACHE_TOKENS.token(self.client, self.rol)
        if not self.token:
            raise StopUser("no se pudo autenticar contra /api/v1/auth/login")
        self.client.headers["Authorization"] = f"Bearer {self.token}"


class OperadorSucursal(_UsuarioSolidApp):
    """Gestor/operador de la sucursal: mapa en vivo, tickets y login.

    Es el perfil del operador del producto: mira el mapa en vivo (SSE),
    consulta las listas y cierra tickets.
    """

    rol = "gestor"
    wait_time = between(1, 3)
    #: Peso del perfil frente al de los visualizadores: con 6 usuarios
    #: virtuales son 5 operadores y 1 visualizador (83 % API / 17 % streams).
    weight = 5

    @task(4)
    def lectura_plazas(self) -> None:
        """GET de las plazas de la sucursal (lo que pinta el mapa)."""
        with self.client.get(
            f"/api/v1/parkings/{PARKING_ID}/spaces",
            name="lectura_plazas",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"lectura_plazas -> HTTP {resp.status_code}")

    @task(3)
    def lectura_tickets(self) -> None:
        """GET de los tickets de la sucursal."""
        with self.client.get(
            "/api/v1/tickets",
            params={"parking_id": PARKING_ID},
            name="lectura_tickets",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"lectura_tickets -> HTTP {resp.status_code}")

    @task(2)
    def lectura_camaras(self) -> None:
        """GET de las cámaras de la sucursal."""
        with self.client.get(
            f"/api/v1/parkings/{PARKING_ID}/cameras",
            name="lectura_camaras",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"lectura_camaras -> HTTP {resp.status_code}")

    @task(3)
    def sse_mapa(self) -> None:
        """Escenario del mapa en vivo: stream SSE de eventos de la sucursal.

        El stream es infinito: se leen unos pocos eventos y se cierra.

        OJO con la autenticación: el SSE sólo acepta el token por cabecera
        ``Authorization``. Su dep de contexto de sucursal (``parking_context``)
        es header-only, así que el ``?token=`` que anuncia el docstring del
        endpoint devuelve 401 (a diferencia del preview MJPEG, que sí lo
        acepta porque usa un dep propio). El token va en la cabecera que
        fija ``on_start``.
        """
        url = f"/api/v1/parkings/{PARKING_ID}/events"
        inicio = time.perf_counter()
        with self.client.get(
            url,
            name="sse_mapa",
            stream=True,
            catch_response=True,
            timeout=(5, TIMEOUT_LECTURA_S),
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"sse_mapa -> HTTP {resp.status_code}")
                return
            primer_evento_ms, bytes_leidos, eventos, corte = _leer_stream(
                resp,
                ventana_s=VENTANA_SSE_S,
                timeout_primer_lectura_s=TIMEOUT_LECTURA_S,
                contador=_contar_eventos_sse,
            )
            if corte:
                resp.failure(f"sse_mapa cortado: {corte}")
            elif primer_evento_ms <= 0:
                resp.failure("sse_mapa: no llegó ningún evento en la ventana")
            self._registrar(
                nombre="sse_mapa_primer_evento",
                milisegundos=primer_evento_ms,
                bytes_leidos=bytes_leidos,
                corte=corte,
                contexto={"parking": PARKING_ID, "eventos": eventos},
            )

    @task(2)
    def cierre_ticket(self) -> None:
        """Escenario de cierre de ticket: alta + cierre (incluye el PDF)."""
        entrada = datetime.now(timezone.utc) - timedelta(hours=2)
        payload = {
            "parking_id": PARKING_ID,
            "vehicle_id": random.choice(VEHICULO_IDS),
            "entry_at": entrada.isoformat(),
        }
        with self.client.post(
            "/api/v1/tickets",
            json=payload,
            name="ticket_crear",
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"ticket_crear -> HTTP {resp.status_code}")
                return
            ticket_id = (resp.json() or {}).get("id")
        if not ticket_id:
            resp.failure("ticket_crear: la respuesta no trae id")
            return
        with self.client.post(
            f"/api/v1/tickets/{ticket_id}/close",
            json={"payment_method": "card"},
            name="ticket_cerrar",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"ticket_cerrar {ticket_id} -> HTTP {resp.status_code}")

    @task(1)
    def login(self) -> None:
        """Escenario de login: autentica de verdad contra ``/auth/login``."""
        rol = random.choice(sorted(CREDENCIALES))
        CACHE_TOKENS.login_real(self.client, rol)

    # ── helpers de lectura de streams ──

    def _registrar(
        self,
        *,
        nombre: str,
        milisegundos: float,
        bytes_leidos: int,
        corte: str | None,
        contexto: dict,
    ) -> None:
        """Publica una métrica propia en las estadísticas de Locust.

        Locust mide por defecto el tiempo hasta la CABECERA de la respuesta;
        en un stream eso no dice nada del vídeo. Estas entradas miden el
        primer frame / primer evento, que es la latencia que ve el usuario.
        """
        self.environment.events.request.fire(
            request_type="GET",
            name=nombre,
            response_time=milisegundos,
            response_length=bytes_leidos,
            response=None,
            context=contexto,
            exception=RuntimeError(corte) if corte else None,
            start_time=time.time(),
        )


class VisualizadorCamaras(_UsuarioSolidApp):
    """Operador con el modal de preview en vivo abierto (MJPEG).

    Es el perfil más pesado del producto: cada usuario mantiene un stream
    MJPEG abierto contra el backend, que a su vez decodifica el RTSP y
    codifica JPEG. El objetivo de carga del producto son 50 streams así.
    """

    rol = "gestor"
    #: El operador deja pasar un rato entre previews: el backend tarda unos
    #: segundos en liberar la cámara cuando el cliente cierra (el generador
    #: puede estar esperando al FFmpeg y la sesión de ``live_streams`` sólo
    #: caduca a los 8 s sin frames), así que reabrir enseguida recibe un
    #: 409. Con esta espera se mide el preview de verdad y no el 409.
    wait_time = between(12, 16)
    #: Un visualizador por cámara: el backend sólo admite un stream vivo
    #: por cámara (409 si ya hay otro abierto). El peso es bajo a
    #: propósito: cada stream abierto **concentra una conexión de
    #: PostgreSQL** mientras dura (y si el cliente cierra antes de
    #: tiempo, la conexión se queda filtrada: ver el informe de
    #: referencia), así que el número de streams concurrentes es el
    #: límite real del entorno, no el número de usuarios.
    weight = 1

    def on_start(self) -> None:
        super().on_start()
        with _CONTADOR_USUARIOS["lock"]:
            indice = _CONTADOR_USUARIOS["valor"]
            _CONTADOR_USUARIOS["valor"] = indice + 1
        self.indice = indice
        # Cada visualizador apunta a una cámara distinta: el backend sólo
        # permite UN stream vivo por cámara (409 si ya hay otro).
        camaras = _camaras_ids()
        self.camara_id = camaras[indice % len(camaras)]

    @task(5)
    def preview_mjpeg(self) -> None:
        """Escenario de preview en vivo: stream MJPEG acotado."""
        url = (
            f"/api/v1/parkings/{PARKING_ID}/cameras/{self.camara_id}/live"
            f"?token={self.token}"
        )
        inicio = time.perf_counter()
        with self.client.get(
            url,
            name="preview_mjpeg",
            stream=True,
            catch_response=True,
            timeout=(5, TIMEOUT_LECTURA_S),
        ) as resp:
            if resp.status_code == 409:
                # Ya hay una vista en vivo abierta para esta cámara. Es una
                # regla de negocio (``live_streams``), no una degradación:
                # se registra aparte y no cuenta como fallo. El visualizador
                # prueba con otra cámara, como haría el operador.
                resp.request_meta["name"] = "preview_mjpeg_omitido_409"
                resp.success()
                self._rotar_camara()
                return
            if resp.status_code != 200:
                resp.failure(f"preview_mjpeg cam {self.camara_id} -> HTTP {resp.status_code}")
                return
            primer_frame_ms, bytes_leidos, frames, corte = _leer_stream(
                resp,
                ventana_s=VENTANA_MJPEG_S,
                timeout_primer_lectura_s=TIMEOUT_LECTURA_S,
                contador=_contar_frames,
            )
            if corte:
                resp.failure(f"preview_mjpeg cortado: {corte}")
            elif frames <= 0:
                resp.failure(f"preview_mjpeg cam {self.camara_id}: no llegó ningún frame")
            self._registrar(
                nombre="preview_mjpeg_primer_frame",
                milisegundos=primer_frame_ms,
                bytes_leidos=bytes_leidos,
                corte=corte,
                contexto={"camara": self.camara_id, "frames": frames},
            )

    def _rotar_camara(self) -> None:
        """Tras un 409, el visualizador pasa a la siguiente cámara.

        POR QUÉ: el backend libera la sesión de una cámara cuando el
        cliente cierra, pero el generador puede tardar (está esperando al
        FFmpeg) y la sesión de ``live_streams`` sólo caduca a los 8 s sin
        frames → el siguiente intento recibe un 409 aunque la cámara esté
        "libre" para el usuario. Rotar evita que el 409 contamine la
        medición del preview.

        El salto es del tamaño del grupo de visualizadores (``weight``) para
        no caer en la cámara que está usando otro visualizador.
        """
        try:
            posicion = _camaras_ids().index(self.camara_id)
        except ValueError:
            posicion = 0
        salto = max(1, type(self).weight)
        camaras = _camaras_ids()
        self.camara_id = camaras[(posicion + salto) % len(camaras)]

    def _registrar(
        self,
        *,
        nombre: str,
        milisegundos: float,
        bytes_leidos: int,
        corte: str | None,
        contexto: dict,
    ) -> None:
        """Publica una métrica propia en las estadísticas de Locust."""
        self.environment.events.request.fire(
            request_type="GET",
            name=nombre,
            response_time=milisegundos,
            response_length=bytes_leidos,
            response=None,
            context=contexto,
            exception=RuntimeError(corte) if corte else None,
            start_time=time.time(),
        )


#: Reparto round-robin de cámaras entre los visualizadores.
_CONTADOR_USUARIOS = {"valor": 0, "lock": threading.Lock()}

#: Instante de arranque de la ejecución (para el contexto del informe).
_INICIO_EJECUCION: dict[str, object] = {}

def _resumen_fallos(environment) -> dict[str, dict[str, object]]:
    """Resumen de los fallos de la ejecución (por métrica).

    El informe JSON de Locust no guarda el motivo de los fallos, y sin él
    un "3 fallos" no dice si fue un 429 del rate-limit, un 409 de
    ``live_streams`` o un corte de stream.
    """
    resumen: dict[str, dict[str, object]] = {}
    for error in getattr(environment.stats, "errors", {}).values():
        metodo = getattr(error, "method", "") or ""
        nombre = getattr(error, "name", "") or ""
        resumen[f"{metodo} {nombre}".strip()] = {
            "ocurrencias": getattr(error, "occurrences", 0),
            "error": str(getattr(error, "error", ""))[:300],
        }
    return resumen


# ───────────────────────────── Ciclo de vida de la ejecución ─────────────────────────────


@events.init.add_listener
def _configurar_entorno(environment, **_kwargs) -> None:
    """No resetear las estadísticas al terminar el spawn.

    Por defecto Locust borra las estadísticas cuando acaba la rampa de
    usuarios, y eso se llevaría por delante los logins que hacen los
    usuarios en ``on_start``: el SLO del login se quedaría sin muestras.
    """
    environment.reset_stats = False
    _INICIO_EJECUCION["t0"] = time.time()


@events.test_start.add_listener
def _guardar_usuarios(environment, **_kwargs) -> None:
    """Guarda el nº de usuarios de la ejecución (al terminar ya valen 0)."""
    runner = environment.runner
    _INICIO_EJECUCION["usuarios"] = getattr(runner, "target_user_count", None) or (
        runner.user_count if runner else None
    )


@events.test_stop.add_listener
def _guardar_contexto(environment, **_kwargs) -> None:
    """Guarda el contexto de la ejecución junto al informe (si se pide).

    El informe JSON de Locust no dice con cuántos usuarios, contra qué host
    ni durante cuánto tiempo se corrió. Sin eso, un número de p95 suelto
    en el repo no es reproducible ni comparable.
    """
    ruta = os.environ.get("SOLIDAPP_INFORME_CONTEXTO")
    if not ruta:
        return
    inicio = _INICIO_EJECUCION.get("t0")
    contexto = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "host": environment.host,
        "usuarios": _INICIO_EJECUCION.get("usuarios"),
        "duracion_s": round(time.time() - inicio, 1) if inicio else None,
        "parking_id": PARKING_ID,
        "camaras": _camaras_ids(),
        "ventana_sse_s": VENTANA_SSE_S,
        "ventana_mjpeg_s": VENTANA_MJPEG_S,
        "presupuesto_logins": PRESUPUESTO_LOGINS,
        "logins_realizados": CACHE_TOKENS.logins_realizados,
        "fallos": _resumen_fallos(environment),
    }
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(contexto, fh, indent=2, ensure_ascii=False)
    except OSError as exc:  # pragma: no cover — defensiva
        log.warning("No se pudo escribir el contexto de la ejecución: %s", exc)
