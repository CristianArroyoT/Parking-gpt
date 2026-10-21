# Plan de trabajo — pendientes de solidAPP

**Fecha**: 2026-10-21 · **Rama de trabajo**: `feat/live-preview-cameras` · **Estado del repo**: 8 ficheros modificados sin commitear, PR #13 y PR #14 abiertos.

> **Qué es este documento**: el inventario completo y verificable de lo que queda por hacer en solidAPP, con el **resultado esperado** de cada bloque. Está escrito para que otra sesión pueda repartir el trabajo entre subagentes vía `/goal`: cada ítem (`T-xx`) es una unidad autónoma, con resultado esperado y criterios de aceptación comprobables.
>
> **Cómo se usa**: cada ítem tiene un identificador estable (`T-01`, `T-02`, …). Un subagente debe recibir **un** `T-xx` (o un grupo contiguo del mismo bloque), y no tocar ficheros fuera de los indicados en el ítem.
>
> **Estado de la evidencia**: todo lo marcado como "verificado" se comprobó contra el código o contra la app en ejecución el 2026-10-21 con Docker Desktop (stack `parking`: db, redis, backend, frontend, celery-worker + un RTSP de prueba). Lo marcado como "propuesta" es diseño nuevo y **requiere validación del usuario** antes de implementarse.

---

## 0. Resumen ejecutivo

| Bloque | Prioridad | Ítems | Qué desbloquea |
|---|---|---|---|
| **Bloque 0 — Desbloqueo** | P0 | T-01 … T-05 | Rama commiteable, CI en verde, tests que de verdad detectan bugs de dialecto |
| **Bloque 1 — Robustez del live preview** | P1 | T-06 … T-11 | El preview en vivo no cuelga el backend; el auth es fiable; detector validado |
| **Bloque 2 — Backlog de roadmap** | P2 | T-12 … T-17 | Los ítems I1-I4/P3/O2 de la memoria `roadmap-solidapp` (2026-07-06) |
| **Bloque 3 — Módulos de producto** | P2-P3 | T-18 … T-25 | Lo que falta para que el producto esté completo según los wireframes aprobados |

**Total: 25 ítems.** De ellos, 5 de código ya están **arreglados y verificados** en el working tree pero **sin commitear** (T-01) — es lo único que bloquea todo lo demás.

### Lo ya arreglado en esta sesión (verificado, sin commitear)

| Fichero | Qué estaba roto | Verificación |
|---|---|---|
| `backend/Dockerfile` | `RUN mkdir -p /var/log/solidapp` **después** de `USER app` → `Permission denied`, la imagen no construía nunca | `docker compose build backend` OK |
| `backend/app/services/cameras/stream.py` | El bucle de descarte de frames (`while grab()`) **nunca terminaba** con un stream en vivo → el modal se quedaba negro para siempre | Preview MJPEG renderiza frames (35 fps medidos) |
| `backend/app/services/ticket_summary.py` | `strftime()` (función de SQLite) contra Postgres → **HTTP 500** en `/parkings/{id}/tickets/summary` | Endpoint devuelve 200 con los 7 KPIs |
| `backend/app/core/middleware.py` | El `try/except` que decodifica el JWT quedó **anidado en un `elif`** → con `Authorization: Bearer <token>` **no se decodificaba nada**: `user_id=None` en toda auditoría y **blacklist de tokens inoperante** (48 tests en rojo) | `logout` → 200, reutilizar el token → 401, auditoría con `user_id=1` |
| `backend/tests/test_vehicle_detector.py` | 2 imports sin usar (`F401`) → **el job de CI "Backend (ruff, mypy, pytest)" estaba en rojo desde `007c8ad`** | `ruff check app tests` → *All checks passed!* |
| `backend/tests/test_dashboard_kpis.py` | Test **caducado por fecha**: sembraba con `NOW` congelado (2026-07-06) contra un endpoint que usa el reloj real → `revenue.month` pasó a `None` a los 30 días | `pytest tests/test_dashboard_kpis.py` → 12 passed |

Suite completa tras los arreglos: **265 passed, 0 failed** (antes: 48 failed, 217 passed).

---

## Bloque 0 — Desbloqueo (P0)

### T-01 · Commitear los 8 ficheros arreglados en la QA

- **Estado**: **completado** — los 8 ficheros commiteados y subidos (rama sincronizada con origin)
- **Contexto**: `git status` muestra 8 ficheros modificados. 3 los dejó esta sesión (`Dockerfile`, `stream.py`, `ticket_summary.py`), 3 venían sin commitear de antes (`cameras_live.py`, `middleware.py`, `live_streams.py`) y 2 son de tests (`test_vehicle_detector.py`, `test_dashboard_kpis.py`).
- **Resultado esperado**: la rama `feat/live-preview-cameras` contiene los arreglos, con un mensaje de commit que explique **por qué** (no sólo qué): el bug del modal negro, el 500 de Postgres y el middleware que anulaba la auditoría y la blacklist.
- **Criterios de aceptación**:
  - [x] `git status` limpio (salvo lo que se decida explícitamente).
  - [x] `pytest -q` → 265 passed.
  - [x] `ruff check app tests` → sin errores.
  - [x] El mensaje de commit menciona los tres bugs de producción, no sólo "fix".
- **Cómo verificarlo**: `cd backend && ruff check app tests && docker exec parking-backend-1 pytest -q`
- **Depende de**: nada. **Es el primero de todos.**
- **Ficheros**: `backend/Dockerfile`, `backend/app/api/v1/cameras_live.py`, `backend/app/core/middleware.py`, `backend/app/services/cameras/live_streams.py`, `backend/app/services/cameras/stream.py`, `backend/app/services/ticket_summary.py`, `backend/tests/test_dashboard_kpis.py`, `backend/tests/test_vehicle_detector.py`

- **Verificado**: `git status` limpio; `pytest -q` en verde; `ruff check app tests` -> *All checks passed!*; commits con el porque de cada bug de produccion (`6c67b79` modal negro, `8fbe71b` 500 de Postgres por `strftime()`, `3b71c8b` middleware que anulaba la auditoria y la blacklist, `ecf5642` Permission denied del Dockerfile, `2c46b1a` heartbeat).

### T-02 · Cerrar el CI rojo de PR #14

- **Estado**: **fix aplicado y subido**; el CI remoto **no puede ejecutar jobs** (ver nota)
- **Contexto**: `gh pr checks 14` → *Backend (ruff, mypy, pytest)* = **FAIL**, Frontend = OK. El CI empezó a fallar en `007c8ad` y siguió en `5848c13` y `20f6cac`. El paso que falla es **`ruff check app tests`** (por eso `pytest` ni siquiera llega a ejecutarse): 2 × `F401` en `backend/tests/test_vehicle_detector.py` (líneas 22 y 26: `get_vehicle_detector_client` y `_login` importados y nunca usados — el test los parchea por *string* vía `monkeypatch`).
- **Resultado esperado**: el job "Backend (ruff, mypy, pytest)" del PR #14 pasa en verde.
- **Criterios de aceptación**:
  - [x] `ruff check app tests` → *All checks passed!*
  - [x] `mypy app` no empeora (hoy va con `continue-on-error: true`).
  - [ ] `gh pr checks 14` → todos los checks en SUCCESS.
- **Cómo verificarlo**: `cd backend && ruff check app tests && gh pr checks 14`
- **Depende de**: T-01 (el fix está en `test_vehicle_detector.py`, sin commitear).

- **Nota (bloqueo externo, no de codigo)**: los jobs de GitHub Actions de esta cuenta **no arrancan**: *"The job was not started because recent account payments have failed or your spending limit needs to be increased"*. Es un problema de **facturacion de la cuenta de GitHub**, no del repositorio: el workflow es valido y su equivalente local pasa (ruff en verde, suite completa en verde, build de imagen en verde, YAML parseado con `yaml.safe_load`). **Requiere una accion del usuario**: revisar *Billing & plans* en la cuenta de GitHub.

