"""Servicio vehicle-detector separado: FastAPI + Ultralytics YOLO.

Recibe frames JPEG/PNG vía POST /detect (multipart upload) y devuelve
la lista de vehículos detectados en coordenadas del viewBox 960x540
del SVG de ``CalibrateView.vue``:

    [
      {"class_name": "car", "confidence": 0.92, "bbox": [x, y, w, h]},
      ...
    ]

El backend reescala internamente la imagen a 960x540 antes de inferir
para que el frontend pinte los bboxes directamente sobre el SVG sin
ninguna transformación de coordenadas.

Sprint Vehicle-Detect v2 (2026-07-07): modelo cambiado de
``yolov8n.pt`` (COCO) a ``best.pt`` (yolov8m fine-tuned en **VisDrone**,
dataset aéreo con drones: coches, vans, buses, motos, etc. en vista
cenital). yolov8n+COCO no detectaba prácticamente nada en capturas
de parking lot — COCO se entrena con fotos frontales/laterales, no
con vistas aéreas. VisDrone está específicamente anotado para ese caso.

El modelo NO está en los assets oficiales de Ultralytics; se descarga
una vez desde HuggingFace (``dronefreak/visdrone-yolov8m``) y se
cachea en el volumen ``vehicle_models`` para arranques instantáneos.

Si YOLO falla al cargar (modelo no descargado, error de runtime),
el endpoint /health devuelve 'degraded' pero /detect responde con []
en lugar de 500 — la app principal prefiere un silencio a un crash.

Endopints:
  GET  /health    → {status, engine, models_loaded}
  POST /detect    → [{class_name, confidence, bbox}, ...]

Variables de entorno:
  VD_MODEL=best.pt                              (nombre del modelo)
  VD_MODEL_URL=<HF resolve URL>                 (descarga inicial)
  VD_PORT=8800
  VD_MODELS_DIR=/models                         (los modelos se cachean aquí)
  VD_CONFIDENCE_THRESHOLD=0.25                  (umbral pre-flight)
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

log = logging.getLogger("vehicle-detector")
logging.basicConfig(level=os.getenv("VD_LOG_LEVEL", "INFO"))

VD_MODEL_NAME = os.getenv("VD_MODEL", "best.pt")
VD_MODEL_URL = os.getenv(
    "VD_MODEL_URL",
    "https://huggingface.co/dronefreak/visdrone-yolov8m/resolve/main/best.pt",
)
VD_PORT = int(os.getenv("VD_PORT", "8800"))
VD_MODELS_DIR = os.getenv("VD_MODELS_DIR", "/models")
# Sprint Vehicle-Detect v2 (2026-07-07): con yolov8m-visdrone (que SÍ
# detecta coches cenitales) subimos de 0.05 → 0.25. El modelo VisDrone
# ya discrimina bien vehículos vs. fondo, no necesitamos tanto recall
# agresivo. Umbral 0.25 = balance entre precision/recall.
VD_CONFIDENCE_THRESHOLD = float(os.getenv("VD_CONFIDENCE_THRESHOLD", "0.25"))

# Resolución fija a la que reescalamos antes de inferir. Coincide con el
# viewBox del SVG en CalibrateView.vue (frontend/src/views/gestor/CalibrateView.vue).
# El backend devuelve bboxes ya en estas coords: frontend las pinta con
# :x="d.bbox[0]" sin transformaciones.
DETECT_W = 960
DETECT_H = 540

# Clases VisDrone (10 clases del dataset): pedestrian, people, bicycle,
# car, van, truck, tricycle, awning-tricycle, bus, motor. Filtramos solo
# vehículos: bicycle/car/van/truck/tricycle/awning-tricycle/bus/motor.
# NO incluimos "pedestrian" ni "people" (peatones, no vehículos).
# ``tricycle`` y ``awning-tricycle`` son vehículos a 3 ruedas (motocarros),
# cuentan como "vehículos estacionados" en un parking.
VEHICLE_CLASSES = {
    "bicycle", "car", "van", "truck", "tricycle",
    "awning-tricycle", "bus", "motor",
}

app = FastAPI(title="solidapp-vehicle-detector", version="0.1.0")


class VehicleHit(BaseModel):
    class_name: str
    confidence: float
    bbox: list[int]  # [x, y, w, h] en coords 960x540


class HealthResponse(BaseModel):
    status: str
    engine: str
    models_loaded: bool
    uptime_s: float


# ── Descarga del modelo (la primera vez, cacheamos en volumen) ──────────
def _ensure_model_local() -> str:
    """Asegura que el modelo existe en ``VD_MODELS_DIR``. Si no, lo descarga
    desde ``VD_MODEL_URL`` (HuggingFace por defecto). Devuelve la ruta
    absoluta al .pt.

    Sprint Vehicle-Detect v2: yolov8m-visdrone NO está en los assets
    oficiales de Ultralytics, así que ultralytics no puede auto-descargarlo.
    Esta función es nuestro downloader explícito.
    """
    os.makedirs(VD_MODELS_DIR, exist_ok=True)
    model_path = os.path.join(VD_MODELS_DIR, VD_MODEL_NAME)
    if os.path.exists(model_path) and os.path.getsize(model_path) > 1_000_000:
        return model_path

    log.info(
        "Descargando modelo %s desde %s → %s",
        VD_MODEL_NAME, VD_MODEL_URL, model_path,
    )
    import urllib.request

    tmp_path = f"{model_path}.part"
    try:
        with urllib.request.urlopen(VD_MODEL_URL, timeout=120) as resp, \
             open(tmp_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        # Si la descarga falló a medio (archivo < 1 MB), algo fue mal.
        if os.path.getsize(tmp_path) < 1_000_000:
            raise RuntimeError(
                f"Descarga sospechosamente pequeña ({os.path.getsize(tmp_path)} B)"
            )
        os.replace(tmp_path, model_path)
        log.info("Modelo descargado: %s (%.1f MB)",
                 model_path, os.path.getsize(model_path) / 1024 / 1024)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return model_path


# ── Carga lazy de YOLO ────────────────────────────────────────────────────
# La primera petición a /detect instancia el motor. Si falla (memoria,
# modelo corrupto, descarga rota), _engine queda en None y /detect
# devuelve [].
_engine: Any = None
_engine_error: str | None = None
_started_at = time.monotonic()


def _get_engine() -> Any:
    """Instancia YOLO en la primera llamada y lo cachea en proceso."""
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    try:
        from ultralytics import YOLO  # type: ignore[import-untyped]

        # ultralytics respeta YOLO_CONFIG_DIR para el config interno.
        os.environ.setdefault("YOLO_CONFIG_DIR", VD_MODELS_DIR)
        model_path = _ensure_model_local()
        _engine = YOLO(model_path)
        log.info("YOLO cargado correctamente: %s", model_path)
    except Exception as exc:  # noqa: BLE001
        _engine_error = f"{type(exc).__name__}: {exc}"
        log.exception("No se pudo cargar YOLO: %s", _engine_error)
    return _engine


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Probe de Docker y de Compose.

    Devuelve 'ok' si el motor está cargado, 'degraded' si falló al cargar
    (sigue respondiendo, pero /detect devolverá []). Compose marca
    healthy/unhealthy según status_code, no según el cuerpo, así que
    siempre devolvemos 200 — la orquestación es responsabilidad del
    HEALTHCHECK del Dockerfile (curl -f).
    """
    return HealthResponse(
        status="ok" if _engine is not None else "degraded",
        engine="yolo",
        models_loaded=_engine is not None,
        uptime_s=round(time.monotonic() - _started_at, 1),
    )


