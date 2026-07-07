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

Si YOLO falla al cargar (modelo no descargado, error de runtime),
el endpoint /health devuelve 'degraded' pero /detect responde con []
en lugar de 500 — la app principal prefiere un silencio a un crash.

Endopints:
  GET  /health    → {status, engine, models_loaded}
  POST /detect    → [{class_name, confidence, bbox}, ...]

Variables de entorno:
  VD_MODEL=yolov8n.pt       (nombre del modelo o ruta local)
  VD_PORT=8800
  VD_MODELS_DIR=/models     (los modelos se cachean en este dir)
  VD_CONFIDENCE_THRESHOLD=0.35
"""
from __future__ import annotations

import io
import logging
import os
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

log = logging.getLogger("vehicle-detector")
logging.basicConfig(level=os.getenv("VD_LOG_LEVEL", "INFO"))

VD_MODEL_NAME = os.getenv("VD_MODEL", "yolov8n.pt")
VD_PORT = int(os.getenv("VD_PORT", "8800"))
VD_MODELS_DIR = os.getenv("VD_MODELS_DIR", "/models")
VD_CONFIDENCE_THRESHOLD = float(os.getenv("VD_CONFIDENCE_THRESHOLD", "0.35"))

# Resolución fija a la que reescalamos antes de inferir. Coincide con el
# viewBox del SVG en CalibrateView.vue (frontend/src/views/gestor/CalibrateView.vue).
# El backend devuelve bboxes ya en estas coords: frontend las pinta con
# :x="d.bbox[0]" sin transformaciones.
DETECT_W = 960
DETECT_H = 540

# Subset COCO que nos interesa para "vehiculo estacionado" (cenital).
# NO incluimos "person" (peatón) ni "train" (no aplica en parking).
VEHICLE_CLASSES = {
    "bicycle", "car", "motorcycle", "bus", "truck",
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


# ── Carga lazy de YOLO ────────────────────────────────────────────────────
# La primera petición a /detect instancia el motor. Si falla (memoria,
# modelo corrupto), _engine queda en None y /detect devuelve [].
_engine: Any = None
_engine_error: str | None = None
_started_at = time.monotonic()


def _get_engine() -> Any:
    """Instancia YOLO en la primera llamada y lo cachea en proceso.

    YOLO descarga el modelo a ``VD_MODELS_DIR`` la primera vez
    (~6 MB para yolov8n.pt). Ese volumen se persiste vía compose,
    así arranques posteriores son instantáneos.
    """
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    try:
        from ultralytics import YOLO  # type: ignore[import-untyped]

        # ultralytics respeta YOLO_CONFIG_DIR para el config interno; le
        # forzamos el dir de modelos. model_path puede ser un nombre
        # builtin (yolov8n.pt) que descarga automáticamente, o una ruta.
        os.environ.setdefault("YOLO_CONFIG_DIR", VD_MODELS_DIR)
        model_path = VD_MODEL_NAME
        if not os.path.isabs(model_path):
            model_path = os.path.join(VD_MODELS_DIR, VD_MODEL_NAME)
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
    try:
        results = engine.predict(
            img_resized,
            conf=VD_CONFIDENCE_THRESHOLD,
            imgsz=(DETECT_H, DETECT_W),
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