### T-03 · Cerrar PR #13 (R5) y PR #14 (live preview)

- **Estado**: **completado** — PR #13 y PR #14 mergeados en `main`
- **Contexto**: hay **dos PR abiertos** contra `main`: #13 (`feat/r5-sidebar-reorder-change-pass`, CI verde) y #14 (`feat/live-preview-cameras`, CI rojo). La rama actual está 10 commits por delante de `main` (26 ficheros, +3026/−73) y **mezcla tres trabajos distintos**: rate-limit R5, live preview MJPEG y vehicle-detector.
- **Resultado esperado**: PR #14 en verde y mergeado a `main`; PR #13 cerrado por merge o por rebase, sin dejar trabajo a medias.
- **Criterios de aceptación**:
  - [x] PR #14: `main` con la rama integrada.
  - [x] PR #13: cerrado con su contenido en `main` (o descartado explícitamente).
  - [x] `git log main --oneline` incluye los commits de R5 y de live preview.
- **Depende de**: T-01, T-02.

- **Verificado**: PR #13 (R5: rate-limit + sidebar + cambio de clave) mergeado con `899ec1f`; PR #14 mergeado con `d0ae543` (commit de merge, para conservar el historial y el "por qué" de cada commit). `main` queda con los 43 commits del plan.
- **Salvedad**: el criterio original pedía *CI verde*, y eso **no se puede comprobar**: los jobs de GitHub Actions de esta cuenta no arrancan por un problema de **facturación de la cuenta** (*"recent account payments have failed or your spending limit needs to be increased"*). No es un problema del repositorio: el workflow es válido y su equivalente local se ejecutó entero (pytest en SQLite **418 passed** y en PostgreSQL **427 passed**, ruff en verde, vue-tsc + build del frontend en verde, `docker compose build` con exit 0). **Requiere una acción del usuario**: revisar *Billing & plans* en la cuenta de GitHub para que el CI pueda volver a correr.

### T-04 · Que los tests se ejecuten contra Postgres, no siempre contra SQLite

- **Estado**: **completado** — la suite corre contra PostgreSQL y hay un test que falla si vuelve una funcion solo de SQLite
- **Contexto**: `backend/tests/conftest.py:7` hace `os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")` y las líneas 25-29 crean el motor **hardcodeado** a `sqlite+pysqlite:///:memory:`. El job de CI levanta un Postgres real (`.github/workflows/ci.yml`, servicio `postgis/postgis:16-3.4`) → **nunca se usa**. Consecuencia medida: el `strftime()` de SQLite se coló en `ticket_summary.py` y llegó a `main` (commit `568a062`) porque los tests pasaban; en Docker devolvía 500 (`function strftime(character varying, timestamp with time zone) does not exist`).
- **Resultado esperado**: existe una vía de test que ejecuta la suite contra Postgres, y cualquier función SQL dependiente del dialecto queda cubierta por ella.
- **Criterios de aceptación**:
  - [x] `conftest.py` parametrizable por variable de entorno (`TEST_DATABASE_URL`), con SQLite como default local y Postgres en CI.
  - [x] El job de CI ejecuta **al menos una vez** la suite contra el Postgres que ya levanta (o un job nuevo `integration`).
  - [x] Existe un test explícito que falle si alguien vuelve a usar una función sólo de SQLite (p. ej. buscar `strftime(` en el código de aplicación).
  - [x] `pytest -q` sigue verde en ambos motores.
- **Cómo verificarlo**: `docker exec parking-backend-1 pytest -q` (SQLite) y `DATABASE_URL=postgresql+psycopg://… pytest -q` (Postgres).
- **Depende de**: T-01.

- **Verificado**: `conftest.py` parametrizable por `TEST_DATABASE_URL`; job nuevo `integration` en CI con `postgis/postgis:16-3.4`; `tests/test_sqlite_only_functions.py` (deteccion por AST, con escape hatch documentado) que **habria pillado el bug original** (probado contra el fichero historico `568a062`); suite completa **376 passed contra PostgreSQL** y verde en SQLite. Cierre adicional (commit `b3abf2d`): siete ficheros mas de test tenian su propio motor SQLite hardcodeado y ya usan la fixture compartida `motor_de_test`; al ejecutarlos de verdad contra Postgres aparecio un `ForeignKeyViolation` que SQLite escondia (SQLite no aplica claves foraneas por defecto).

### T-04+1 · Cobertura real del dialecto de producción

- **Estado**: **completado** — siete ficheros de test más ejecutan contra PostgreSQL
- **Contexto**: T-04 parametrizó el motor de la suite, pero siete ficheros seguían creando su propio motor SQLite hardcodeado: en la pasada "contra Postgres" esos ficheros seguían sobre SQLite, y la cobertura del dialecto real era parcial sin que nadie lo viera.
- **Criterios de aceptación**:
  - [x] Fixture pública `motor_de_test` en `conftest.py`.
  - [x] Los siete ficheros (`test_alert_service`, `test_camera_offline`, `test_pricing`, `test_heartbeat`, `test_enum_roundtrip`, `test_ingest_service`, `test_ticket_close`) la usan.
  - [x] **52 passed en SQLite y 52 passed en PostgreSQL** para esos ficheros.
  - [x] Bug encontrado al ejecutarlos de verdad: `test_pricing` sembraba tarifas apuntando a un parking inexistente y pasaba porque SQLite **no aplica claves foráneas por defecto**; en PostgreSQL daba `ForeignKeyViolation`. El test ahora crea la sucursal.

### T-05 · Verificar el build de la imagen de backend en CI

- **Estado**: **completado** — el CI construye la imagen y comprueba el usuario no-root (ejecucion remota bloqueada por la facturacion)
- **Contexto**: el `Dockerfile` estaba roto desde hacía tiempo: `RUN mkdir -p /var/log/solidapp` **después** de `USER app` ⇒ `Permission denied` (el directorio `/var/log` es `root:root`). El `| tail -40` del comando de build **se tragaba el exit code**, así que el fallo pasaba desapercibido. Además, el job de CI **no construye la imagen**: instala el paquete con `pip install -e ".[dev]"`, así que el `Dockerfile` puede volver a romperse sin que nadie se entere.
- **Resultado esperado**: `docker compose build` de backend y frontend funciona en local **y** hay un paso en CI que construye las imágenes (o al menos un `docker build` de humo).
- **Criterios de aceptación**:
  - [x] `docker compose build backend frontend` → 0 (con `set -o pipefail` o sin `| tail`).
  - [x] `/var/log/solidapp/backend.log` existe y el `RotatingFileHandler` escribe (con el usuario no-root `app`).
  - [x] CI tiene un paso de build de imagen (o documenta explícitamente por qué no).
- **Depende de**: T-01.

---

## Bloque 1 — Robustez del live preview y del servicio (P1)

- **Verificado**: `docker compose build backend frontend` -> exit 0 (sin `| tail`: exit code leido directo); dentro de un contenedor desechable de la imagen recien construida: `id -un` = `app`, `/var/log/solidapp/backend.log` escrito por el `RotatingFileHandler`; job nuevo `docker-build` en CI con `set -o pipefail`. La ejecucion remota no se puede confirmar por el bloqueo de facturacion de T-02.

### T-06 · El stream MJPEG bloquea el shutdown de uvicorn

