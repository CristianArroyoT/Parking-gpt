"""Configuración central via Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    async_database_url: str = Field(default="postgresql+asyncpg://parking:parking@db:5432/parking", alias="ASYNC_DATABASE_URL")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_ttl_minutes: int = Field(default=15, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=7, alias="REFRESH_TOKEN_TTL_DAYS")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:3000", alias="CORS_ORIGINS")

    ocr_engine: Literal["paddleocr", "tesseract"] = Field(default="paddleocr", alias="OCR_ENGINE")
    ocr_lang: str = Field(default="es", alias="OCR_LANG")
    ocr_confidence_threshold: float = Field(default=0.85, alias="OCR_CONFIDENCE_THRESHOLD")
    ocr_frames_before_fail: int = Field(default=5, alias="OCR_FRAMES_BEFORE_FAIL")

    # Heartbeat real (sprint CAMERA_OFFLINE v2): probe ligero cada 60s.
    # Si falla N heartbeats consecutivos → alerta CAMERA_OFFLINE con
    # context.kind="heartbeat". Distinto de ocr_frames_before_fail
    # (semánticamente: frames vs heartbeats).
    heartbeat_failures_before_alert: int = Field(
        default=3, alias="HEARTBEAT_FAILURES_BEFORE_ALERT"
    )
    # URLs que el heartbeat skipea (seed local, entornos de prueba).
    # Lista separada por comas en env, e.g. HEARTBEAT_SKIP_URL_PREFIXES="rtsp://demo.invalid,rtsp://test.local".
    heartbeat_skip_url_prefixes: list[str] = Field(
        default=["rtsp://demo.invalid"], alias="HEARTBEAT_SKIP_URL_PREFIXES"
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
    loki_url: str = Field(default="http://loki:3100", alias="LOKI_URL")
    # Retención del histórico de audit_logs (1 año por defecto, alineado
    # con la política del producto documentada en memoria). Usada por la
    # task ``solidapp.purge_audit_logs`` (sprint Fase 3C 2026-07-01)
    # que borra filas con ``created_at < now - retention_days``.
    audit_log_retention_days: int = Field(default=365, alias="AUDIT_LOG_RETENTION_DAYS")

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
    trusted_proxies: list[str] = Field(
        default_factory=lambda: ["172.16.0.0/12", "10.0.0.0/8"],
        alias="TRUSTED_PROXIES",
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

    environment: Literal["development", "staging", "production", "test"] = Field(default="development", alias="ENVIRONMENT")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton para no releer el entorno en cada llamada."""
    return Settings()