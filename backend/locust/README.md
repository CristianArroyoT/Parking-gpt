# Pruebas de carga de solidAPP (Locust) — T-13

Escenarios de carga contra la API real del backend, con un **SLO verificable**
y un **informe de referencia guardado en el repo**.

- Escenarios (`backend/locustfile.py`): login, mapa en vivo (SSE), cierre de
  ticket y preview en vivo (MJPEG).
- SLO (`backend/locust/slo.json`): umbrales de latencia y de ausencia de cortes.
- Verificador (`backend/locust/check_slo.py`): lee el informe JSON de Locust y
  devuelve código de salida `!= 0` si el SLO no se cumple → integrable en CI.
- Preflight (`backend/locust/preflight.py`): comprueba que el entorno responde
  antes de cargar (si no, el informe mide un entorno roto, no el producto).
- Informe de referencia (`backend/locust/reports/2026-10-21-referencia.json`).

## 1. Hallazgos de la ejecución de referencia (lo importante)

La carga no sólo mide: **ha encontrado dos defectos de producción**.

### 1.1 · P0 — cerrar el preview en vivo tumba el backend (SIGSEGV)

Cada vez que un cliente cierra el stream MJPEG, el worker de uvicorn **muere
con SIGSEGV (exit 139)**:

```
app.services.cameras.stream: mjpeg: stream cerrado camera=81 url=rtsp://parking-mediamtx:8554/cam1
<worker muere>   →  docker: Exited (139)
```

La causa es una carrera en `app/services/cameras/stream.py`: el generador
libera el `cv2.VideoCapture` en su `finally` (`cap.release()`) mientras el
`await asyncio.to_thread(cap.grab)` sigue en vuelo en otro hilo; cuando ese
hilo vuelve a tocar la captura ya liberada, revienta el proceso.

En el entorno de QA el `--reload` de uvicorn lo tapa (el worker reinicia solo),
pero **en producción, sin `--reload`, el backend entero se cae cada vez que un
operador cierra el modal de preview**. Reproducido 4/4 ejecuciones de carga
con el escenario de preview.

Efecto medido en la referencia contaminada: 3 caídas del worker en 180 s →
36 peticiones fallidas (`HTTP 0`, el servidor estaba caído) y el p95 de
`lectura_tickets` subió de 15 ms (mediana) a 1,1 s.

**Estado: CORREGIDO** (ver `app/services/cameras/stream.py`). El arreglo
envuelve el `cv2.VideoCapture` en `CapturaSincronizada`, que serializa con un
`threading.Lock` **todas** las llamadas a OpenCV (`grab`, `retrieve`,
`release`): el `release()` del `finally` espera a que termine la lectura en
vuelo en vez de competir con ella. El lock es de `threading` y no de asyncio
porque las dos partes viven en hilos distintos (el `grab()` en el thread pool,
el `release()` en el event loop).

Verificado antes/después con la misma reproducción
(`backend/tests/manual_repro_cierre_preview.py`, 20 cierres abruptos del
preview contra un uvicorn **sin** `--reload`):

| código | resultado |
|---|---|
| anterior al arreglo | el worker **muere con SIGSEGV (exit -11) tras 5 cierres** |
| con el arreglo | **20 cierres y el proceso sigue vivo**, `/health` → 200 |

El test de regresión unitario está en
`backend/tests/test_mjpeg_capture_safety.py`: falla si alguien vuelve a
soltar el lock.

La reproducción manual queda en
`backend/tests/manual_repro_cierre_preview.py` (levanta un uvicorn sin
`--reload`, cierra el preview 20 veces de golpe y comprueba que el
proceso sobrevive). Con `APP_DIR` se le puede apuntar a otra copia del
código para comparar el antes y el después.

### 1.2 · P1 — cada stream abierto retiene (y a veces filtra) una conexión de PostgreSQL

Los endpoints de streaming (`/parkings/{id}/events` y
`/parkings/{id}/cameras/{id}/live`) declaran `db: Session = Depends(get_db)`.
FastAPI cierra esa sesión **después** de que termine la respuesta, así que
**cada stream abierto mantiene una conexión del pool durante toda su vida**.
Con el pool por defecto (5 + 10 de *overflow* = 15) el objetivo de producto de
**50 streams simultáneos** no cabe: la API se quedaría sin conexiones.

Además, cuando el cliente aborta el stream antes de tiempo (una pestaña
cerrada, un `timeout` del cliente), la sesión **no se cierra** y la conexión
se queda en `idle in transaction` (medido: 5 conexiones filtradas tras una
ejecución de 90 s con 2 streams):