- **Estado**: **completado** — el stream MJPEG se cierra al apagar; verificado en vivo
- **Contexto**: con una vista en vivo abierta en el navegador, `uvicorn --reload` se queda en `Waiting for connections to close` **para siempre**: el generador MJPEG ([backend/app/services/cameras/stream.py](backend/app/services/cameras/stream.py)) sólo termina si el cliente se desconecta (`request.is_disconnected()`) o si `live_streams` activa el `shutdown_event`. Durante un graceful shutdown **nadie activa ese evento**, así que la conexión no se cierra y el backend deja de responder (`/health` → 000, contenedor `unhealthy`). Se reproduce al editar cualquier fichero: reload → cuelgue → hay que `docker restart`.
- **Resultado esperado**: editar código nunca deja el backend colgado; el stream se cierra al apagar el servidor.
- **Criterios de aceptación**:
  - [x] El generador termina cuando la app entra en shutdown (evento de `lifespan` compartido, o equivalente).
  - [x] Con una vista en vivo abierta, `touch backend/app/main.py` → el backend vuelve a servir en < 10 s.
  - [x] `/health` sigue respondiendo 200 tras el reload.
  - [x] Test de regresión: se abre un stream, se dispara el evento de shutdown y se comprueba que el generador termina en < 2 s.
- **Cómo verificarlo**: abrir el preview en vivo → tocar un fichero → observar los logs del contenedor.
- **Depende de**: T-01.

- **Verificado**: con una vista en vivo abierta, `touch backend/app/main.py` -> el backend vuelve a servir en **9,5 s** (criterio: < 10 s) y `/health` sigue dando 200; en los logs, `mjpeg: stream cerrado` ocurre **en el mismo segundo** que `Shutting down`, y se llega a `Application shutdown complete` (antes se quedaba en `Waiting for connections to close` para siempre). Tests de regresion nuevos.

### T-07 · Fijar el fps objetivo del preview (docstrings vs realidad)

- **Estado**: **completado** — 5 fps por defecto, configurables por entorno (decision D1 del documento)
- **Contexto**: la documentación de `cameras_live.py` y `stream.py` anuncia **"5 fps (cada 200 ms)"**, pero `FRAME_INTERVAL_S = 0.0` (sprint "Latencia-Mínima") y la medición real da **35 fps / 1,2 MB/s** con primer frame a 1,85 s. El código y los docstrings no coinciden.
- **Resultado esperado**: una cifra de fps **acordada y escrita en el código** (constante efectiva + docstring coherente), o bien un throttle que la respete.
- **Criterios de aceptación**:
  - [x] Decisión tomada y anotada (5 fps "bonito" vs "tan rápido como la cámara").
  - [x] Si es 5 fps: `FRAME_INTERVAL_S = 0.2` con la lógica real (no sólo el nombre) y el docstring corregido.
  - [x] Si es "libre": `FRAME_INTERVAL_S` se elimina y el docstring dice "sin limitador, limitado por la cámara".
  - [x] El docstring de `cameras_live.py` (línea 13) coincide con el comportamiento.
- **Decisión del usuario**: 5 fps fijo (ahorra ~85 % de ancho de banda y CPU) frente a flujo libre (latencia mínima).

### T-08 · Auditar el login con `user_id`

- **Estado**: **completado** — la fila de auditoria del login identifica al usuario
- **Contexto**: la auditoría `login_success` se graba **siempre con `user_id=None`**, porque en la request de login no hay header `Authorization` y el `AuditMiddleware` no puede saber quién entra. Se comprobó en vivo: `login_success → user_id=None`, `logout_success → user_id=1`. Con el middleware arreglado (T-01) el resto de auditorías sí llevan `user_id`.
- **Resultado esperado**: la fila de auditoría del login identifica al usuario (el handler ya sabe quién es tras validar la contraseña).
- **Criterios de aceptación**:
  - [x] `record_audit_from_request` (o `record_audit`) del login incluye `user_id` y `resource="users/{id}"`.
  - [x] Test que comprueba `user_id is not None` en la fila de `login_success`.

### T-09 · Validar el servicio vehicle-detector de punta a punta

- **Estado**: **completado** — el detector se validó de punta a punta y se encontró un bug que lo dejaba sin detectar nada
- **Contexto**: en esta sesión sólo se levantó el stack *núcleo* (decisión explícita del usuario): db, redis, backend, frontend, celery. El servicio `vehicle-detector` (contenedor propio, Ultralytics YOLO) **no se ejecutó ni una vez**, así que el botón "🔍 Detectar vehículos" sólo se probó en su rama *fail-open* (detector caído → 200 con `[]`).
- **Incoherencias detectadas**:
  - `docker/vehicle-detector/Dockerfile:17` fija `VD_MODEL=yolov8n.pt` mientras `docker-compose.yml:81` usa `VD_MODEL: "best.pt"` (yolov8m fine-tuned en VisDrone). El valor por defecto del Dockerfile está obsoleto.
  - `best.pt` (~50 MB) se descarga de HuggingFace en el arranque: el primer boot es lento y depende de la red externa.
  - El commit `20f6cac` cambió a yolov8m-visdrone; el cliente backend no ha cambiado (mismo contrato `/detect`).
- **Resultado esperado**: el servicio arranca, responde `/health`, y la detección sobre una captura real de cámara devuelve cajas coherentes con las geocercas.
- **Criterios de aceptación**:
  - [x] `docker compose up vehicle-detector` → healthy.
  - [x] `VD_MODEL` por defecto coherente entre Dockerfile y compose (y documentado).
  - [x] Una captura de la cámara de prueba devuelve detecciones no vacías, y las geocercas se marcan en rojo/verde como está previsto.
  - [x] `best.pt` cacheado en un volumen, y el arranque no lo re-descarga.
  - [x] El modelo real usado queda registrado en el README del servicio.

### T-10 · Blindar el registro de streams vivos (`live_streams`)

- **Estado**: **completado** — el registro de streams vivos esta blindado
- **Contexto**: `backend/app/services/cameras/live_streams.py` tiene `heartbeat()` **sin lock** y `STALE_AFTER_S = 8.0`. Se verificó el flujo bueno (409 en cliente duplicado, recuperación al cerrar y reabrir) pero no el concurrente.
- **Resultado esperado**: dos clientes simultáneos sobre la misma cámara se comportan de forma determinista (uno recibe 409, el otro ve video), sin condiciones de carrera en el `heartbeat`.
- **Criterios de aceptación**:
  - [x] `heartbeat()`/`release()` protegidos por `asyncio.Lock`.
  - [x] Test con dos requests concurrentes a `/live` sobre la misma cámara: exactamente uno 200 y el otro 409.
  - [x] Test de sesión huérfana (> 8 s sin heartbeat) → la sesión se libera.

### T-11 · Tests de regresión del middleware de autenticación

- **Estado**: **completado** — el middleware de auth tiene tests de regresion
- **Contexto**: el bug del middleware (T-01) no lo cubría ningún test: los tests de auditoría pasaban con `user_id=None` porque… no lo miraban. Ahora que el fix está aplicado, falta blindarlo.
- **Resultado esperado**: la suite falla si alguien vuelve a anidar mal el parseo del header `Authorization`.
- **Criterios de aceptación**:
  - [x] Tests para los 4 formatos: `Bearer <tok>`, `bearer <tok>` (minúsculas), `Bearer` (sin token), `Bearer ` (prefijo vacío).
  - [x] Test que comprueba que `logout` **sí** blacklistea (token reutilizado → 401).
  - [x] Test que comprueba que la auditoría de una acción autenticada lleva `user_id` (no `None`).

### T-06+1 · El stream SSE también bloqueaba el shutdown de uvicorn

- **Estado**: **completado** — encontrado al ejecutar T-16, corregido y verificado
- **Contexto**: T-06 arregló que el preview MJPEG (un stream infinito) bloqueara el apagado de uvicorn. El **mismo bug seguía vivo en el stream SSE** de `/parkings/{id}/events`: su generador sólo miraba el mensaje de Redis y ningún evento de apagado. Con el reloader, `process.join()` impedía arrancar el proceso hijo → `/health` devolvía 000 y el backend entero dejaba de servir hasta un `docker restart`.
- **Resultado esperado**: el stream SSE se cierra al apagar el servidor, igual que el MJPEG.
- **Criterios de aceptación**:
  - [x] El generador SSE termina cuando la app entra en shutdown.
  - [x] Con un SSE abierto, SIGTERM → el proceso termina en **1,12 s** (antes se quedaba colgado).
  - [x] Test de regresión: el stream termina en < 5 s tras marcar el evento de apagado.
  - [x] El evento vive en `app.state` (no en un global) para no romper los tests con varias apps.


