"""Configuración central via Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lee variables del entorno y valida tipos."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="postgresql+psycopg://parking:parking@db:5432/parking", alias="DATABASE_URL")
    # NO USADO (2026-10-22): la aplicación es **síncrona** (no hay
    # ``create_async_engine`` en ninguna parte). Queda declarado para
    # cuando haya motor asíncrono; ponerlo no cambia nada.
    # La puerta tools/verificar_ajustes_muertos.py lo vigila.
    async_database_url: str = Field(default="postgresql+asyncpg://parking:parking@db:5432/parking", alias="ASYNC_DATABASE_URL")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_ttl_minutes: int = Field(default=15, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=7, alias="REFRESH_TOKEN_TTL_DAYS")

    # NO USADO (2026-10-22): el ``CMD`` del Dockerfile fija
    # ``--host 0.0.0.0 --port 8000`` en duro, y el healthcheck usa el
    # 8000. Si se cambia el puerto hay que cambiarlo en los dos sitios
    # (y aquí no sirve de nada).
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:3000", alias="CORS_ORIGINS")
    # URL **publica** del frontend: la que ve el cliente final. Se usa para
    # los enlaces de los correos (por ejemplo, el de recuperar contrasena).
    #
    # OJO (T-61): antes esta URL estaba hardcodeada en el servicio de
    # correo como "http://localhost:5173/recuperar-contrasena", o sea que
    # en produccion el correo de "restablece tu contrasena" llevaba un
    # enlace a localhost: el cliente lo pulsaba y no llegaba a nada. El
    # flujo de recuperacion de contrasena estaba roto de punta a punta.
    frontend_base_url: str = Field(
        default="http://localhost:5173", alias="FRONTEND_BASE_URL"
    )

    # NO USADO (2026-10-22), los tres: el motor y el idioma los elige el
    # **servicio OCR** (docker/ocr), con sus propias variables
    # ``OCR_ENGINE`` y ``OCR_LANG``. OJO con ``ocr_lang``: su valor de
    # aquí ("es") NO es el que se usa; el servicio va con "en" (modelo
    # de matrículas EU).
    #
    # Y ``ocr_confidence_threshold`` tampoco: el filtro de confianza
    # real es el ``confidence_threshold`` de **cada geocerca** (lo
    # calibra el operador al pintar la plaza). Poner este valor no
    # descarta ninguna lectura.
    ocr_engine: Literal["paddleocr", "tesseract"] = Field(default="paddleocr", alias="OCR_ENGINE")
    ocr_lang: str = Field(default="es", alias="OCR_LANG")
    ocr_confidence_threshold: float = Field(default=0.85, alias="OCR_CONFIDENCE_THRESHOLD")
    ocr_frames_before_fail: int = Field(default=5, alias="OCR_FRAMES_BEFORE_FAIL")
    # T-167 (2026-10-24): cada cuántos segundos se espera que llegue un
    # fallo de OCR (o una lectura) por cámara. El TTL del contador de
    # fallos consecutivos se calcula con este intervalo
    # (``umbral × intervalo × margen``, en ``app/services/alerts.py``):
    # antes el TTL eran 600 s fijos y la ventana iba desde el primer
    # fallo, así que si los fallos llegaban más espaciados que
    # ``600/5 = 120 s`` el contador caducaba antes de poder llegar al
    # umbral y **la alerta nunca saltaba**.
    #
    # T-177 (2026-10-24): el ping **ya se despacha** (cada 10 min por
    # cámara, decisión de producto), así que este valor es el ritmo
    # **real** y tiene que ser **600 s** (10 min), no 60 s: con 60 s de
    # TTL la ventana del contador (5 × 60 × 2 = 600 s) **caducaría justo
    # antes** de que llegara el siguiente fallo (que llega a los 600 s) y
    # la alarma ``OCR_FAILED`` volvería a no saltar nunca.
    #
    # OJO: este valor tiene que **coincidir** con
    # ``ping_camera_interval_seconds`` (600 s). Si se cambia uno, hay que
    # cambiar el otro: lo vigila un test (``test_ping_camera_despacho.py``).
    ocr_ping_interval_seconds: int = Field(
        default=600, alias="OCR_PING_INTERVAL_SECONDS"
    )
    # T-177 (2026-10-24): intervalo **real** entre pings a la misma
    # cámara. Es lo que lee el ``beat_schedule`` (``celery_app.py``) para
    # saber cada cuánto despachar ``solidapp.ping_cameras``, y el TTL del
    # lock por cámara (para que los pings no se acumulen) y del contador
    # de fallos de OCR.
    #
    # 600 s = 10 min (decisión de producto del 2026-10-24).
    ping_camera_interval_seconds: int = Field(
        default=600, alias="PING_CAMERA_INTERVAL_SECONDS"
    )
    # T-167 (2026-10-24): ritmo real del ``probe_heartbeats`` (el beat lo
    # despacha cada 60 s, en ``app/workers/celery_app.py``). Mismo uso:
    # el TTL del contador de fallos consecutivos de ``CAMERA_OFFLINE``.
    heartbeat_interval_seconds: int = Field(
        default=60, alias="HEARTBEAT_INTERVAL_SECONDS"
    )

    # Heartbeat real (sprint CAMERA_OFFLINE v2): probe ligero cada 60s.
    # Si falla N heartbeats consecutivos → alerta CAMERA_OFFLINE con
    # context.kind="heartbeat". Distinto de ocr_frames_before_fail
    # (semánticamente: frames vs heartbeats).
    heartbeat_failures_before_alert: int = Field(
        default=3, alias="HEARTBEAT_FAILURES_BEFORE_ALERT"
    )
    # URLs que el heartbeat skipea (seed local, entornos de prueba).
    #
    # OJO (T-75, 2026-10-22): esto es un **string**, no una ``list[str]``,
    # a propósito. ``pydantic-settings`` parsea los campos de tipo lista
    # ANTES de los validadores y para eso solo entiende JSON: un valor de
    # entorno como ``"rtsp://demo.invalid,rtsp://test.local"`` (justo el
    # que documenta este comentario) hacia fallar el arranque con
    # ``SettingsError``. La lista se saca en
    # ``heartbeat_skip_url_prefixes_list`` (mismo patrón que
    # ``cors_origins``).
    heartbeat_skip_url_prefixes: str = Field(
        default="rtsp://demo.invalid", alias="HEARTBEAT_SKIP_URL_PREFIXES"
    )
    # Sprint Camera Health: ventana máxima (segundos) entre probe y "now"
    # para que el estado sea "healthy". Si ``now - last_heartbeat_at``
    # supera este umbral, el endpoint marca "degraded" (cámara viva pero
    # sin actualización reciente). Recomendado: ≥ 2× el schedule del
    # beat (60 s) → 120 s absorbe un probe lento sin falsos degraded.
    camera_health_stale_threshold_seconds: int = Field(
        default=120, alias="CAMERA_HEALTH_STALE_THRESHOLD_SECONDS"
    )
    # Sprint Live-Preview T-07 (2026-10-21): fps objetivo del preview en vivo.
    #
    # Decisión D1 (el código anunciaba "5 fps" pero corría a 35 fps reales):
    # el preview NO necesita ir al ritmo de la cámara. A 5 fps se ahorra
    # ~85 % de CPU y de ancho de banda del backend, y la latencia útil
    # que ve el operador sigue siendo <400 ms (el frame llega al cliente
    # en cuanto se emite).
    #
    # Configurable por entorno para poder volver al "flujo libre" del
    # sprint Latencia-Mínima (2026-07-07) sin tocar código: 0 (o un
    # valor no positivo) = SIN limitador, el preview va tan rápido como
    # la cámara + la red lo permitan.
    live_preview_fps: float = Field(default=5.0, alias="LIVE_PREVIEW_FPS")

    # URL del servicio OCR separado (PaddleOCR en su propio contenedor).
    # Si el servicio no responde, el cliente devuelve [] y el caller
    # decide qué hacer. NO usar en tests salvo que se inyecte MockTransport.
    ocr_service_url: str = Field(
        default="http://localhost:8800", alias="OCR_SERVICE_URL"
    )
    ocr_service_timeout: float = Field(
        default=4.0, alias="OCR_SERVICE_TIMEOUT"
    )

    # Sprint Vehicle-Detect (2026-07-07): detector cenital de vehículos
    # (Ultralytics YOLO) en su propio contenedor. Timeout generoso
    # porque YOLO en CPU puede tardar 300-500 ms por imagen 960x540.
    vehicle_detector_url: str = Field(
        default="http://localhost:8801", alias="VEHICLE_DETECTOR_URL"
    )
    vehicle_detector_timeout: float = Field(
        default=8.0, alias="VEHICLE_DETECTOR_TIMEOUT"
    )

    # Sprint Fase 3A (2026-07-01): observabilidad y auditoría.
    # ``log_format=plain`` por defecto para que ``docker compose logs backend``
    # siga legible en dev. ``json`` activa ``python-json-logger`` en
    # ``app/core/logging.py`` (escribirá a stdout + archivo rotado en
    # ``/var/log/solidapp/backend.log`` que Promtail scrapea → Loki).
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: Literal["json", "plain"] = Field(default="plain", alias="LOG_FORMAT")
    # NO USADO por la aplicación (2026-10-22): los logs salen por stdout
    # y los reenvía Promtail, que tiene su URL en
    # ``infra/promtail/promtail-config.yaml``. Ponerlo aquí no cambia
    # nada.
    loki_url: str = Field(default="http://loki:3100", alias="LOKI_URL")
    # Retención del histórico de audit_logs (1 año por defecto, alineado
    # con la política del producto documentada en memoria). Usada por la
    # task ``solidapp.purge_audit_logs`` (sprint Fase 3C 2026-07-01)
    # que borra filas con ``created_at < now - retention_days``.
    audit_log_retention_days: int = Field(default=365, alias="AUDIT_LOG_RETENTION_DAYS")
    # T-164 (2026-10-24): minutos sin llegadas de una camara para dar la
    # alarma de «ha dejado de empujar lecturas». El push externo es el
    # camino real de datos y no tenia ninguna vigilancia.
    camera_push_silence_minutes: int = Field(
        default=30, alias="CAMERA_PUSH_SILENCE_MINUTES"
    )

    # Sprint Fase 3C (2026-07-01): rate-limit en ``POST /auth/login``.
    # El ``LoginRateLimiter`` usa 2 buckets Redis (IP + email). Si
    # CUALQUIER bucket supera ``max_attempts`` en ``window_seconds`` →
    # 429 Too Many Requests y audit_logs con ``action=rate_limited_login``.
    login_rate_limit_window_seconds: int = Field(
        default=300, alias="LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    )
    login_rate_limit_max_attempts: int = Field(
        default=10, alias="LOGIN_RATE_LIMIT_MAX_ATTEMPTS",
    )
    # CIDR de proxies en los que se confía para parsear ``X-Forwarded-For``.
    # Por defecto: rangos Docker (172.16.0.0/12, 10.0.0.0/8). En producción
    # con Nginx/Cloudflare el admin debe añadir las IPs del proxy
    # explícitamente vía env (TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8,...").
    # Si el ``client.host`` NO está en esta lista, el helper ignora XFF
    # (defensa contra spoofing).
    #
    # OJO (T-75, 2026-10-22): un **string**, no una ``list[str]``. Con la
    # lista, un valor de entorno con comas (el formato que documenta este
    # comentario) hacia fallar el arranque del backend con
    # ``SettingsError``: el compose que se copia a las sucursales lleva
    # ese valor y **el despliegue no arrancaba**. La lista se saca en
    # ``trusted_proxies_list``.
    trusted_proxies: str = Field(
        default="172.16.0.0/12,10.0.0.0/8", alias="TRUSTED_PROXIES"
    )

    # Sprint Fase 3D (2026-07-01): token blacklist (logout invalida JWT).
    # ``jwt_blacklist_key_prefix`` + ``jti`` (UUID v4 hex añadido al token
    # en ``create_access_token``/``create_refresh_token``). El TTL del
    # key en Redis se calcula como ``(exp - now) + grace_seconds``, así
    # se auto-limpia cuando el JWT ya estaba expirado de forma natural.
    # Fail-CLOSED: si Redis cae, ``is_blocked`` re-lanza ``RedisError`` y
    # el ``AuditMiddleware`` aborta con 401 (no deja pasar requests no
    # validados contra blacklist).
    jwt_blacklist_key_prefix: str = Field(
        default="jwt:blacklist:", alias="JWT_BLACKLIST_KEY_PREFIX",
    )
    jwt_blacklist_ttl_grace_seconds: int = Field(
        default=60, alias="JWT_BLACKLIST_TTL_GRACE_SECONDS",
    )

    # Sprint Fase 3D (2026-07-01): rate-limit genérico para CRUDs
    # autenticados (``POST /users``, ``PATCH /users/{id}``,
    # ``POST /vehicles``, ``PATCH /vehicles/{id}``). Más permisivo que
    # login (30 vs 10) porque el CRUD legítimo hace ráfagas razonables
    # (carga inicial de datos, scripts de seed). Mismo patrón fail-OPEN
    # que ``LoginRateLimiter``: si Redis cae, deja pasar.
    endpoint_rate_limit_max_attempts: int = Field(
        default=30, alias="ENDPOINT_RATE_LIMIT_MAX_ATTEMPTS",
    )
    endpoint_rate_limit_window_seconds: int = Field(
        default=60, alias="ENDPOINT_RATE_LIMIT_WINDOW_SECONDS",
    )

    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="solidAPP <no-reply@solidapp.es>", alias="SMTP_FROM")

    # T-23 (plan maestro 2026-10-21): **el reconocimiento facial está FUERA
    # del MVP**. Se deja la estructura de datos (``face_templates``) y los
    # endpoints de alta/baja preparados, pero DESHABILITADOS: con el flag a
    # ``False`` (valor por defecto) el router de ``/face-templates``
    # responde ``404`` y el login sigue siendo usuario + contraseña, sin
    # tocar esta tabla en ningún momento.
    #
    # El flag existe para que la activación sea una decisión explícita
    # (y auditable) cuando se implemente el reconocimiento real, no un
    # simple borrado de código.
    face_templates_enabled: bool = Field(
        default=False, alias="FACE_TEMPLATES_ENABLED",
    )

    # ── T-21 (plan maestro 2026-10-21): adjuntos/fotos de incidentes ────
    # El binario de las fotos NUNCA va a la base de datos: vive en un
    # volumen local y en la BD sólo queda la metadata (nombre, hash,
    # mime, tamaño y ruta). Ver ``app/services/incident_attachments.py``.
    #
    # ``incident_attachments_dir``: raíz del volumen dentro del
    # contenedor. Por defecto ``/var/lib/solidapp/incident-attachments``,
    # que es donde monta el volumen Docker ``incident_attachments``.
    incident_attachments_dir: str = Field(
        default="/var/lib/solidapp/incident-attachments",
        alias="INCIDENT_ATTACHMENTS_DIR",
    )
    # Tamaño máximo por fichero (bytes). 10 MB: una foto de móvil taken
    # con la cámara a máxima calidad pesa 3-5 MB, así que 10 MB deja
    # margen sin permitir que una subida abuse del disco (3 ficheros ×
    # 10 MB = 30 MB como máximo por incidente).
    incident_attachment_max_bytes: int = Field(
        default=10 * 1024 * 1024, alias="INCIDENT_ATTACHMENT_MAX_BYTES",
    )
    # Número máximo de ficheros por incidente (el wireframe del operador
    # pide "adjuntos (hasta 3 fotos)").
    incident_attachment_max_files: int = Field(
        default=3, alias="INCIDENT_ATTACHMENT_MAX_FILES",
    )
    # Tipos MIME admitidos, separados por comas. Se verifican por los
    # BYTES del fichero, no por la extensión ni por el Content-Type
    # que manda el cliente. **SVG no se acepta**: es XML ejecutable.
    incident_attachment_allowed_mime_types: str = Field(
        default="image/jpeg,image/png,image/webp",
        alias="INCIDENT_ATTACHMENT_ALLOWED_MIME_TYPES",
    )
    # Retención por defecto de las fotos (días) — LOPDGDD: minimización.
    # 90 días cubre el plazo de gestión de una reclamación sin mantener
    # fotos de personas durante años.
    incident_attachment_retention_days: int = Field(
        default=90, alias="INCIDENT_ATTACHMENT_RETENTION_DAYS",
    )

    environment: Literal["development", "staging", "production", "test"] = Field(default="development", alias="ENVIRONMENT")

    @model_validator(mode="after")
    def _exigir_algoritmo_hs256(self) -> "Settings":
        """El backend firma con HS256 (clave compartida) y con nada mas.

        POR QUE (2026-10-23, T-89): ``python-jose`` 3.5.0 tiene un aviso
        abierto **sin version arreglada** (GHSA-3qf3-8w2g-rqmx /
        CVE-2026-85394): al inicializar una clave HMAC acepta una clave
        publica DER sin armadura PEM, y si no se restringen los
        algoritmos, un atacante con la clave publica del servicio puede
        falsificar un token HS256.

        Aqui se cierra por configuracion, no por suerte:

        - el despliegue es de **clave compartida** (HS256): no hay clave
          publica que un atacante pueda usar;
        - ``decode_token`` restringe los algoritmos de forma explicita;
        - y ahora ``JWT_ALGORITHM`` **solo** admite HS256: si alguien
          pone RS256 (que necesitaria una clave asimetrica), la
          aplicacion no levanta y lo dice, en vez de firmar con un
          algoritmo que nadie ha auditado.

        La prueba que acompaña a esta regla esta en
        ``backend/tests/test_jwt_algoritmos.py`` y la excepcion, con su
        justificacion, en ``tools/dependencias_aceptadas.json``.
        """
        if self.jwt_algorithm.strip().upper() != "HS256":
            raise ValueError(
                "JWT_ALGORITHM debe ser HS256: el backend firma con clave "
                f"compartida y no admite {self.jwt_algorithm!r}."
            )
        return self

    @model_validator(mode="after")
    def _exigir_secreto_real_fuera_de_desarrollo(self) -> "Settings":
        """En staging/producción, el secreto JWT tiene que ser real.

        POR QUÉ (2026-10-21): el compose trae ``JWT_SECRET:
        ${JWT_SECRET:-change-me-in-production}``. Ese valor por defecto
        está escrito en un repositorio **público**: si alguien despliega
        en una sucursal sin poner la variable de entorno, la API firmaría
        los tokens con un secreto que cualquiera puede leer, es decir,
        podría fabricar el token de administrador.

        Mejor que arrancar y fallar por el camino (un 401 en mitad de una
        sesión de un técnico es unundiagnóstico horrible): que la
        aplicación no levante y lo diga claro en el log.

        En ``development`` y ``test`` no se comprueba: el equipo de QA
        usa el valor por defecto a propósito.
        """
        if self.environment not in ("production", "staging"):
            return self
        # T-81: la comparación es por PREFIJO, no exacta. Con la exacta
        # se colaba el valor que propone el propio .env.example
        # ("change-me-in-production-32-bytes-min"): quien copiaba el
        # .env.example a .env (que es lo que dice el README) arrancaba en
        # produccion con un secreto PUBLICO y podia firmar tokens de
        # administrador.
        secreto = self.jwt_secret.strip().lower()
        if (
            not secreto
            or secreto.startswith(_MARCADORES_SECRETO_POR_DEFECTO)
            or secreto in _SECRETOS_POR_DEFECTO_EXACTOS
        ):
            raise ValueError(
                "JWT_SECRET debe definirse con un valor real cuando "
                f"ENVIRONMENT={self.environment}: el valor por defecto "
                "'change-me-in-production' está en el repositorio "
                "público y permitiría firmar tokens de administrador. "
                "Exporta JWT_SECRET antes de arrancar."
            )
        return self

    @model_validator(mode="after")
    def _exigir_url_publica_real_fuera_de_desarrollo(self) -> "Settings":
        """En staging/produccion, la URL del frontend tiene que ser real.

        POR QUÉ (2026-10-22): es la URL que se pone en los correos (por
        ejemplo, el de recuperar contrasena). Con el valor por defecto
        (localhost:5173) el correo lleva un enlace que no lleva a ningun
        sitio, y el cliente no puede recuperar su contrasena.

        Y tiene que ser HTTPS: la PWA (decision D4) solo se registra en
        contexto seguro, y el README ya lo dice. Un enlace http:// en un
        correo es, ademas, un aviso del cliente de correo.

        Mismo patron que el secreto JWT: que la aplicacion no levante y lo
        diga claro en el log, en vez de fallar mas tarde con un enlace
        roto que nadie sabe explicar.
        """
        if self.environment not in ("production", "staging"):
            return self
        url = self.frontend_base_url.strip()
        if url in ("", "http://localhost:5173"):
            raise ValueError(
                "FRONTEND_BASE_URL debe definirse con la URL real del "
                f"frontend cuando ENVIRONMENT={self.environment}: con el "
                "valor por defecto los correos (por ejemplo, el de "
                "recuperar contrasena) llevan un enlace a localhost. "
                "Exporta FRONTEND_BASE_URL antes de arrancar."
            )
        if not url.startswith("https://"):
            raise ValueError(
                "FRONTEND_BASE_URL tiene que empezar por https:// cuando "
                f"ENVIRONMENT={self.environment}: la PWA solo se registra en "
                f"contexto seguro y '{url}' no lo es."
            )
        return self

    @property
    def trusted_proxies_list(self) -> list[str]:
        """Los CIDR de los proxies de confianza, ya separados (T-75)."""
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def heartbeat_skip_url_prefixes_list(self) -> list[str]:
        """Los prefijos de URL que el heartbeat skipea (T-75)."""
        return [
            p.strip() for p in self.heartbeat_skip_url_prefixes.split(",") if p.strip()
        ]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def incident_attachment_mime_types_list(self) -> list[str]:
        """Tipos MIME admitidos, ya normalizados (minúsculas, sin espacios)."""
        return [
            m.strip().lower()
            for m in self.incident_attachment_allowed_mime_types.split(",")
            if m.strip()
        ]


#: Secretos que se rechazan tal cual en staging/produccion.
_SECRETOS_POR_DEFECTO_EXACTOS = ("secret", "")
#: Marcadores que hacen rechazar cualquier secreto que **empiece** por
#: ellos (T-81): asi se cubre "change-me-in-production-32-bytes-min", que
#: es el valor que propone el .env.example.
_MARCADORES_SECRETO_POR_DEFECTO = ("change-me", "changeme")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton para no releer el entorno en cada llamada."""
    return Settings()