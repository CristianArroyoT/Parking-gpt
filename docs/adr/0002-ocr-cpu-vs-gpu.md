# ADR-0002 · OCR con GPU: no, por ahora

- **Estado**: Aceptada
- **Fecha**: 2026-10-21
- **Ítem del plan**: T-14 (Bloque 2 · I2 — Evaluar la GPU para el OCR)
- **Datos**: [`docker/ocr/reports/2026-10-21-cpu-vs-gpu.txt`](../../../docker/ocr/reports/2026-10-21-cpu-vs-gpu.txt)
- **Benchmark**: [`docker/ocr/benchmark.py`](../../../docker/ocr/benchmark.py)

---

## Contexto

El MVP tiene **50 cámaras** (5 sucursales × 10 cámaras) y el objetivo de
producto es **50+ sucursales** (500 cámaras si cada una tiene 10 cámaras).

El OCR es el servicio más pesado del stack: PaddleOCR (PaddlePaddle 2.6.2 +
PaddleOCR 2.7.3) con modelos PP-OCRv4 de detección y reconocimiento.

La pregunta: **¿aporta algo meter el OCR en una GPU?** No es una pregunta
retórica: la respuesta cambia el hardware que se compra para cada sucursal
y el tamaño de la imagen del servicio.

## Lo que se midió (no esalted, no es estimado)

RTX 2060 (6 GB) con el runtime `nvidia` de Docker Desktop. Dos imágenes del
**mismo** servicio OCR, una con `paddlepaddle` (CPU) y otra con
`paddlepaddle-gpu` sobre CUDA 11.8 + cuDNN 8. El benchmark genera una imagen
de 1280×720 con una matrícula sintética y mide la llamada completa del
cliente (ida + vuelta), con warmup aparte para no contar la carga del modelo.

| Concurrencia | CPU p50 | CPU p95 | CPU ocr/s | GPU p50 | GPU p95 | GPU ocr/s | Ganancia |
|---|---|---|---|---|---|---|---|
| 1 | 329 ms | 530 ms | 2,82 | 302 ms | 417 ms | 3,08 | 1,1× |
| 8 | 2 905 ms | 3 546 ms | 2,67 | 975 ms | 1 551 ms | 7,38 | **2,8×** |
| 16 | 4 286 ms | 6 006 ms | 3,29 | 1 721 ms | 2 553 ms | **7,89** | 2,4× |
| 32 | 8 702 ms | 11 601 ms | 3,16 | 4 295 ms | 5 540 ms | 6,48 | 2,0× |

Hallazgos:

1. **En secuencial la GPU no aporta** (1,1×). Con una imagen tan pequeña, el
   trabajo por petición es tan pequeño que el coste de lanzar los kernels y
   copiar la imagen a la GPU se come la ventaja.
2. **En concurrencia la GPU sí**: 2,8× de throughput a concurrencia 8.
3. La **CPU satura en ~3,2 ocr/s** por instancia. A partir de ahí el p95 se
   dispara (11,6 s en concurrencia 32) sin que suba el throughput: es cola
   de espera, no más capacidad.
4. La **GPU satura en ~7,9 ocr/s** por instancia.

## La carga real (esto es lo que decide)

El OCR **no** se llama por cada frame de cámara. Lo invoca el beat de Celery
(`tick_cameras`, cada 60 s), que hace **una captura y un OCR por cámara y
minuto**:

```
carga (ocr/s) = nº de cámaras / 60
```

| Escenario | Cámaras | Carga | Instancias CPU | Instancias GPU |
|---|---|---|---|---|
| MVP (5 sucursales × 10) | 50 | 0,83 ocr/s | 1 (25 % de ocupación) | 1 (11 %) |
| Objetivo (50 sucursales × 10) | 500 | 8,33 ocr/s | 3 | 2 |

## Decisión

**No activar la GPU. Se descarta con datos, y se deja la variante preparada.**