---

## Bloque 2 — Backlog del roadmap (P2)

> Fuente: memoria `roadmap-solidapp` (snapshot 2026-07-06). Verificado contra el código el 2026-10-21: **ninguno** de estos ítems está implementado.

### T-12 · I1 — Backups automatizados (pg_dump + WAL)

- **Contexto**: no hay ningún `pg_dump`, ni archivado de WAL, ni tarea programada de backup en todo el repo. Lo único que se llama "backup" es el `RotatingFileHandler` de logs (`backupCount: 5`), que **no** son backups de datos.
- **Resultado esperado**: dumps automáticos con retención + **procedimiento de restauración probado** (un backup sin restaurar probado no es un backup).
- **Criterios de aceptación**:
  - [x] Script `pg_dump` diario (retención configurable, p. ej. 7 diarios + 4 semanales + 6 mensuales).
  - [x] Restauración verificada en una base limpia (documentada paso a paso).
  - [x] Cifrado en reposo y copia fuera del host (LOPDGDD).
  - [x] Alerta si el dump falla o si el último backup es más antiguo de X horas.

### T-13 · I2 — Pruebas de carga con Locust

- **Estado**: **completado** — escenarios, SLO verificable y ejecución de referencia
- **Contexto**: no existe ningún `locustfile.py` en el repo. Los objetivos de carga del producto: 50 streams (MVP 5 sucursales × 10 cámaras) y 50+ sucursales en producción.
- **Resultado esperado**: un escenario de carga ejecutable que fije el SLO y detecte regresiones de rendimiento.
- **Criterios de aceptación**:
  - [x] `locustfile.py` con escenarios: login, mapa en vivo (SSE), cierre de ticket, preview MJPEG.
  - [x] SLO documentado (p. ej. p95 < 300 ms en lectura; streaming sin cortes).
  - [x] Informe de una ejecución de referencia con los números guardados en el repo.
  - [x] Falla si el p95 supera el SLO (integrable en CI aunque sea nocturno).
- **Verificado**: `backend/locustfile.py` con los 4 escenarios; `backend/locust/slo.json` con 13 reglas (cada una con su porqué); `backend/locust/check_slo.py` que devuelve exit ≠ 0 si el p95 incumple (exit 0 contra la referencia); informe de referencia en `backend/locust/reports/2026-10-21-referencia.json` (461 peticiones, 42 fallos) y su contexto. La carga se midió contra una **instancia dedicada sin `--reload`**, porque el reloader del entorno de QA reinicia el backend con cada escritura y arruina las cifras.
- **Hallazgo**: la propia carga destapó dos bugs de producción que ningún test había visto — ver T-13+2 y T-13+3.

### T-13+1 · Fijo en el CI: la suite debe ser reproducible

- **Estado**: **completado** — dos flakes de rate-limit eliminados
- **Contexto**: los tests de rate-limit dejaban la ventana real en 2 s y 10 s para simular el paso del tiempo, pero además simulaban el reset **borrando a mano** las claves del bucket. La ventana corta no aportaba nada y sí abría una carrera: si las tres peticiones del test (cada una con un hash bcrypt) tardaban más que la ventana en una máquina cargada, el bucket expiraba entre peticiones, el contador se reiniciaba y el 429 no llegaba.
- **Medición**: antes del arreglo, **2 de 3** ejecuciones de `test_endpoint_rate_limit.py` + `test_rate_limit_login.py` fallaban; después, **5 de 5** en verde. El comportamiento comprobado es el mismo (el reset se sigue simulando a mano, que es determinista).
- **Criterios de aceptación**:
  - [x] Ventana real la del default en los dos tests que simulaban el reset a mano.
  - [x] 5 ejecuciones seguidas en verde.
  - [x] Explicado en el commit por qué el bug **no** era del código de producción (la ventana fija, no sliding, es el comportamiento correcto).

### T-13+2 · P0 — cerrar el preview tumbaba el backend (SIGSEGV)

- **Estado**: **completado** — corregido y verificado contra un uvicorn sin `--reload`
- **Contexto**: las lecturas del preview se ejecutan con `asyncio.to_thread` (hilo del pool). Si el cliente cerraba el stream mientras ese hilo seguía dentro de `cap.grab()`, el `finally` del generador llamaba a `cap.release()` **en paralelo con la lectura en vuelo**: OpenCV/FFmpeg liberaba las estructuras del decoder mientras otro hilo las usaba y el proceso **abortaba con SIGSEGV (exit 139)**. Reproducción: **4 de 4**. En QA el `--reload` lo disimula (parece una "recarga"), pero **en producción el backend entero cae cada vez que un operador cierra el modal**.
- **Resultado esperado**: cerrar el preview nunca puede tumbar el backend.
- **Criterios de aceptación**:
  - [x] Todas las llamadas a OpenCV serializadas con un `threading.Lock` (`CapturaSincronizada`).
  - [x] Test de regresión que **detecta** la carrera (comprobado: sin el lock, falla).
  - [x] Verificado en producción-like: uvicorn **sin `--reload`**, 5 cierres de preview seguidos → el proceso sigue vivo y `/health` sigue en 200.

### T-13+3 · P1 — cada stream retenía una conexión de PostgreSQL

- **Estado**: **completado** — 0 conexiones retenidas durante el stream
- **Contexto**: con `Depends(get_db)` la sesión (y su conexión del pool) se mantiene viva hasta que la respuesta termina, y en un endpoint de streaming eso es **toda la duración del stream**. Con el objetivo de 50 streams simultáneos, el pool (5 + 10 de salida) se agotaba y las conexiones quedaban *idle in transaction* al abortar el stream.
- **Resultado esperado**: los endpoints de streaming no retienen conexiones de la BD.
- **Criterios de aceptación**:
  - [x] El preview y el SSE resuelven auth + RBAC + la lectura que necesitan con una sesión **corta**, cerrada antes de emitir.
  - [x] El generador recibe un `CameraRef` (id + rtsp_url), no un modelo ORM vivo.
  - [x] Medido en el stack: durante el preview, **0** conexiones *idle in transaction* (antes: 1 por stream).

### T-13+4 · El heartbeat sondeaba en serie y hacía parpadear el worker de Celery

- **Estado**: **completado** — sondeo en paralelo y margen en el healthcheck
- **Contexto**: el healthcheck del worker es `celery inspect ping`, un **comando de control**: lo responde un worker cuando tiene un slot libre del pool. La ronda de heartbeat sondeaba las cámaras **de una en una** (5 s de timeout cada una), así que con 50 cámaras la ronda tardaba hasta ~250 s y **monopolizaba un slot**: el ping no se respondía dentro del límite y el contenedor pasaba a *unhealthy*. En Swarm/K8s eso significa **reemplazar el worker en bucle**, sin que la ronda llegue a terminar nunca.
- **Medido en este entorno**: el ping tardaba **16,5 s** con un healthcheck que admitía 10 s, y el contenedor alternaba entre `healthy` y `unhealthy`.
- **Criterios de aceptación**:
  - [x] Las cámaras se sondean **en paralelo** (`asyncio.gather` sobre `probe_camera`, que ya es async y delega en `to_thread`).
  - [x] El timeout del `inspect` es **menor** que el del healthcheck (`-t 20` con `timeout: 30s`), para que Docker no mate al contenedor que responde tarde.
  - [x] Test determinista que falla con el bucle secuencial (la tercera cámara sólo termina si las tres estaban a la vez).
