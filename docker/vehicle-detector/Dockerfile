# Servicio vehicle-detector separado: ejecuta Ultralytics YOLO dentro de
# su propio contenedor (~500 MB RSS en CPU) para no engordar la imagen
# del backend. El backend le envía frames JPEG por HTTP (POST /detect
# con multipart) y recibe
# [{class_name, confidence, bbox: [x,y,w,h]}, ...] como JSON.
#
# La primera vez que arranca, se descarga el modelo (yolov8m fine-tuned
# en VisDrone, ~50 MB) a /models. Se persiste en el volumen
# 'vehicle_models' para que arranques posteriores sean instantáneos.
#
# Sprint Vehicle-Detect v2 (2026-07-07): el modelo por defecto es
# ``best.pt`` (yolov8m-VisDrone), NO ``yolov8n.pt`` (COCO). COCO se
# entrena con fotos frontales/laterales y apenas detectaba nada en
# vistas aéreas de parking. Este default estaba desactualizado respecto
# a ``docker-compose.yml`` (que ya usaba ``best.pt``): T-09 del plan de
# pendientes lo alineó.
#
# ``best.pt`` no está en los assets oficiales de Ultralytics: lo baja
# la app desde HuggingFace (VD_MODEL_URL) la primera vez.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VD_MODEL=best.pt \
    VD_PORT=8800 \
    VD_MODELS_DIR=/models \
    VD_CONFIDENCE_THRESHOLD=0.25

# Deps de sistema mínimas para OpenCV (carga de imagen) y curl (healthcheck).
# torch instala sus propias libs (libgomp, etc.) vía wheels — no hacen falta aquí.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin torch a CPU explícitamente para evitar el wheel CUDA (~2.5 GB).
# ultralytics 8.x es compatible con torch 2.2+.
COPY requirements.txt /tmp/requirements.txt
RUN pip install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# La app FastAPI vive en /app/app.py.
COPY app.py /app/app.py

# Crea el usuario no-root para correr el servicio (LOPDGDD: mínimo privilegio).
RUN useradd --create-home --shell /bin/bash vd \
    && mkdir -p /models \
    && chown -R vd:vd /app /models
USER vd

EXPOSE 8800

# start-period=120s: la primera vez tarda en descargar best.pt (~50 MB)
# y cargar el modelo en memoria (warm-up ~2-3 s + carga ~3-5 s).
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:${VD_PORT}/health || exit 1

# tini reapea procesos zombi y propaga señales correctamente.
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800", "--workers", "1"]
