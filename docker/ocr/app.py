"""Servicio OCR separado: FastAPI + PaddleOCR.

Recibe frames JPEG/PNG vía POST /recognize (multipart upload) y devuelve
la lista de matrículas detectadas:

    [
      {"plate": "1234ABC", "confidence": 0.97, "bbox": [x1, y1, x2, y2]},
      ...
    ]

Si PaddleOCR falla al cargar (modelos no descargados, error de runtime),
el endpoint /health devuelve 'degraded' pero /recognize responde con []
en lugar de 500 — la app principal prefiere un silencio a un crash.

Endopints:
  GET  /health   → {status, engine, models_loaded}
  POST /recognize → [{plate, confidence, bbox}, ...]

Variables de entorno:
  OCR_ENGINE=paddle       (reservado para Tesseract en futuro)
  OCR_PORT=8800
  OCR_MODELS_DIR=/models  (los modelos se cachean en este dir)
  OCR_LANG=en             (lang de PaddleOCR: en para matrículas EU)
"""
from __future__ import annotations

import io
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

log = logging.getLogger("ocr")
logging.basicConfig(level=os.getenv("OCR_LOG_LEVEL", "INFO"))

OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle")
OCR_PORT = int(os.getenv("OCR_PORT", "8800"))
OCR_MODELS_DIR = os.getenv("OCR_MODELS_DIR", "/models")
OCR_LANG = os.getenv("OCR_LANG", "en")

app = FastAPI(title="solidapp-ocr", version="0.1.0")


class PlateHit(BaseModel):
    plate: str
    confidence: float
    bbox: list[int]


class HealthResponse(BaseModel):
    status: str
    engine: str
    models_loaded: bool
    uptime_s: float


# ── Carga lazy de PaddleOCR ──────────────────────────────────────────────
# La primera petición a /recognize instancia el motor. Si falla (memoria,
# modelo corrupto), _engine queda en None y /recognize devuelve [].
_engine: Any = None
_engine_error: str | None = None
_started_at = time.monotonic()


def _get_engine() -> Any:
    """Instancia PaddleOCR en la primera llamada y lo cachea en proceso.

    PaddleOCR descarga los modelos al directorio OCR_MODELS_DIR la primera
    vez. Ese volumen se persiste vía compose, así arranques posteriores son
    instantáneos (~1-2 s de carga del modelo ya cacheado).
    """
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    try:
        # PaddleOCR < 3.x: import desde paddleocr.
        from paddleocr import PaddleOCR  # type: ignore[import-untyped]

        # use_angle_cls=False: las matrículas no van rotadas.
        # show_log=False: silencio en stdout (el contenedor ya tiene logs).
        # det=True, rec=True, cls=False: queremos detección + reconocimiento.
        _engine = PaddleOCR(
            use_angle_cls=False,
            lang=OCR_LANG,
            show_log=False,
            det_model_dir=os.path.join(OCR_MODELS_DIR, "det"),
            rec_model_dir=os.path.join(OCR_MODELS_DIR, "rec"),
            cls_model_dir=os.path.join(OCR_MODELS_DIR, "cls"),
        )
        log.info("PaddleOCR cargado correctamente")
    except Exception as exc:  # noqa: BLE001
        _engine_error = f"{type(exc).__name__}: {exc}"
        log.exception("No se pudo cargar PaddleOCR: %s", _engine_error)
    return _engine


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Probe de Docker y de Compose.

    Devuelve 'ok' si el motor está cargado, 'degraded' si falló al cargar
    (sigue respondiendo, pero /recognize devolverá []). Compose marca
    healthy/unhealthy según status_code, no según el cuerpo, así que
    siempre devolvemos 200 — la orquestación es responsabilidad del
    HEALTHCHECK del Dockerfile (curl -f).
    """
    return HealthResponse(
        status="ok" if _engine is not None else "degraded",
        engine=OCR_ENGINE,
        models_loaded=_engine is not None,
        uptime_s=round(time.monotonic() - _started_at, 1),
    )


@app.post("/recognize", response_model=list[PlateHit])
async def recognize(image: UploadFile = File(...)) -> list[PlateHit]:
    """Detecta matrículas en la imagen subida.

    Acepta image/jpeg, image/png. Devuelve lista vacía si no encuentra
    nada o si el motor no está cargado (preferimos 'no sé' a 'crash').
    """
    engine = _get_engine()
    if engine is None:
        log.warning("/recognize llamado pero motor no disponible: %s", _engine_error)
        return []

    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Imagen vacía")

    # Decodificamos a numpy.ndarray desde bytes en memoria (sin tocar disco).
    try:
        import numpy as np
        from PIL import Image

        pil_img = Image.open(io.BytesIO(raw)).convert("RGB")
        arr = np.array(pil_img)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Imagen no válida: {exc}") from exc

    # PaddleOCR .ocr() es sync pero ligero (~50-200 ms por frame).
    try:
        # `cls=False` lo pasamos en la creación; aquí invocamos ocr().
        result = engine.ocr(arr, cls=False)
    except Exception as exc:  # noqa: BLE001
        log.exception("Fallo en engine.ocr: %s", exc)
        return []

    hits: list[PlateHit] = []
    if not result:
        return hits
    # result = [ [ [bbox, (text, conf)], ... ] ] cuando hay det+rec.
    # Algunos builds devuelven estructura diferente; normalizamos.
    try:
        for page in result:
            for line in page or []:
                bbox_pts, (text, conf) = line
                plate = str(text).strip().replace(" ", "")
                # bbox_pts es [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                xs = [int(p[0]) for p in bbox_pts]
                ys = [int(p[1]) for p in bbox_pts]
                hits.append(
                    PlateHit(
                        plate=plate,
                        confidence=round(float(conf), 4),
                        bbox=[min(xs), min(ys), max(xs), max(ys)],
                    )
                )
    except Exception as exc:  # noqa: BLE001
        log.exception("Formato de respuesta PaddleOCR inesperado: %s", exc)
        return []

    log.info("/recognize: %d matrículas detectadas", len(hits))
    return hits


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=OCR_PORT, log_level="info")