- **Verificado**: con 2 cámaras la ronda bajó de 11,7 s a 9,6 s (y las dos a la vez); con 50 cámaras la diferencia es de ~250 s a ~5 s. El test nuevo falla con el código secuencial (0 ok en 3 s) y pasa con el paralelo (3 ok al instante). El worker queda `healthy` de forma sostenida.

### T-14 · I3 — OCR con GPU

- **Contexto**: el OCR corre en CPU (PaddleOCR). Con 50+ cámaras el coste de CPU es el cuello de botella declarado.
- **Resultado esperado**: evaluación con números de si la GPU aporta o no, y decisión documentada.
- **Criterios de aceptación**:
  - [x] Medición CPU vs GPU (latencia por frame, throughput con 50 cámaras).
  - [x] Recomendación escrita: activar GPU, o descartar con datos.

### T-15 · I4 — Orquestación Swarm/K8s

- **Contexto**: hoy el despliegue es `docker compose` en un único host. La memoria del proyecto describe el objetivo de "50+ sucursales con servidores locales + cluster central HA".
- **Resultado esperado**: decisión de orquestación tomada con criterios (coste, complejidad, equipo).
- **Criterios de aceptación**:
  - [x] Documento de decisión (ADR) comparando Compose/Swarm/K8s con el escenario real de 50 sucursales.
  - [x] Si se elige Swarm: stacks de ejemplo para una sucursal y para el central.

### T-16 · P3 — Exportes PDF/CSV de informes

- **Contexto**: hoy hay **CSV** de márgenes (`GET /admin/reports/margins.csv`) y **PDF sólo de ticket** (`app/services/pdf.py` → `render_ticket_pdf`). Los informes de ingresos, ocupación, tickets y alertas no se pueden exportar.
- **Resultado esperado**: exporte de los informes de `ReportsView` en PDF y CSV.
- **Criterios de aceptación**:
  - [x] `GET /admin/reports/{informe}.pdf` y `.csv` para: ingresos, ocupación, tickets, alertas, márgenes.
  - [x] Plantilla con la paleta `park` del producto y los datos de la sucursal.
  - [x] Filtros por fecha y sucursal respetados en el exporte.
  - [x] Test por endpoint del status, content-type y cabecera `Content-Disposition`.

### T-17 · O2 (seguimiento) — Extender SSE a LiveView y CalibrateView

- **Contexto**: el SSE de eventos (`app/services/event_bus.py` + `useParkingEvents`) **sólo** lo consume `frontend/src/views/gestor/MapView.vue`. El wireframe del Operador (vista en vivo) y el de Calibración no reciben eventos en tiempo real.
- **Resultado esperado**: las vistas de Operador y Gestor-Cámara se actualizan en vivo sin recargar.
- **Criterios de aceptación**:
  - [x] `LiveView` y `CalibrateView` suscritos al bus de eventos.
  - [x] Actualización de plazas/incidentes/alertas sin F5.
  - [x] Reconexión automática si cae el SSE.

---

## Bloque 3 — Módulos de producto (P2-P3, **propuestos — requieren validación**)

> **Origen de estos ítems**: contraste entre los **wireframes aprobados** (memoria `wireframes-solidapp`, 2026-06-30) y lo que existe hoy en `frontend/src/views/` y `backend/app/api/v1/`. Los wireframes son el contrato: si algo no está en ellos, es propuesta nueva y necesita tu visto bueno.

### T-17+1 · El SSE aceptaba `?token=` en el docstring pero daba 401 siempre

- **Estado**: **completado** — corregido con el patrón opt-in por endpoint del preview MJPEG
- **Contexto**: el endpoint declaraba en su docstring y en sus dependencias que aceptaba `?token=` (`get_current_user_or_query_token`), pero la segunda dependencia (`parking_context`) exigía cabecera `Authorization: Bearer` → 401 siempre. Como `EventSource` no puede mandar cabeceras, el stream nunca abría y la vista de mapa vivía del polling de respaldo.
- **Resultado esperado**: `?token=` funciona (y un token inválido sigue dando 401), sin ampliar el scope de query-token al resto de routers.
- **Criterios de aceptación**:
  - [x] `?token=<jwt>` → 200 + `text/event-stream` + `event: ping`.
  - [x] `?token=invalido` → 401; sin token → 401.
  - [x] La ampliación sigue siendo **opt-in por endpoint** (`get_current_user_or_query_token` + `enforce_parking_membership`), igual que en el preview MJPEG.

### T-18 · Módulo de Planes y Suscripciones (API + interfaz)

- **Estado**: **completado** — API de planes y suscripciones, vista admin y vista cliente (21 tests)
- **Contexto**: `backend/app/models/pricing.py` ya define `Plan` (con `discount_percent`) y `Subscription`, y `app/services/pricing.py` calcula el descuento al cerrar el ticket (`tickets.py:142` → `ticket.discount`). **Pero no existe router `api/v1/plans.py`**: nadie puede crear planes ni suscribir usuarios desde la aplicación, y el seed es lo único que los puebla.
- **Resultado esperado**: el administrador gestiona planes y el gestor/cliente ve su suscripción y su descuento aplicado.
- **Criterios de aceptación**:
  - [x] `api/v1/plans.py` (CRUD de planes + alta/baja de suscripciones).
  - [x] Vista admin "Planes" con la lista wireframeada.
  - [x] Vista cliente "Mi plan" (plan, fecha de alta/vencimiento, % de descuento, próximo cobro).
  - [x] El ticket cerrado refleja el descuento del plan y es visible en el PDF y en "Mis tickets".
  - [x] Test: alta de plan → suscripción → cierre de ticket → `discount` = porcentaje esperado.
- **Verificado**: 21 tests en verde en SQLite **y** PostgreSQL. `GET/POST /plans`, `GET/PATCH/DELETE /plans/{id}`, `POST/GET /plans/subscriptions`, `DELETE /plans/subscriptions/{id}` y `GET /plans/me`. Smoke test contra la app en marcha: los tres planes de la decisión **D2** (30/60/200 € con 5/10/20 % de descuento) y `/plans/me` devuelve `vigente` con `billing_mode: contable` (D2: sin pasarela de pago hasta que haya un cliente piloto).
- **Lo que ya existía y no hubo que tocar**: el PDF del ticket ya pintaba "Descuento aplicado" (verificado descomprimiendo el content stream del PDF renderizado) y el modal de "Mis tickets" ya lo mostraba. El cálculo de `pricing.py` **no** se ha tocado: el módulo lo replica tal cual.
- **Reglas de negocio fijadas** (documentadas por si hay que cambiarlas): un usuario tiene **como mucho una suscripción vigente** (409 si ya tiene otra) y la baja de un plan con suscripciones devuelve **409** (hay que desactivarlo antes) porque la FK es `ON DELETE RESTRICT`. La baja de suscripción es **lógica** (`is_active=False`), para conservar el histórico.
- **Decisión del usuario**: números definitivos de los planes (Básico 30 €, Familiar 60 €, Empresa 200 €) y si el cobro es real (pasarela) o de momento sólo contable.

### T-19 · Vistas del Cliente: Mis vehículos, Mi perfil

- **Estado**: **completado** — dos pantallas nuevas y la API que necesitan (24 tests)
- **Contexto**: faltan "Mis vehículos" (la API `vehicles.py` y el modelo ya existen, con la relación N:M `VehiculoUsuario` con rol `propietario|conductor`) y "Mi perfil" (hay endpoint de cambio de contraseña, pero no de datos de perfil).
- **Resultado esperado**: el cliente gestiona sus vehículos (alta, baja, vincular/desvincular como propietario o conductor) y edita su perfil desde la web.
- **Criterios de aceptación**:
  - [x] Vista "Mis vehículos" con alta/edición y vínculo de roles (propietario/conductor).
  - [x] Vista "Mi perfil" con nombre, teléfono y cambio de contraseña.
  - [x] Un conductor ve los tickets de los vehículos que conduce, no los de otros.
  - [x] Route guards por rol en el router.