```sql
select state, count(*) from pg_stat_activity where datname='parking' group by state;
--  idle               | 6
--  idle in transaction | 5   <-- filtradas
```

**Estado: CORREGIDO** (ver `app/api/v1/cameras_live.py` y
`app/api/v1/events.py`). Los endpoints de streaming ya **no** declaran
`db: Session = Depends(get_db)`: resuelven la autenticación, el RBAC y la
lectura que necesitan con una **sesión corta**, abierta y cerrada *antes*
de empezar a emitir. El generador del preview recibe un `CameraRef` (sólo
`id` y `rtsp_url`), no un modelo ORM vivo.

Medido después del arreglo: durante el preview hay **0** conexiones en
`idle in transaction` (antes: 1 por stream), que es lo que hace el objetivo
de 50 streams simultáneos caber en el pool.

### 1.3 · P2 — reabrir el preview da 409 durante hasta ~8 s

`live_streams` sólo libera la cámara cuando el generador termina, y el
generador puede tardar (esperando al FFmpeg) o la sesión caduca a los 8 s sin
frames (`STALE_AFTER_S`). El operador que cierra y reabre el preview se
encuentra un **409 "Ya hay una vista en vivo abierta"**. Con el RTSP real
medido: el 409 aparece si se reintenta antes de ~8 s.

**Estado: CORREGIDO** (ver `app/services/cameras/live_streams.py`,
`app/services/cameras/stream.py` y `app/api/v1/cameras_live.py`). Debajo
del síntoma había **cuatro** defectos encadenados:

1. **El teardown del RTSP corría en el hilo del event loop.**
   `CapturaSincronizada.release()` espera a que termine la lectura en vuelo, y
   con la cámara colgada esa espera llega hasta el timeout de FFmpeg (5 s):
   **se congelaba el backend entero**, no sólo ese stream.
2. **El slot se liberaba después del teardown**: el `finally` del generador
   interno (el que cierra la captura) se ejecuta antes que el del generador
   externo (el que suelta el slot), así que la cámara quedaba ocupada durante
   todo el teardown.
3. **La liberación no era determinista**: al abortarse la petición,
   Starlette cancela la tarea del stream y el generador se cierra después, por
   el finalizador de generadores asíncronos del event loop. En el peor caso
   el slot se quedaba hasta el barrido de huérfanas (8 s).
4. **`release(camera_id)` no sabía a qué sesión pertenecía la llamada** (la
   LIMITACIÓN CONOCIDA documentada en su propio docstring): el `finally` de un
   generador viejo podía liberar la sesión de un cliente **nuevo** y matarle
   el stream.

El arreglo: el generador suelta el slot **antes** de limpiar la captura
(callback síncrono `on_session_end`), el teardown va a un hilo
(`asyncio.to_thread`) para no congelar el event loop, la respuesta suelta el
slot de forma **determinista** al terminar (`_PreviewResponse`), y
`release()`/`heartbeat()` reciben la **sesión** para no tocar la de otro
cliente. El registro de streams pasa a una API **síncrona**: una liberación
con `await` dentro de un `finally` puede ser cortada por una cancelación.

Verificado antes/después con el **mismo** fichero de tests
(`backend/tests/test_live_preview_release_order.py`) ejecutado contra el
código anterior y el nuevo: 3 de los 4 tests fallaban antes (incluido el
congelamiento del event loop: **5 ticks en 1 s** frente a ~100 ahora) y los
4 pasan ahora.

## 2. Instalación

`locust` **no** es una dependencia del backend (a propósito: no se añade a
`backend/pyproject.toml`, para no obligar a instalar gevent en el runtime de
producción). Dos formas de traerlo:

**A) Contenedor (lo usado para la ejecución de referencia).** No toca el host:

```bash
docker run --rm --network parking_default \
  -v D:/Parking/backend:/carga -w /carga locustio/locust \
  -f /carga/locustfile.py --headless --host http://parking-backend-1:8000 ...
```

**B) venv en el host** (útil para depurar con el navegador de Locust):

```bash
cd D:/Parking
python -m venv .venv-locust
.venv-locust/Scripts/pip install locust      # locust 2.46.7 con Python 3.13
.venv-locust/Scripts/locust -f backend/locustfile.py --host http://localhost:8000
```

## 3. Preflight