def _resize_to_viewbox(arr: np.ndarray) -> np.ndarray:
    """Reescala la imagen a (DETECT_W, DETECT_H) preservando aspect ratio.

    OpenCV no estira: usa cv2.resize con INTER_AREA (mejor para reducir).
    Devuelve un ndarray (DETECT_H, DETECT_W, 3) en RGB.
    """
    import cv2  # type: ignore[import-untyped]

    h, w = arr.shape[:2]
    if (w, h) == (DETECT_W, DETECT_H):
        return arr
    return cv2.resize(arr, (DETECT_W, DETECT_H), interpolation=cv2.INTER_AREA)


@app.post("/detect", response_model=list[VehicleHit])
async def detect(image: UploadFile = File(...)) -> list[VehicleHit]:
    """Detecta vehículos en la imagen subida.

    Acepta image/jpeg, image/png. Devuelve lista vacía si no encuentra
    nada o si el motor no está cargado (preferimos 'no sé' a 'crash').
    """
    engine = _get_engine()
    if engine is None:
        log.warning("/detect llamado pero motor no disponible: %s", _engine_error)
        return []

    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Imagen vacía")

    # Decodificamos a numpy.ndarray desde bytes en memoria (sin tocar disco).
    try:
        import cv2  # type: ignore[import-untyped]

        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("cv2.imdecode devolvió None (formato no soportado)")
        # cv2 devuelve BGR; YOLO acepta ambos pero trabajamos en RGB para
        # consistencia con el resto del pipeline.
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Imagen no válida: {exc}") from exc

    # Reescalar a 960x540 (viewBox del SVG) ANTES de inferir → bboxes
    # devueltos en coords 0-960 / 0-540.
    img_resized = _resize_to_viewbox(img)

    # YOLO .predict() es sync. En CPU para 960x540 con yolov8n: ~300-500 ms.
    # verbose=False silencia el log por-frame.
    # imgsz=960 (NO (DETECT_H, DETECT_W)) → YOLO hace upscaling interno a
    # 960x960 antes de inferir, lo que mejora DETECT_DE_OBJETOS_PEQUEÑOS
    # (coches cenitales a veces ocupan <100 px de ancho tras el resize).
    try:
        results = engine.predict(
            img_resized,
            conf=VD_CONFIDENCE_THRESHOLD,
            imgsz=960,
            verbose=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Fallo en engine.predict: %s", exc)
        return []

    hits: list[VehicleHit] = []
    if not results:
        return hits
    try:
        for r in results:
            names = r.names  # dict {int(class_id): class_name}
            for box in r.boxes or []:
                cls_id = int(box.cls[0].item())
                cls_name = str(names.get(cls_id, cls_id))
                if cls_name not in VEHICLE_CLASSES:
                    continue
                conf = float(box.conf[0].item())
                # xywh son las coords en el espacio de la imagen de entrada
                # (960x540), no las de la original. Formato: [cx, cy, w, h].
                xywh = box.xywh[0].tolist()
                cx, cy, w, h = (int(v) for v in xywh)
                x = max(0, cx - w // 2)
                y = max(0, cy - h // 2)
                w = min(w, DETECT_W - x)
                h = min(h, DETECT_H - y)
                hits.append(
                    VehicleHit(
                        class_name=cls_name,
                        confidence=round(conf, 4),
                        bbox=[x, y, w, h],
                    )
                )
    except Exception as exc:  # noqa: BLE001
        log.exception("Formato de respuesta YOLO inesperado: %s", exc)
        return []

    log.info("/detect: %d vehículos detectados", len(hits))
    return hits


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=VD_PORT, log_level="info")