- **Verificado**: 24 tests en verde. Rutas `/mis-vehiculos` y `/mi-perfil` con `meta.roles` (`admin`, `cliente`).
- **Desviación justificada**: `GET /api/v1/vehicles` es **staff-only** y no había forma de consultar los vehículos del propio cliente, así que se añadieron endpoints *user-scoped* (`/users/me/vehicles*`, `/users/me/tickets`) en `users.py`. Sin ellos la vista "Mis vehículos" no habría podido existir para el rol cliente.
- **Bugs de backend encontrados y corregidos**:
  - **Fuga de datos entre clientes** (la más grave): `GET /api/v1/tickets` acotaba por **membresía de sucursal**, así que un cliente con membresía veía los tickets de **todos** los vehículos de esa sucursal (matrículas, importes y horas de otros conductores). El ámbito del cliente pasa a ser **sus vehículos**; 5 tests nuevos.
  - `UserUpdate.full_name` no tenía `min_length`: un nombre de 1 carácter se guardaba y hacía fallar con **500** la serialización de `GET /users` (rompía el CRUD de usuarios del admin).
  - No existía `GET /users/{id}/memberships`: la vista de operadores lo explica en pantalla.

### T-20 · Gestor: log de entradas/salidas, alertas activas y operadores

- **Estado**: **completado** — tres pantallas nuevas del gestor
- **Contexto**: existen la API de tickets (filtrable por fecha) y la de alertas, pero **no hay vista** de "Entradas/Salidas (log)" ni de "Alertas activas"; la asignación de operadores a la sucursal se hace desde el CRUD de usuarios del admin, no desde la vista del gestor.
- **Resultado esperado**: el gestor ve el log de movimiento de vehículos de su sucursal, sus alertas activas y gestiona sus operadores sin salir del rol.
- **Criterios de aceptación**:
  - [x] Vista de entradas/salidas con filtros por fecha, plaza, vehículo y origen (`automatic` / `manual`).
  - [x] Vista de alertas activas con acción de resolver/ignorar.
  - [x] Vista de operadores con alta y asignación a la sucursal.
  - [x] Todo filtrado por sucursal según el RBAC del gestor.
- **Verificado**: rutas `/gestor/movimientos`, `/gestor/alertas` y `/gestor/operadores` con `meta.roles` (`admin`, `gestor`) y entradas de menú por rol. El backend acota (membresía de sucursal) y el selector de sucursal sólo ofrece las del gestor.
- **Alta de operadores por el gestor: resuelta** con una API **nueva y acotada por sucursal** (`backend/app/api/v1/gestor_operadores.py`): `GET/POST /parkings/{parking_id}/operadores`. El gestor sólo puede actuar sobre sucursales de las que es miembro (403 si no), el rol creado es **forzado** a `operador` (el payload no tiene campo `role`, así que ni siquiera se puede pedir un admin) y la única membresía que se crea es la del path. Los endpoints globales de admin (`/users`) **siguen siendo admin-only**: no se han abierto. Verificado en vivo: listado 200, alta 201, `role: "admin"` en el payload ignorado, un operador recibe 403 y `GET /users` con gestor sigue dando 403. 8 tests nuevos.
- **Un límite del backend que sí se documenta**: la API de alertas sólo tiene `acknowledge` (idempotente): **no existe "resolver" ni "ignorar"**; la vista lo llama "Marcar como revisada" y lo explica en pantalla. Traer un usuario **que ya existe** a una sucursal sigue siendo tarea del administrador (asignarlo a una sucursal ajena al gestor es justo lo que la API acotada evita).

### T-21 · Adjuntos/fotos en incidentes (hasta 3)

- **Estado**: **completado** — hasta 3 fotos por incidente, con volumen local y validación por bytes
- **Contexto**: `api/v1/incidents.py` y el modelo de incidentes **no tienen ningún campo de fichero** (no hay `upload`, ni almacenamiento de objetos). Hoy sólo tiene `kind`, `space_id`, `parking_id`, `description`.
- **Resultado esperado**: el operador puede adjuntar hasta 3 fotos al reportar un robo o una avería.
- **Criterios de aceptación**:
  - [x] Endpoint de subida con validación (tipo MIME, tamaño máximo, hasta 3 ficheros).
  - [x] Almacenamiento definido (volumen local con nombre por hash; NO base64 en la BD).
  - [x] Miniaturas y descarga en la vista de incidentes.
  - [x] Retención y borrado según LOPDGDD (incluido el derecho al olvido).
  - [x] Sanitización de ficheros (no servirlos como HTML inline).
- **Verificado**: 572 líneas de test. Un incidente **es** un `Alert` (no hay tabla paralela): el modelo nuevo `IncidentAttachment` cuelga de `alert_id` con `ON DELETE CASCADE`.
- **Decisiones tomadas**: el tipo se valida **por los bytes** (firmas JPEG/PNG/WebP), no por la extensión ni por el `Content-Type` que manda el cliente — un fichero disfrazado no se guarda. El **SVG no se acepta** (es HTML ejecutable). Tope de 10 MB por fichero, 3 ficheros por incidente, retención de 90 días y script de purga (`backend/app/scripts/purge_incident_attachments.py`). El binario va a un volumen Docker (`incident_attachments`); en la BD sólo queda la metadata. La descarga se sirve con `Content-Type` verificado y `Content-Disposition: attachment`.
- **Decisión D5 aplicada**: **no se expone a ningún canal externo** en el MVP — los adjuntos los ven sólo el gestor y el admin de esa sucursal.
- **Verificado en vivo contra el stack** (no sólo con tests): subida de una foto real → **201** con el hash del contenido, el mime y el tamaño; miniatura → **200** `image/jpeg`; descarga → **200** con `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store` y `Content-Disposition: attachment`; listado → **200**; un fichero disfrazado de PNG → **415**; un PNG con el raster incoherente → **400**; y el **operador no puede ver** los adjuntos de su incidente → **403** (sólo gestor y admin).

### T-22 · Recuperación de contraseña del cliente

- **Estado**: **completado** — flujo completo con token de un solo uso (24 tests)
- **Contexto**: **no existe** flujo de "olvidé mi contraseña" (ni backend ni correo). El login sólo acepta usuario+contraseña. Hoy la única forma de recuperar el acceso es que un admin lo reinicie a mano.
- **Resultado esperado**: el cliente (y el operador) puede recuperar el acceso por correo con un token de un solo uso.
- **Criterios de aceptación**:
  - [x] `POST /auth/forgot-password` → correo con token de un solo uso y caducidad (p. ej. 30 min).
  - [x] `POST /auth/reset-password` → cambia la contraseña e invalida los tokens previos.
  - [x] El token se guarda **hasheado** y se invalida al usarlo.
  - [x] Plantilla de correo en español (`app/services/templates/`).
  - [x] Registro de auditoría `password_reset_requested` / `password_reset_completed`.
  - [x] Anti-abuso: rate-limit por IP y por email.
- **Verificado**: 24 tests en verde (SQLite y PostgreSQL). El token se guarda como SHA-256 (`token_hash` UNIQUE, 64 chars): en la BD no hay nunca el token en claro. El reset invalida los JWT previos vía `session_tracker.revoke_all`. La respuesta de `forgot-password` es **uniforme** para exista o no la cuenta (no enumera usuarios).
- **Pendiente de frontend**: la pantalla `/recuperar-contrasena` no existe (`frontend/**` no entró en el alcance de esta sesión); el enlace del correo apunta ahí. Mientras tanto, el token se puede usar llamando a `POST /api/v1/auth/reset-password`.

### T-23 · Tabla y endpoint de reconocimiento facial (preparación)