```bash
python backend/locust/preflight.py
# [OK  ] GET /health -> 200 {"status":"ok","version":"0.1.0"}
# [OK  ] POST /api/v1/auth/login (gestor.madrid@solidapp.es) -> 200
# [OK  ] GET /api/v1/parkings/11 -> 200
# [OK  ] POST /api/v1/tickets -> 201
# [OK  ] POST /api/v1/tickets/157/close -> 200
# [OK  ] GET /api/v1/parkings/11/events -> 200, 22 bytes en 2 s
# [OK  ] GET .../cameras/81/live -> 200, 16 frames (540092 bytes) en 8 s
# PREFLIGHT OK: el entorno responde.
```

## 4. Cómo se midió (metodología de la referencia)

1. **Instancia dedicada de carga**, sin `--reload`, para que los cambios de
   código de otros no reinicien el servidor bajo medición:

   ```bash
   docker run -d --name parking-carga --network parking_default \
     -v D:/Parking/backend:/app -w /app <env del compose> solidapp-backend:latest \
     sh -c "while true; do uvicorn app.main:app --host 0.0.0.0 --port 8000; \
             echo '--- worker caiu, reiniciando ---'; sleep 1; done"
   ```

   El bucle `while true` hace de supervisor: **relevanta el worker después
   del SIGSEGV del preview** (si no, la ejecución se quedaría a medias). En
   producción no hay supervisor: por eso el crash es un P0.

2. **Cámaras de carga**: la BD sembrada tiene una sola cámara con RTSP real
   (la 81). Como el backend sólo admite **un stream vivo por cámara** (409 si
   ya hay otro), se crean 9 cámaras temporales que apuntan al mismo RTSP:

   ```bash
   for i in 1 2 3 4 5 6 7 8 9; do
     curl -s -X POST http://localhost:8000/api/v1/parkings/11/cameras \
       -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d "{\"code\":\"CARGA-$i\",\"name\":\"Carga locust $i\",\"rtsp_url\":\"rtsp://parking-mediamtx:8554/cam1\"}"
   done
   # Limpiar al terminar (no hay endpoint de borrado de cámaras)
   docker exec parking-db-1 psql -U parking -d parking \
     -c "DELETE FROM cameras WHERE code LIKE 'CARGA-%';"
   ```

3. **Ejecución**: 6 usuarios virtuales (5 operadores + 1 visualizador) durante
   180 s, ramp rate 2/s.

4. **Tickets**: el escenario crea tickets reales (es el hot path que se quiere
   medir). Para limpiar:

   ```bash
   docker exec parking-db-1 psql -U parking -d parking \
     -c "DELETE FROM tickets WHERE origin = 'automatic' AND entry_at > now() - interval '1 day';"
   ```

## 5. La ejecución de referencia (números reales)

`backend/locust/reports/2026-10-21-referencia.json` (Locust) y
`2026-10-21-referencia.contexto.json` (contexto: fecha, host, usuarios,
cámaras, motivos de los fallos).

Comando (el que genera el informe):

```bash
docker run --rm --network parking_default \
  -v D:/Parking/backend:/carga -w /carga \
  -e "SOLIDAPP_CAMARA_IDS=81,154,155,156,157,158,159,160,161,162" \
  -e "SOLIDAPP_INFORME_CONTEXTO=/carga/locust/reports/2026-10-21-referencia.contexto.json" \
  locustio/locust -f /carga/locustfile.py --headless \
  --host http://parking-carga:8000 --users 6 --spawn-rate 2 --run-time 180s \
  --json-file /carga/locust/reports/2026-10-21-referencia
```

| Métrica | Peticiones | Fallos | p95 | Umbral SLO |
|---|---|---|---|---|
| `login` (POST) | 5 | 0 | **240 ms** | 1500 ms |
| `lectura_plazas` (GET) | 109 | 0 | **20 ms** | 300 ms |
| `lectura_tickets` (GET) | 75 | 0 | **18 ms** | 300 ms |
| `lectura_camaras` (GET) | 42 | 0 | **15 ms** | 300 ms |
| `ticket_crear` (POST) | 48 | 0 | **36 ms** | 500 ms |
| `ticket_cerrar` (POST) | 48 | 0 | **35 ms** | 1500 ms |
| `sse_mapa` (apertura) | 74 | 0 | **14 ms** | 1000 ms |
| `sse_mapa_primer_evento` | 74 | 0 | **0 ms** | 1500 ms |
| `preview_mjpeg` (apertura) | 8 | 0 | **31 ms** | 1000 ms |
| `preview_mjpeg_primer_frame` | 8 | 0 | **2 100 ms** | 3000 ms |
| Bytes por sesión de preview | — | — | 1,13 MB | ≥ 50 KB |
| Previews descartados con 409 | 0 | — | 0 | 0 |