Motivos, por peso:

1. **El modelo de despliegue no tiene GPU donde hace falta.** Según
   [ADR-0001](0001-orquestacion-produccion.md), cada sucursal corre su propio
   servidor local (4-8 GB de RAM, sin GPU) y el OCR es **local** a la
   sucursal: el beat de Celery y el worker de cada sucursal disparan las
   capturas y el OCR contra el servicio OCR de esa misma sucursal. En ese
   hardware **no hay GPU que poner**, y la CPU de la sucursal sobra de largo
   (10 cámaras = 0,17 ocr/s frente a los 3,2 ocr/s de capacidad).
2. **En el MVP la CPU va sobrada.** 50 cámaras = 0,83 ocr/s contra 3,2 de
   capacidad: un 25 % de ocupación. Meter una GPU sería añadir hardware,
   una imagen 3 GB más y una complication (el runtime `nvidia`, la
   cuDNN…) para no ganar nada.
3. **La GPU sólo es relevante si el OCR se centraliza**, y ese escenario
   contradice el modelo de producto «servidor local en la sucursal»
   (que es lo que da al sistema su resiliencia cuando se cae el enlace).

### Cuándo revisar esta decisión

| Disparador | Qué hacer |
|---|---|
| El OCR se centraliza en vez de ser local a la sucursal | Reevaluar: 500 cámaras = 8,33 ocr/s y la GPU da 2,4-2,8× |
| Una sucursal supera las **~190 cámaras** (CPU saturada) | Evaluar GPU **en esa sucursal** o más réplicas CPU |
| El p95 del OCR en producción supera **2 s** | Señal de saturación: escalar primero réplicas CPU (más simple) |
| Sale una GPU integrada de bajo consumo y precio (NPU en el servidor de sucursal) | Reevaluar la ecuación de hardware |

## Qué se deja preparado

- **`docker/ocr/Dockerfile.gpu`**: la variante GPU, completa y documentada.
  Construir: `docker build -f docker/ocr/Dockerfile.gpu -t solidapp-ocr:gpu docker/ocr`.
  Ejecutar: `docker run -d --runtime=nvidia --gpus all -p 8890:8800 -v parking_ocr_models:/models solidapp-ocr:gpu`.
- **Los dos detalles que hacen que funcione** (y que no son obvios):
  - Las imágenes `nvidia/cuda:*-runtime` traen las librerías CUDA **con
    versión** (`libcublas.so.11`, `libcudnn.so.8`). Paddle las carga con
    `dlopen("libcublas.so")`, **sin versión**: sin crear los enlaces, falla
    con `RuntimeError: Cannot load cudnn shared library`.
  - `LD_LIBRARY_PATH` de la imagen no incluye `/usr/local/cuda/lib64`.
  - El `requirements.txt` pide `paddlepaddle` (CPU) porque es lo que necesita
    la variante de CPU: en la imagen GPU hay que **desinstalarlo** y poner
    `paddlepaddle-gpu`, o el `import paddle` acabará cargando las librerías
    de CPU y la GPU no se usará sin avisar.
- **`docker/ocr/benchmark.py`**: el benchmark, que corre contra cualquier
  instancia (CPU o GPU) y devuelve el JSON de resultados.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Activar la GPU en el MVP | La carga real (0,83 ocr/s) no lo justifica; el hardware de sucursal no tiene GPU |
| Centralizar el OCR en un servidor con GPU | Contradice el modelo de producto (resiliencia local ante caída del enlace); ver ADR-0001 |
| Optimizar PaddleOCR (modelos más ligeros, ONNX, batching) | Es la palanca real si el OCR se centralizara:reduce latencia en CPU, no sólo la mueve de sitio. Se deja como línea de trabajo futura |
| Instalar la GPU «por si acaso» | El coste no es sólo el hardware: es una imagen 3 GB más, el runtime `nvidia` y un `Dockerfile.gpu` que mantener |