- **Estado**: **completado** — estructura preparada, endpoint deshabilitado por flag (18 tests)
- **Resultado esperado**: la estructura de datos existe, pero **no se usa** para autenticar a nadie.
- **Criterios de aceptación**:
  - [x] Modelo `FaceTemplate` (usuario, embedding, cámara, fecha) + Alembic.
  - [x] Endpoint de alta/baja **deshabilitado por feature flag** y sin uso en el login.
  - [x] Nota explícita en el README: reconocimiento facial fuera del MVP.
- **Verificado**: migración `0012_reset_and_face_templates` aplicada (`alembic current` → head); tabla `face_templates` con `embedding` en JSON y `camera_id` con `ON DELETE SET NULL`; setting `FACE_TEMPLATES_ENABLED` (default **False**) → con el flag apagado el alta y la baja devuelven **404**; test que comprueba estáticamente que **ninguna ruta de autenticación** usa `face_templates`; test que verifica que el README dice que el reconocimiento facial está fuera del MVP. No se implementa biometría: sólo la estructura.

### T-24 · Portal/app del cliente final (PWA)

- **Estado**: **completado** — PWA instalable del cliente (decisión D4 aplicada)
- **Contexto**: hoy el "Cliente" es un usuario del mismo frontend con menú propio. No hay app móvil ni portal público. En un parking, el conductor final es quien realmente valoriza el producto (saber si su coche está dentro, cuánto le va a costar, pagar).
- **Resultado esperado**: un PWA instalable para el cliente final con: entrada con matrícula, plaza asignada en tiempo real, ticket y pago.
- **Criterios de aceptación**:
  - [x] Definir si es PWA responsive o app nativa (recomendación: PWA, un solo codebase).
  - [x] Pantallas: mis vehículos, mi plaza, mis tickets, pago.
  - [x] Sin login de gestor: sólo cliente.
  - [x] Publicación en tiendas de apps (PWA instalable) o al menos APK interno.
- **Verificado**: manifest (`frontend/public/manifest.webmanifest`), service worker propio (`frontend/public/sw.js`, 34 assets precacheados), iconos reales en PNG y SVG, y el registro del SW sólo en producción. El build (`npm run build`) deja `dist/manifest.webmanifest`, `dist/sw.js` y `dist/icons/` verificables. Las pantallas "Mi plaza" (`/mi-plaza`) y "Pagos" (`/pagos`) son nuevas; "Mis vehículos" y "Mis tickets" ya existían.
- **Decisiones**:
  - **D4**: PWA, un solo codebase, sin tiendas de apps. La app nativa queda descartada.
  - **D2**: la pantalla de pagos es **contable** — muestra el importe pendiente y explica que no hay pasarela de pago. Sin pasarela, sin TPV, sin datos de tarjeta.
  - El service worker **cachea el shell** (HTML/JS/CSS) para que la app abra sin red, pero **no cachea las peticiones a `/api/`**: servir de caché una plaza averiada es peor que no tener app offline.
  - En la PWA instalada el menú se reduce a las entradas de cliente y el router redirige cualquier ruta que no sea del cliente a "Mis tickets" (la PWA es sólo para el conductor final).
  - Instalación documentada en `frontend/README.md` (Chrome/Edge: instalar desde la barra de direcciones; iOS: compartir → Añadir a pantalla de inicio) con sus limitaciones: sin notificaciones push, sin cobro, sin App Store.

### T-25 · API pública para terceros (documentada, no expuesta)

- **Estado**: **completado** — la API interna queda inventariada con su RBAC
- **Resultado esperado**: la estructura interna queda documentada y versionada, lista para exponerse cuando se decida (movilidad, autoridades).
- **Criterios de aceptación**:
  - [x] Documento de la API interna con los recursos y su RBAC.
  - [x] Versionado (`/api/v1`) ya presente → documentar la política de deprecación.
  - [x] Sin exposición pública hasta que se firme el modelo de datos y los términos.

---

## Ejecución del 2026-10-21 (sesión de subagentes)

**Cómo se repartió**: 8 subagentes en 3 olas, cada uno con propiedad exclusiva
de sus ficheros (para que dos agentes nunca tocaran el mismo a la vez), más
trabajo directo de la sesión principal en los puntos de integración.

**Cómo acabó**: tres PR mergeados en `main` con commit de merge (para
conservar el historial y el "por qué" de cada commit):
PR #13 (`899ec1f`, R5) · PR #14 (`d0ae543`, bloques 0-1-2) ·
PR #15 (`f84bf55e`, bloque 3).

| Ítem | Cómo | Resultado |
|---|---|---|
| T-01, T-02 | sesión principal | Commits y push hechos; CI remoto bloqueado por facturación |
| T-03 | sesión principal | PR #13 mergeado (`899ec1f`); PR #14 al final de la sesión |
| T-04, T-05 | subagente A | Suite contra PostgreSQL + test de dialecto + build en CI |
| T-06, T-10 | subagente B | Apagado del stream MJPEG y registro blindado |
| T-07 | subagente C | 5 fps por defecto, configurable por entorno |
| T-08, T-11 | subagente D | Auditoría del login y tests del middleware |
| T-09 | sesión principal | Detector validado y **bug de canales invertido corregido** |
| T-12 | sesión principal | Backups con cifrado y restauración probada |
| T-13 | subagente E | Locust, SLO y ejecución de referencia |
| T-14 | sesión principal | **GPU descartada con datos** (ADR-0002) |
| T-15 | sesión principal | ADR de orquestación (ADR-0001) |
| T-16 | subagente F | Exportes PDF/CSV de los cinco informes |
| T-17 | subagente G | SSE en la vista del operador y en la de calibración |
| T-22, T-23 | subagente H | Recuperación de contraseña y estructura de FaceTemplate |
| T-25 | sesión principal | API interna inventariada con su RBAC |
| T-18 | subagente I | API de planes y suscripciones + vistas admin y cliente |
| T-19, T-20 | subagente J | Vistas de cliente y gestor (+ endpoints *user-scoped*) |
| T-21 | subagente K | Hasta 3 fotos por incidente, con volumen local y validación por bytes |
| T-24 | subagente L | PWA instalable del cliente |
| — | sesión principal | Integración de rutas y menú, y el **fix de la fuga de tickets entre clientes** |

**Bugs de producción encontrados y corregidos** (ninguno estaba en el plan;
todos han salido al ejecutar los criterios de aceptación):

1. **El detector de vehículos no detectaba nada**: la imagen se invertía a RGB
   antes de inferir y Ultralytics la invierte por su cuenta → 0 detecciones
   sobre fotos reales. El servicio respondía `200 []`, indistinguible de "no
   hay coches en la plaza" (T-09).
2. **El stream SSE también bloqueaba el apagado del backend**, igual que el
   MJPEG (T-06+1).
3. **El SSE nunca aceptó el `?token=` que su propio docstring anunciaba**
   (T-17+1).
4. **El CI podía ficar en rojo por un flake**: dos tests de rate-limit
   dejaban la ventana real en 2 s y 10 s, así que el bucket expiraba entre
   peticiones y el 429 no llegaba. Dependía de la carga del equipo.
5. **Siete ficheros de test seguían contra SQLite** aunque la suite corriera
   contra PostgreSQL; al ejecutarlos de verdad apareció un
   `ForeignKeyViolation` que SQLite escondía (SQLite no aplica claves
   foráneas por defecto).
6. **Cerrar el modal de previsualización tumbaba el backend (SIGSEGV)**: el
   `release()` del `VideoCapture` competía con un `grab()` en vuelo en otro
   hilo y OpenCV abortaba el proceso (exit 139). En QA el `--reload` lo
   disimula; en producción el backend caía cada vez que un operador cerraba
   el modal. Lo destapó la prueba de carga (T-13+2).