**0 fallos en 491 peticiones, 0 cortes de stream y 0 previews descartados con
un 409**: el SLO se cumple entero (14 de 14 reglas). El contenedor de carga se
monitorizó durante los 180 s: **0 reinicios** (antes: 3 caídas del worker por
el crash P0).

> La regla `mjpeg_sin_409` es la que ata el P2 del preview al SLO: en el
> escenario de carga sólo hay **un** visualizador, así que cualquier 409 es un
> síntoma del P2 (la cámara seguía ocupada al reabrir), no una regla de
> negocio. Antes de corregirlo, esa métrica la pasaba el locustfile como
> "éxito" porque un 409 no es un fallo HTTP: el SLO no lo veía.

### El fixture del RTSP importa (y era lo que inflaba las cifras)

La fuente de QA hace push de un MP4 cuyo **keyframe está cada 250 frames**
(GOP de ~10 s). El primer frame del preview tiene que esperar al siguiente
keyframe, así que tardaba entre 1,2 y 8 s y varias sesiones se pasaban del
límite: con 10 cámaras fueron 2 fallos de 8 y con 3 cámaras **3** de 8
(peor: no era contención entre lectores, era el GOP).

Recreando el push con `-g 25` (keyframe cada segundo) el primer frame llega
en **1,7 s (p95)** y el preview queda **sin fallos**:

```bash
docker rm -f parking-rtsp-push
docker run -d --name parking-rtsp-push --network parking_default \
  -v "$TEMP/qa_long.mp4:/work/qa_long.mp4:ro" alpine:3.20 \
  sh -c "apk add --no-cache ffmpeg >/dev/null 2>&1 && exec ffmpeg -re \
    -stream_loop -1 -i /work/qa_long.mp4 -c:v libx264 -preset ultrafast \
    -tune zerolatency -pix_fmt yuv420p -g 25 -f rtsp -rtsp_transport tcp \
    rtsp://parking-mediamtx:8554/cam1"
```

Esto **nofalsea el SLO**: sólo quita un cuello de botella del *fixture*. El
límite real del producto no es la latencia del primer frame (depende del GOP
de la cámara real), sino que el stream **no se corte** (bytes medios por
sesión) y que el backend **no caiga** al cerrarlo.

## 6. El SLO

Definido en `backend/locust/slo.json` (fuente de verdad; este README no lo
duplica). Cada regla tiene `id`, `method`, `name`, `metrica`, `umbral`,
`min_muestras` y `motivo` (por qué ese umbral).

| Métrica | Significado |
|---|---|
| `percentil_ms` | Percentil (por defecto p95) del histograma de tiempos de respuesta. |
| `max_fallos` | Nº de peticiones fallidas de la métrica (0 = ni un fallo). |
| `min_bytes_medios` | Bytes medios por petición (detecta streams congelados). |
| `max_tasa_fallo` | Proporción de fallos (0.0 - 1.0). |
| `max_peticiones` | Nº de **ocurrencias** de la entrada. Sirve para lo que Locust cuenta como "éxito" pero que en realidad es un síntoma: los previews descartados con un 409 (la cámara ocupada) los cuenta el locustfile aparte, porque un 409 es una regla de negocio y no un fallo HTTP. Con esta métrica el SLO detecta una regresión del P2 del preview. |

El percentil se calcula **replicando el algoritmo de Locust**
(`calculate_response_time_percentile`) para que el número del verificador sea
exactamente el mismo que muestra la web de Locust.

Si una métrica **no aparece** en el informe o **no tiene muestras
suficientes**, la regla falla: un SLO que no se puede evaluar no se puede
"pasar". La excepción es `max_peticiones`: si la entrada no aparece es que
hubo **0 ocurrencias**, que es justo lo que la regla quiere ver.

### Encaje en CI

```bash
locust -f backend/locustfile.py --headless --host "$HOST" \
  --users 6 --spawn-rate 2 --run-time 180s --json-file informe.json
python backend/locust/check_slo.py --report informe.json   # exit 1 si no cumple
```

El job debe ser **nocturno o de fin de semana**: la ejecución de referencia
mide el backend de un entorno de QA, no un banco de pruebas, y el resultado
depende del hardware donde corre.

## 7. Decisiones de diseño (y por qué)

### 7.1 El login no se carga en bucle

`POST /api/v1/auth/login` tiene rate-limit por IP **y** por email
(`LoginRateLimiter`: 10 intentos por ventana de 300 s). Un escenario que haga
login en cada iteración se comería su propio 429 y mediría el rate-limit en vez
del backend. Por eso:

