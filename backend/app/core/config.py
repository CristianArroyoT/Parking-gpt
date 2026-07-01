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
    # URL del servicio OCR separado (PaddleOCR en su propio contenedor).
    # Si el servicio no responde, el cliente devuelve [] y el caller
    # decide qué hacer. NO usar en tests salvo que se inyecte MockTransport.
    ocr_service_url: str = Field(
        default="http://localhost:8800", alias="OCR_SERVICE_URL"
    )
    ocr_service_timeout: float = Field(
        default=4.0, alias="OCR_SERVICE_TIMEOUT"
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
    # con la política del producto documentada en memoria). La rotación
    # automática entra en el sprint 3D; este setting es la fuente de verdad.
    audit_log_retention_days: int = Field(default=365, alias="AUDIT_LOG_RETENTION_DAYS")

    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="solidAPP <no-reply@solidapp.es>", alias="SMTP_FROM")

    environment: Literal["development", "staging", "production"] = Field(default="development", alias="ENVIRONMENT")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton para no releer el entorno en cada llamada."""
    return Settings()