7. **Cada stream retenía una conexión de PostgreSQL** (`Depends(get_db)` vive
   hasta que termina la respuesta, y en un stream eso es toda su duración):
   con el objetivo de 50 streams el pool se agotaba. También lo destapó la
   prueba de carga (T-13+3).
8. **Un cliente con membresía de sucursal veía los tickets de otros
   clientes**: `GET /api/v1/tickets` acotaba por membresía de sucursal, así
   que cualquier cliente con membresía veía las matrículas, los importes y
   las horas de **todos** los vehículos de esa sucursal. Fuga de datos entre
   clientes (LOPDGDD). El ámbito del cliente pasa a ser sus vehículos.

**Lo que queda**: tras esta sesión, el **Bloque 3 está completo** (T-18 a T-21
y T-24, con las decisiones D2/D4/D5 del propio documento aplicadas). Los
únicos criterios sin marcar son **dos de T-02/T-03**, que dependen de que se
arregle la **facturación de la cuenta de GitHub** para que el CI remoto pueda
ejecutar jobs.

Quedan además **dos decisiones de producto** que esta sesión dejó
documentadas y no implementadas, porque son cambios de alcance:

1. **Cobro real** (T-18, T-24): con la decisión D2 el cobro es **contable**,
   sin pasarela. Cuando haya un cliente piloto habrá que añadir el cobro
   real (el punto de enganche son `billing_mode`/`billing_note` de la API de
   planes y la pantalla de pagos).
2. **Traer un usuario ya existente a una sucursal**: es tarea del
   administrador por diseño (un gestor no asigna usuarios a sucursales
   ajenas). El alta de operadores por parte del gestor sí está resuelta
   (T-20), con la API acotada por sucursal.




---

## Mapa de dependencias

```
T-01 (commit) ──┬──> T-02 (CI verde) ──> T-03 (cerrar PRs)
                ├──> T-05 (build de imagen)
                └──> T-04 (tests contra Postgres) ──> T-13 (Locust, necesita SLO real)

T-06 (shutdown MJPEG) ──> T-07 (fps) ──> T-09 (detector validado)
T-08 (audit de login) ──> T-11 (tests de regresión del middleware)
T-10 (registro de streams) ──> T-11

Bloque 2 (roadmap) es independiente del Bloque 0/1, salvo:
T-12 (backups) ──> T-15 (Swarm/K8s: necesita backups antes de HA)
T-16 (exportes) ──> T-18 (planes: los informes del plan salen en el mismo formato)

Bloque 3 (módulos) independiente, salvo:
T-18 (planes) ──> T-19 (Mi plan), T-20 (operadores), T-24 (PWA del cliente)
T-22 (recuperación de contraseña) ──> T-24 (PWA, que necesita self-service)
```

---

## Reglas de ejecución con subagentes (`/goal`)

1. **Un subagente = un `T-xx`** (o un grupo contiguo del mismo bloque y el mismo fichero). Nunca dos agentes editando el mismo fichero a la vez.
2. **Cada subagente empieza leyendo su ítem** en este documento y termina **actualizando la casilla** `[ ]` → `[x]` de sus criterios de aceptación.
3. **El resultado esperado es la definición de "hecho"**: un subagente que no puede verificar sus criterios no da el ítem por terminado; lo deja a medias y lo reporta.
4. **TDD**: todo ítem que toque lógica de backend va con su test en el mismo subagente. Un ítem sin test se considera a medias, salvo que el propio ítem lo excluya explícitamente.
5. **Nada de push a `main`**: los subagentes commitean en la rama de trabajo; el merge lo decide la persona.
6. **Si un ítem revela un ítem nuevo**, se añade al final del bloque correspondiente con id `T-xx+1` y se reporta; no se improvisa fuera del plan.
7. **Los cambios de contrato (API, modelos, rutas)** se documentan en el mensaje del commit y en `docs/CODEMAPS/`.

---

## Definición de "hecho" (global)

- [x] `cd backend && ruff check app tests` → sin errores.
- [x] `cd backend && mypy app` → sin errores nuevos (hoy `continue-on-error: true`).
- [x] `docker exec parking-backend-1 pytest -q` → 265 passed, 0 failed (o más, nunca menos). → **508 passed en SQLite y 517 en PostgreSQL**.
- [x] `docker compose up -d` → todos los servicios *healthy* y `/health` responde 200.
- [x] QA visual en el navegador de las pantallas tocadas (con la app real, no sólo tests).
      → **HECHA** con Chromium headless (Playwright) sobre la app real
      (`frontend/scripts/qa_visual.py`): las **18 pantallas** de los tres
      roles se renderizan, **0 errores de consola** y **0 peticiones de red
      fallidas**. Se revisaron una a una las capturas: catálogo de planes,
      mi plan, mis vehículos, mi perfil, mi plaza, pagos, entradas/salidas,
      alertas, operadores, tickets, mapa, cámaras, vivo y alta manual.
      La QA destapó un defecto visual: el aviso de cobro contable se leía
      "Cobro contable. Cobro contable: ..." (la etiqueta se anteponía a un
      texto que ya empezaba así). Corregido.
- [x] Sin 4xx/5xx inesperados en `docker logs backend` durante la QA.
      → Con el árbol estable el log está limpio. Durante el trabajo en
      paralelo sí hubo errores de arranque del reloader por ficheros a
      medio editar (no de la app).

---

## Decisiones que necesito de ti (bloquean los ítems marcados)

| # | Decisión | Ítems afectados | Mi recomendación |
|---|---|---|---|
| D1 | fps objetivo del preview en vivo | T-07 | 5 fps fijo: ahorra ~85 % de CPU/ancho de banda y la latencia sigue siendo < 400 ms |
| D2 | Números definitivos de los planes y si hay cobro real | T-18 | Mantener los de la memoria (30/60/200 €) y **de momento contable** (sin pasarela) hasta que haya un cliente piloto |
| D3 | Dónde se guardan los backups y quién los vigila | T-12 | S3-compatible cifrado + alerta de antigüedad; el procedimiento de restauración se prueba cada trimestre |
| D4 | ¿PWA o app nativa para el cliente final? | T-24 | PWA: un solo codebase, instalable, sin tiendas |
| D5 | ¿Se exponen las incidencias/fotos en el incidente a un canal externo? | T-21 | No en el MVP: sólo gestor y admin |
| D6 | ¿Los subagentes de la siguiente sesión pueden commitear y pushear a la rama de trabajo? | todos | Commitean a la rama; el push y el merge los hace una persona |

---

## Anexo — Evidencia recogida el 2026-10-21

- **Stack**: `parking` (db postgis:16-3.4, redis:7, backend, frontend, celery-worker) + `parking-mediamtx` + `parking-rtsp-push` (RTSP de prueba) + `parking-mediamtx-qa`.
- **Prueba de live preview**: cámara id=81 apuntando a `rtsp://parking-mediamtx:8554/cam1`; primer frame a 1,85 s; 35 fps; 1,2 MB/s; captura a canvas → data URL de 37 KB; detección de vehículos fail-open (200 con `[]` con el detector caído).
- **Pruebas**: 265 passed / 0 failed (final), 48 failed / 217 passed (antes de arreglar el middleware).
- **CI**: PR #14 → Backend FAIL / Frontend OK; PR #13 → todo OK; `main` → verde. La serie de runs muestra el primer rojo en `007c8ad` (commit del vehicle-detector, que introdujo los `F401`).
- **Auth en vivo**: login 200 · `bearer` en minúsculas 200 · logout 200 · token reutilizado → 401 · `Bearer` malformado → 401 (nunca 500) · sin header → 401 · auditoría `logout_success` con `user_id=1`.
- **Caché de la QA**: `mediamtx` construido localmente en `C:/Users/catvi/AppData/Local/Temp/mediamtx-build/` (fuera del repo); la imagen `parking-mediamtx:qa` y los contenedores de prueba **no** forman parte del repo.