- el token se pide **una vez** y se reutiliza entre todos los usuarios
  virtuales (es lo que hace el cliente real: el login no es el hot path, el
  token dura 15 min);
- los logins "de escenario" consumen un **presupuesto** por ejecución
  (`SOLIDAPP_PRESUPUESTO_LOGINS`, 5 por defecto). Agotado el presupuesto, la
  tarea se salta y lo dice en el log, en vez de provocar un 429 artificial.

### 7.2 Los streams son infinitos: se leen acotado y se cierran

El SSE (`/parkings/{id}/events`) y el MJPEG (`/cameras/{id}/live`) no
terminan nunca. El cliente lee un número **acotado** de bytes durante una
ventana (`VENTANA_SSE_S` / `VENTANA_MJPEG_S`) y cierra la conexión
explícitamente. Si se esperase al final del stream, la carga se quedaría
colgada para siempre.

Cerrar es además obligatorio por el registro `live_streams`: si el cliente no
cierra, la sesión sigue "viva" (heartbeat) y el siguiente cliente recibe un
409 en vez de vídeo.

### 7.3 Lo que se mide

Locust mide por defecto el tiempo hasta la **cabecera** de la respuesta. En
un stream eso no dice nada del vídeo, así que el locustfile publica dos
métricas propias (`events.request.fire`):

| Entrada del informe | Qué mide |
|---|---|
| `sse_mapa` / `preview_mjpeg` | Apertura del stream (auth + cabeceras). |
| `sse_mapa_primer_evento` | Latencia hasta el primer evento SSE. |
| `preview_mjpeg_primer_frame` | Latencia hasta el primer frame JPEG. |

Además, el tamaño medio de la respuesta por sesión (`total_content_length`)
sirve para detectar un preview **congelado**: el usuario vería el modal
parado aunque no haya ningún error.

### 7.4 El SSE sólo se autentica por cabecera

El SSE usa `parking_context`, que es *header-only*: el `?token=` que anuncia
el docstring del endpoint devuelve **401**. El preview MJPEG sí acepta
`?token=` (usa un dep propio), que es lo que hace el `<img>` del frontend. Los
escenarios reflejan cada caso real.

### 7.5 Variables de entorno

| Variable | Defecto | Para qué |
|---|---|---|
| `SOLIDAPP_PARKING_ID` | `11` | Sucursal sobre la que se carga. |
| `SOLIDAPP_CAMARA_IDS` | `81` | Cámaras del escenario MJPEG (separadas por comas). Cada visualizador toma una distinta (el backend sólo admite **un** stream vivo por cámara: 409 si ya hay otro). **Se lee en runtime**, no al importar el módulo. Ojo: el nombre correcto es con **una R** (`CAMARA`); por compatibilidad se acepta también `SOLIDAPP_CAMERA_IDS` (dos R), que es el que leía el locustfile hasta el 2026-10-21 y hacía que la variable documentada no surtiera efecto. |
| `SOLIDAPP_VEHICLE_IDS` | `1,11,13` | Vehículos sembrados para el escenario de tickets. |
| `SOLIDAPP_VENTANA_SSE_S` | `2` | Segundos que se lee el stream SSE en cada sesión. |
| `SOLIDAPP_VENTANA_MJPEG_S` | `8` | Segundos que se lee el stream MJPEG en cada sesión. |
| `SOLIDAPP_TIMEOUT_LECTURA_S` | `8` | Timeout de lectura del socket (cubre el arranque del preview). |
| `SOLIDAPP_PRESUPUESTO_LOGINS` | `5` | Nº máximo de **logins reales** por ejecución. |
| `SOLIDAPP_INFORME_CONTEXTO` | — | Ruta donde escribir el contexto de la ejecución. |

## 8. Avisos del entorno de desarrollo

- El contenedor del backend monta `./backend` en `/app` y arranca uvicorn con
  `--reload`: **cualquier fichero nuevo o modificado bajo `backend/` reinicia
  el backend**. Durante una medición de carga eso importa: no escribas nada
  en `backend/` mientras corre el escenario (el propio informe se escribe
  ahí, al final de la ejecución).
- Con un stream SSE o MJPEG abierto, ese reinicio se queda colgado: es el bug
  de T-06 (el shutdown ordenado de uvicorn espera a que terminen las
  conexiones, y un stream infinito no termina nunca).
- La carpeta `backend/locust/` **no lleva `__init__.py`** a propósito: si lo
  llevara, el paquete `locust` de la carpeta ensombrecería a la librería
  `locust` cuando el CLI añade el directorio del locustfile al `sys.path`.
