# solidAPP · vehicle-detector

Servicio de detección de vehículos en vista cenital para el **pre-flight de
calibración de geocercas** (`CalibrateView.vue`).

Se mantiene en su propio contenedor para no engordar la imagen del backend:
Ultralytics + torch en CPU ocupan ~500 MB de RSS que el backend no necesita.

---

## Modelo

| Campo | Valor |
|---|---|
| Modelo | `best.pt` — **yolov8m fine-tuned en VisDrone** |
| Origen | [`dronefreak/visdrone-yolov8m`](https://huggingface.co/dronefreak/visdrone-yolov8m) (HuggingFace) |
| Tamaño | ~50 MB (52 053 138 bytes exactos) |
| Umbral de confianza | `0.25` (`VD_CONFIDENCE_THRESHOLD`) |
| Tamaño de inferencia | `imgsz=960` |
| Caché | volumen Docker `vehicle_models` → `/models` |

**Por qué VisDrone y no COCO**: el dataset VisDrone está anotado específicamente
para imágenes aéreas de drones (coches, vans, buses, motos…). `yolov8n.pt` de
COCO se entrena con fotos frontales/laterales y en las capturas de un parking
cenital no detectaba prácticamente nada. El commit `20f6cac` cambió el modelo
por esto.

`best.pt` **no** está en los assets oficiales de Ultralytics: no se puede
descargar con `YOLO("best.pt")`. La app lo baja explícitamente de HuggingFace
en el primer arranque (`_ensure_model_local`) y lo deja en `/models`. El
volumen persiste el fichero, así que **el segundo arranque no vuelve a
descargarlo** (verificado: el arranque posterior tardó < 1 s en servir `/health`
con el modelo ya en caché).

### Clases que se devuelven

De las 11 clases de VisDrone se filtran sólo vehículos:
`bicycle`, `car`, `van`, `truck`, `tricycle`, `awning-tricycle`, `bus`, `motor`.

Se descartan `pedestrian` y `people` (peatones, no vehículos).

---

## API

### `GET /health`

```json
{ "status": "ok", "engine": "yolo", "models_loaded": true, "uptime_s": 42.1 }
```

`status` es `"degraded"` mientras el motor no se haya cargado: **la carga es
perezosa** (ocurre en el primer `/detect`). El contenedor queda `healthy` en
cuanto `/health` responde 200, que es lo que mira el `HEALTHCHECK`.

### `POST /detect`

`multipart/form-data` con el campo `image` (JPEG o PNG).

```json
[
  { "class_name": "car", "confidence": 0.267, "bbox": [209, 321, 112, 160] }
]
```

`bbox` es `[x, y, w, h]` en coordenadas del **viewBox 960×540** del SVG de
`CalibrateView.vue`. El servicio reescala la imagen a 960×540 antes de
inferir, de modo que el frontend puede pintar los bbox directamente sobre el
SVG sin transformar coordenadas.

**Fallo abierto**: si el motor no está cargado o `predict` falla, `/detect`
devuelve `200 []` en lugar de un 500. La app prefiere un «no he detectado nada»
a un crash; el cliente HTTP del backend (`app/services/vehicle_detector/client.py`)
aplica la misma política.

---

## Ejecutar

```bash
# Stack completo (el detector arranca con el resto)
docker compose up -d vehicle-detector

# Logs
docker logs parking-vehicle-detector-1 -f

# Health desde el host
curl http://localhost:8802/health
```

## Tests

Los tests del servicio se ejecutan **dentro de la imagen** (necesitan
`ultralytics` y `opencv`):

```bash
docker run --rm \
  -v "${PWD}/docker/vehicle-detector:/app" \
  -v parking_vehicle_models:/models \
  solidapp-vehicle-detector:latest \
  sh -c "pip install -q pytest && python -m pytest tests -q"
```

(Ojo: `python -m pytest`, no `pytest` — la imagen corre como usuario no-root
`vd` y el script queda en `~/.local/bin`, que no está en el `PATH`.)

Cubren el contrato de **orden de canales BGR** (ver «Historia» abajo), que es
la clase de bug que dejó el detector **sin detectar nada** sin dar ningún error.

---

## Historia: el bug de los canales invertidos (2026-10-21, T-09)

La imagen se decodificaba con OpenCV y se convertía a RGB antes de inferir:

```python
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)   # ← el bug
```

**Ultralytics asume que un array numpy viene en BGR** y lo invierte internamente
a RGB (`im0[..., ::-1]`). Al entregarle RGB, se aplicaba un segundo intercambio
y el modelo veía los colores al revés.

Medido sobre una foto real con coches:

| Entrada | Detecciones |
|---|---|
| BGR (correcto) | `car 0.267`, `car 0.131`, `bus 0.072` |
| RGB (con el bug) | **ninguna** |

Como `/detect` responde `200 []` ante cualquier problema, en la aplicación el
síntoma era «el botón 🔍 Detectar vehículos nunca encuentra nada», que es
indistinguible de «no hay ningún vehículo en la plaza». La calibración con
pre-flight quedaba neutralizada sin dejar rastro en los logs.

La corrección está en `_decode_image()` (`app.py`), que deja la imagen en BGR y
documenta el porqué; `tests/test_detect_channel_order.py` fija el contrato.

---

## Limitación conocida de la QA

El RTSP de prueba del entorno de QA (`rtsp://parking-mediamtx:8554/cam1`) emite
un **esquema sintético** —fondos oscuros con plazas dibujadas y un rectángulo
que representa un vehículo—, no una vista aérea real.

Un modelo entrenado con fotos reales **no detecta nada** en ese vídeo: no es un
fallo del servicio, es que el fixture no está en el dominio del modelo. Para
validar la detección con resultados no vacíos hay que usar una captura real
(foto de un parking en vista cenital), no el RTSP esquemático de QA.
