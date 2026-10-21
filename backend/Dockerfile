# syntax=docker/dockerfile:1.6

# --- builder ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install --prefix=/install .

COPY app ./app

# --- runtime ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH=/install/lib/python3.11/site-packages:/app

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash app

WORKDIR /app
COPY --from=builder /install /install
COPY --from=builder /app/app ./app

# Sprint Fase 3A: directorio donde el RotatingFileHandler escribe
# /var/log/solidapp/backend.log (scrapeado por Promtail → Loki).
# El mkdir debe correr como root: /var/log es root:root y el usuario
# no-root no puede crear directorios dentro. Por eso va ANTES de
# ``USER app`` (si va después, falla con "Permission denied").
RUN mkdir -p /var/log/solidapp && chown -R app:app /var/log/solidapp
VOLUME ["/var/log/solidapp"]

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]