"""Punto de entrada FastAPI: app factory + middlewares + routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import AuditMiddleware
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Sprint Fase 3A: logger JSON / file rotado ANTES de aceptar tráfico.
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="solidAPP API",
        version="0.1.0",
        description="Backend de gestión de parkings con OCR (MVP Fase 1).",
        lifespan=lifespan,
    )
    # Sprint Fase 3A: extrae user_id/ip/correlation_id en cada request
    # y los persiste en request.state.audit para los handlers.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0")

    return app


app = create_app()
