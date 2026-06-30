# Servicio OCR separado: ejecuta PaddleOCR dentro de su propio contenedor
# (~1.5 GB) para no engordar la imagen del backend. El backend le envía
# frames por HTTP (POST /recognize con multipart) y recibe
# [{plate, confidence, bbox}, ...] como JSON.
#
# La primera vez que arranca, PaddleOCR descarga los modelos a
# ~/.paddleocr (~100 MB). Se persiste en el volumen 'ocr_models' para
# que arranques posteriores sean instantáneos.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OCR_ENGINE=paddle \
    OCR_PORT=8800 \
    OCR_MODELS_DIR=/models

# Deps de sistema mínimas para PaddlePaddle (OpenMP) y OpenCV (carga de imagen).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# La app FastAPI vive en /app/app.py.
COPY app.py /app/app.py

# Crea el usuario no-root para correr el servicio (LOPDGDD: mínimo privilegio).
RUN useradd --create-home --shell /bin/bash ocr \
    && mkdir -p /models \
    && chown -R ocr:ocr /app /models
USER ocr

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=5s --start_period=60s --retries=3 \
    CMD curl -fsS http://localhost:${OCR_PORT}/health || exit 1

# tini reapea procesos zombi y propaga señales correctamente.
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800", "--workers", "1"]