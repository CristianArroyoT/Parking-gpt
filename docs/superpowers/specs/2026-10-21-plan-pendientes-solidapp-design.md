# Plan de trabajo — pendientes de solidAPP

**Fecha**: 2026-10-21 · **Rama de trabajo**: `feat/live-preview-cameras` · **Estado del repo**: 8 ficheros modificados sin commitear, PR #13 y PR #14 abiertos.

> ### 📍 Estado actual (2026-10-21, cierre de la sesión)
>
> El plan está **ejecutado**: **221 de 222 criterios** verificados. `main` y `origin/main` están **sincronizados** (el nº de commits crece con cada entrega; se consulta con `git log --oneline | wc -l`).
>
> | Comprobación | Resultado |
> |---|---|
> | Suite completa | **562 passed** en SQLite · **571 passed** en PostgreSQL |
> | QA visual (Chromium) | 21 pantallas a **5 anchos** (414, 768, 1024, 1232, 1440 px): 0 desbordes, 0 errores de consola |
> | PWA | verificado: instalable y **arranca sin red** |
> | API | **101 rutas** inventariadas (coinciden con el código) y **99 de 99 endpoints con test**; el inventario se genera del código y **el CI lo comprueba** |
> | Esquema | Los modelos y las migraciones coinciden: `alembic check` limpio y **el CI migra una base vacía** |
> | Stack | `docker compose up -d` → los **11 servicios** aparecen `(healthy)` |
> | Carga / SLO | **Revalidado** con el código final: 467 peticiones, 0 fallos → **14 de 14 reglas** (informe `2026-10-21-revalidacion.json`) |
> | Lint y tipos | `ruff` en verde (backend **y** `tools/`); **`mypy` en verde (0 errores en modo `strict`)**, y su paso del CI ya **no** va con `continue-on-error`; **`eslint` en verde (0 problemas)**, con paso propio en el CI; `vue-tsc` y `npm run build` en verde; `actionlint` exit 0 |
> | CI replicado en local | Los **4 jobs** del workflow (backend, integration, docker-build y frontend) pasan **completos, incluidos los dos pasos de test**: `python tools/ejecutar_ci_local.py --all` |
>
> **Lo que queda depende de ti** (y sólo de ti):
> 1. **La facturación de la cuenta de GitHub.** Sin ella los jobs de Actions
>    no arrancan (*"recent account payments have failed"*) y no se puede
>    marcar el último criterio, que es precisamente el que depende del
>    CI. **Todos** los jobs del workflow están replicados a mano y en
>    verde, así que deberían pasar en cuanto lo arregles.
>    - Ojo al alcance: el **último run que ejecutó un solo paso** fue el
>      del **2026-07-07**; desde entonces **ningún** run ha llegado a
>      arrancar un job. De los 100 runs revisados, **44** fueron
>      rechazados así. El CI lleva **más de tres meses sin validar nada**
>      (no es sólo que hoy falle), así que esto no es un trámite menor:
>      es la única red de seguridad que le queda al repo, y **87 commits
>      de `main` siguen sin pasar por ella**.
>    - Para comprobarlo de un vistazo: `python tools/estado_ci.py`
>      (distingue verde / rojo de verdad / rechazado por la cuenta).
>    - **Tres vías para recuperar el CI**, de menos a más invasiva (el
>      repositorio es **privado**, así que los runners de pago son
>      inevitables mientras la cuenta no esté al día):
>      1. **Arreglar la facturación** (*Billing & plans*). Es lo
>         limpio: no toca el repositorio ni el workflow.
>      2. **Hacer el repositorio público.** Las Actions son gratuitas
>         en repos públicos, así que el bloqueo desaparece sin tocar
>         nada. **Ojo**: el repositorio tiene el histórico completo y
>         datos de ejemplo; es una decisión de producto sobre la
>         visibilidad, no una decisión técnica.
>      3. **Runner self-hosted en esta máquina.** Es lo que se ha
>         intentado medir: el token de registro funciona y no hay
>         runners dados de alta, pero **no es viable sin tocar el
>         workflow** (el job de integración declara servicios
>         Linux con `localhost`, y dentro de un runner en contenedor
>         los servicios se alcanzan por nombre) **o sin parar el stack
>         local** para liberar los puertos 5432 y 6379. Meter un cambio
>         del workflow que no se puede validar (porque los jobs no
>         arrancan) es justo la forma de dejar el CI en rojo sin
>         querer, así que **no se ha hecho**.
> 2. **La decisión de producto del cobro con pasarela** (D2): hoy es
>    contable, a la espera de que haya un cliente piloto.
>
> Este documento **creció** durante la ejecución: cada hallazgo posterior
> (T-13+6 y siguientes) tiene su propia entrada, con lo que se
> comprobó y cómo.

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
  - [x] `mypy app` → **0 errores** (en modo `strict`; ver T-28). Su paso del CI ya no va con `continue-on-error`.
  - [ ] Los **4 checks del CI sobre `main`** en SUCCESS (Backend, Integration, Build de imágenes Docker y Frontend).
      > El criterio original decía `gh pr checks 14`, pero **el PR #14 está fusionado desde el 2026-07-07** y no queda ningún PR abierto: la referencia correcta hoy es el CI sobre `main`. Ver `python tools/estado_ci.py`.
- **Cómo verificarlo**: `cd backend && ruff check app tests && python tools/estado_ci.py`
- **Depende de**: T-01 (el fix está en `test_vehicle_detector.py`, sin commitear).

- **Nota (bloqueo externo, no de codigo)**: los jobs de GitHub Actions de esta cuenta **no arrancan**: *"The job was not started because recent account payments have failed or your spending limit needs to be increased"*. Es un problema de **facturacion de la cuenta de GitHub**, no del repositorio: el workflow es valido y su equivalente local pasa (ruff en verde, suite completa en verde, build de imagen en verde, YAML parseado con `yaml.safe_load`). **Requiere una accion del usuario**: revisar *Billing & plans* en la cuenta de GitHub.
- **El alcance real del bloqueo (medido el 2026-10-21)**: no es sólo "ahora falla". Revisados los **100 runs** más recientes: **56** llegaron a ejecutar pasos y **44** fueron **rechazados sin ejecutar ninguno**. El **último run que ejecutó un solo paso** fue el del **2026-07-07T20:52:15Z** (en la rama `feat/live-preview-cameras`: Backend en rojo por el `F401`, Frontend en verde) — el de PR #14 justo antes de fusionarlo. Los 44 runs posteriores (todos de hoy) terminan en `failure` **con 0 pasos** en los 4 jobs, que es la firma de un job **rechazado antes de asignarle un runner** (no de un fallo del código). Consecuencia: **87 commits de `main` nunca los ha validado el CI**, sólo la verificación local. `tools/estado_ci.py` distingue los tres casos (verde / rojo de verdad / rechazado por la cuenta) para que no se confundan.

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
- **Verificado**: `backend/locustfile.py` con los 4 escenarios; `backend/locust/slo.json` con 13 reglas (cada una con su porqué); `backend/locust/check_slo.py` que devuelve exit ≠ 0 si el p95 incumple; informe de referencia en `backend/locust/reports/2026-10-21-referencia.json` y su contexto. La carga se mide contra una **instancia dedicada sin `--reload`**, porque el reloader del entorno de QA reinicia el backend con cada escritura y arruina las cifras.
- **Referencia re-medida con el P0 ya corregido**: 461 peticiones, **0 fallos**, 0 cortes de stream y **0 reinicios** del worker en 180 s. El SLO se cumple entero (**13 de 13 reglas**). Números: lectura de plazas p95 21 ms, tickets 35 ms, cámaras 19 ms, alta de ticket 38 ms, cierre 49 ms, apertura SSE 24 ms con 71 sesiones sin un solo corte, primer frame del preview 1 700 ms con 8 sesiones sin fallos.
- **Hallazgo**: la propia carga destapó dos bugs de producción que ningún test había visto — ver T-13+2 y T-13+3 — y un detalle del *fixture*: la fuente RTSP de QA hace push de un MP4 con keyframe cada 250 frames (GOP de ~10 s), así que el primer frame tardaba 1,2-8 s y varias sesiones se pasaban del límite. Recreando el push con `-g 25` el primer frame llega en 1,7 s y el preview queda sin fallos: eso quita un cuello de botella del fixture, no del producto.

### T-13+1 · Fijo en el CI: la suite debe ser reproducible

- **Estado**: **completado** — dos flakes de rate-limit eliminados
- **Contexto**: los tests de rate-limit dejaban la ventana real en 2 s y 10 s para simular el paso del tiempo, pero además simulaban el reset **borrando a mano** las claves del bucket. La ventana corta no aportaba nada y sí abría una carrera: si las tres peticiones del test (cada una con un hash bcrypt) tardaban más que la ventana en una máquina cargada, el bucket expiraba entre peticiones, el contador se reiniciaba y el 429 no llegaba.
- **Medición**: antes del arreglo, **2 de 3** ejecuciones de `test_endpoint_rate_limit.py` + `test_rate_limit_login.py` fallaban; después, **5 de 5** en verde. El comportamiento comprobado es el mismo (el reset se sigue simulando a mano, que es determinista).
- **Criterios de aceptación**:
  - [x] Ventana real la del default en los dos tests que simulaban el reset a mano.
  - [x] 5 ejecuciones seguidas en verde.
  - [x] Explicado en el commit por qué el bug **no** era del código de producción (la ventana fija, no sliding, es el comportamiento correcto).
- **Segundo caso, resuelto después (T-13+5)**: los tests de rate-limit de endpoints fallaban de forma intermitente porque el bucket `rl:users_create:actor:1` **se saltaba un valor** (2 → 4 en un solo POST) y el test veía un 429 antes de tiempo. La causa era que la suite **compartía Redis con la app en marcha** (backend en `:8000`, worker de Celery, QA manual): cualquier `POST /users` real hecho como admin —que en la BD de test también es el actor 1— incrementaba el mismo bucket. La suite pasa ahora a su **propia base de Redis (la 15)**: con la app real bombardeando `POST /users` como admin, el fichero de tests de rate-limit pasa **6/6** en dos pasadas (antes ese mismo escenario lo hacía fallar).

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

### T-13+5 · La suite compartía Redis con la app en marcha (rate-limit intermitente)

- **Estado**: **completado** — la suite usa su propia base de Redis
- **Contexto**: los tests de rate-limit de endpoints fallaban de forma **intermitente** (2 o 4 fallos según la pasada). El contador del bucket `rl:users_create:actor:1` **se saltaba un valor** (2 → 4 en un solo POST) y el test veía un 429 antes de tiempo.
- **Causa**: la suite **compartía Redis con la app que está en marcha** en el mismo entorno (backend en `:8000`, worker de Celery, QA manual). Cualquier `POST /users` real hecho como admin —que en la BD de test también es el actor 1— incrementaba **el mismo bucket** que mide el test. Con el monitor de Redis se vio que los INCRaban del mismo proceso, pero el salto de +2 sólo se reproducía con tráfico de la app en paralelo.
- **Criterios de aceptación**:
  - [x] La suite apunta a una **base de Redis propia** (la 15) mediante `REDIS_URL`.
  - [x] Con la app real bombardeando `POST /users` como admin —la contaminación exacta que provocaba los fallos— el fichero de tests de rate-limit pasa **6/6** en dos pasadas.
- **Nota**: en CI el job ya tenía su propio Redis, pero aislar también allí hace que el resultado de los tests **no dependa de lo que esté haciendo la app** en ese momento.

### T-13+6 · P2 — cerrar y reabrir el preview daba 409, y el teardown congelaba el backend

- **Estado**: **completado** — corregido y verificado antes/después contra el código anterior
- **Contexto**: al cerrar el modal de previsualización y volver a abrirlo, el cliente recibía un **409** durante hasta ~8 s (el umbral de `STALE_AFTER_S`). Debajo había cuatro defectos encadenados:
  1. El `cap.release()` (teardown del RTSP) corría **en el hilo del event loop**. `CapturaSincronizada.release()` espera a la lectura en vuelo, que con la cámara colgada puede tardar hasta el timeout de FFmpeg (5 s): **el backend entero se congelaba**, no sólo ese stream.
  2. El slot de la cámara se liberaba en el `finally` del generador **externo** (`safe_gen`), que se ejecuta **después** del `finally` del generador **interno** (el que cierra la captura): el slot quedaba ocupado durante todo el teardown.
  3. La liberación dependía del **finalizador de generadores asíncronos** del event loop (Starlette cancela la tarea al abortarse la petición y el generador se cierra después): no era determinista y, en el peor caso, el slot se quedaba hasta el barrido de huérfanas.
  4. `release(camera_id)` no sabía **a qué sesión** pertenecía la llamada (LIMITACIÓN CONOCIDA documentada en su docstring): el `finally` de un generador viejo podía liberar la sesión de un cliente nuevo y matarle el stream.
- **Resultado esperado**: cerrar el preview libera la cámara de inmediato, reabrirla nunca da 409, y el teardown del RTSP no congela el backend.
- **Criterios de aceptación**:
  - [x] El slot se libera **antes** de la limpieza de la captura, y la liberación es **determinista** (no depende del finalizador de generadores ni del barrido de huérfanas).
  - [x] El teardown del `VideoCapture` se ejecuta **fuera** del hilo del event loop.
  - [x] `release`/`heartbeat` identifican **la sesión**: el `finally` de un generador viejo no puede tocar la sesión de un cliente nuevo.
  - [x] El registro de streams pasa a una API **síncrona** (una liberación con `await` puede ser cortada por una cancelación).
  - [x] Test de regresión con el **mismo fichero** ejecutado contra el código anterior y el nuevo: 3 de 4 fallaban antes (incluido el congelamiento del event loop: **5 ticks en 1 s** frente a ~100 ahora) y los 4 pasan ahora.
- **Nota**: el cierre y reapertura **a nivel de endpoint** ya funcionaba en el camino de cancelación; lo que no estaba garantizado era el orden, la determinación y la identidad de la sesión. El congelamiento del event loop sí era real y era lo más grave.
- **Revalidación bajo carga (2026-10-21)**: con el código corregido se regeneró la ejecución de referencia (6 usuarios, 180 s, 10 cámaras): **491 peticiones, 0 fallos, 0 cortes, 0 reinicios del worker y 0 previews descartados con un 409** → SLO **14 de 14** reglas OK (antes 13 de 13). Al revalidar salieron dos fallos del **instrumental**, corregidos:
  1. El locustfile leía en runtime `SOLIDAPP_CAMERA_IDS` (dos R) mientras la constante y el README documentan `SOLIDAPP_CAMARA_IDS` (una R): poner la variable documentada **no surtía efecto** y la ejecución se quedaba con la cámara 81 sola, la que provoca la contención. Ahora se aceptan los dos nombres.
  2. Los previews descartados con un 409 los cuenta Locust como **éxito** (un 409 es una regla de negocio, no un fallo HTTP), así que el SLO **no veía** la métrica clave del P2: una regresión habría pasado el CI sin que nadie se enterase. Nueva métrica `max_peticiones` (cuenta ocurrencias) y regla `mjpeg_sin_409` con umbral 0, con sus tests.
- **Segunda revalidación, con el código final del día** (después de los arreglos de móvil, del correo de cámara caída y de `/health/ready`): **467 peticiones, 0 fallos, 14 de 14 reglas**, 0 previews descartados con un 409 y 0 cortes de stream en 66 conexiones. Informe: `backend/locust/reports/2026-10-21-revalidacion.json`. El número de peticiones baja un poco porque depende del ritmo de la máquina, no del código: lo que se compara son los percentiles y los fallos, y se mantienen.
- **CI replicado a mano** (el CI remoto no arranca por la facturación): `ruff check app tests` en verde, `mypy app` sin errores nuevos, pytest en SQLite y PostgreSQL, `pytest tests/test_sqlite_only_functions.py` (paso aparte del job de integración), `vue-tsc --noEmit`, `npm run build`, **build de las dos imágenes Docker** (exit 0), usuario no-root `app` y log rotado en `/var/log/solidapp/backend.log` comprobados como hace el job `docker-build`, y QA visual headless (19 pantallas sin incidencias, 0 errores de consola).

### T-13+7 · P3 — la tabla de Operadores no cabía en su tarjeta y la columna "Estado" quedaba cortada

- **Estado**: **completado** — corregido y verificado a 1232 px
- **Contexto**: encontrado en la **QA visual en el navegador integrado** (no en la headless), con la ventana del panel lateral a 1232 px. En `/gestor/operadores`, la tabla vive en media rejilla (`lg:grid-cols-2`): la tarjeta mide ~435 px y la tabla necesita ~470 px (el correo largo no cede), así que la columna **"Estado"** (los badges "Activo") quedaba **cortada a media**. En el navegador se veía el badge a medio dibujar.
- **Por qué la QA headless no lo veía**: el script recorría las pantallas a 1440 px, donde la columna sí cabe. El defecto sólo aparece por debajo de ~1280 px.
- **Al medirlo apareció más**: la comprobación de desbordamiento encontró **4 recortes más** en el mismo ancho — Cámaras (950 px en 928), Planes (887 en 611), Usuarios (650 en 611) y Tarifas (744 en 611). Los tres últimos están dentro de una tarjeta con `overflow-hidden`: la tabla se **recortaba** sin forma de llegar al resto.
- **Criterios de aceptación**:
  - [x] El script de QA visual **detecta** contenido que no cabe (recortado o desbordado) y sale con código 1 si lo hay.
  - [x] El script permite elegir el ancho del viewport (`--ancho`), y la QA se pasa a 1232 px además de a 1440 px.
  - [x] Las 5 tablas que no caben están envueltas en un contenedor `overflow-x-auto` con `min-w-max`: **0 desbordes a 1232 px** (antes 5).
  - [x] Sin regresión a 1440 px: 0 desbordes y 0 errores de consola en las 21 pantallas.
  - [x] `vue-tsc --noEmit` y `npm run build` en verde.
- **Nota de alcance**: el arreglo es el desplazamiento horizontal en la
  tarjeta, no un rediseño. Con ventana ancha se ve exactamente igual que
  antes.
- **Ampliado a 1024 px** (el ancho de tablet, con el menú colapsado): salió
  un defecto más, la etiqueta **"Minutos/fracción"** de Tarifas, que era un
  único token sin espacios (98 px) en una caja de 86 px y se salía de su
  columna. Ahora dice "Minutos por fracción", que parte en dos palabras como
  la etiqueta de al lado. Con la QA a 1024, 1232 y 1440 px: **0 desbordes y
  0 errores de consola** en las 21 pantallas.
- **El detector excluye a propósito** los controles de formulario
  (`select`, `input`, `textarea`), que el navegador recorta de forma nativa
  con puntos suspensivos, y los elementos posicionados en absoluto o fijo.
  Sin esas exclusiones el detector marcaría ruido y nadie lo miraría.

### T-13+9 · P2 — en el móvil (414 px) la página entera se desplazaba de lado a lado

- **Estado**: **completado** — corregido y verificado a 414 px
- **Contexto**: la QA visual recorría cuatro anchos (768, 1024, 1232 y 1440 px), pero **ninguno era de móvil**: el más estrecho era una tablet vertical. Al añadir el ancho de un móvil (414 px) aparecieron **26 contenidos desbordados en 6 de las 21 pantallas**, y **3 pantallas con la página entera desplazable** de lado a lado (Movimientos, Operadores y Tickets). En un teléfono, el usuario tenía que mover la ventana para ver el final de una tabla.
- **Por qué**: un `<table>` no baja del ancho de su contenido. Sin un contenedor con `overflow-x-auto`, la tabla se sale de su tarjeta; y dentro de una rejilla o de un flex, el `min-width: auto` del ítem lo ata a la anchura mínima de su contenido, así que la columna no encoge y la página hereda el desbordamiento.
- **El arreglo tiene dos partes y con una sola no basta**:
  1. Envolver la tabla en un `div` con `overflow-x-auto` y `min-w-max` **dentro** del atributo `class` de la tabla.
  2. Poner `min-w-0` **en el ítem de la rejilla** que contiene la tabla. Con sólo la parte 1, el envoltorio se encoge pero la columna sigue midiendo lo que mide la tabla, y la página sigue desbordando. Se comprobó midiendo: el `<section>` de Operadores seguía con `min-width: auto` y 611 px de ancho en una columna de 366.
- **Cómo se localizó sin adivinar**: `frontend/scripts/sonda_anchura.py` (nuevo) mide la cadena de ancestros del elemento más ancho, con su `min-width` calculado, su `overflow-x` y su `display`. Es lo que distingue "este elemento es el culpable" de "este otro sólo lo arrastra".
- **Herramienta**: `tools/envolver_tablas.py` (nuevo) aplica la parte 1 a todas las vistas de forma mecánica. Dos detalles que la herramienta tiene que respetar y que costaron un 500 al principio: mueve la directiva `v-if`/`v-else` al envoltorio (si se deja en la tabla, Vue no compila: *"v-else has no adjacent v-if or v-else"*) y añade `min-w-max` **dentro** del atributo `class` (fuera, `<table class="w-full" min-w-max>` no significa nada).
- **Criterios de aceptación**:
  - [x] La QA visual recorre el ancho de móvil (414 px).
  - [x] Las 8 tablas que no caben están envueltas en un contenedor `overflow-x-auto min-w-0`.
  - [x] Los ítems de rejilla que contienen tablas llevan `min-w-0`.
  - [x] **0 desbordes a 414 px** (antes 26, en 6 pantallas) y **0 pantallas con scroll horizontal de página** (antes 3).
  - [x] Sin regresión: **0 desbordes** en las 21 pantallas a 768, 1024, 1232 y 1440 px.
  - [x] 0 errores de consola y 0 peticiones fallidas en los **cinco** anchos.
  - [x] `vue-tsc --noEmit` y `npm run build` en verde.
- **Otro arreglo de la QA**: las pantallas de mapa y de vídeo en directo nunca dejan de cargar (teselas del mapa y flujo SSE), así que la espera de "networkidle" se agotaba siempre ahí y se reportaba como **error de red**. Ahora se reporta como **aviso**: es tráfico de fondo perpetuo, no una pantalla rota.

### T-13+10 · P2 — el texto corrupto podía llegar al commit sin que nada lo parase

- **Estado**: **completado** — puerta añadida al CI y verificada en local
- **Contexto**: al modelo de lenguaje se le cuelan con facilidad caracteres de otros alfabetos (CJK, cirílico, coreano) al escribir en español. No es hipotético: **pasó dos veces en esta misma sesión**, una en un docstring (una palabra china colada entre dos españolas) y otra en un **identificador de JavaScript** (con caracteres CJK), que dejó una vista entera en blanco con un 500. El escáner ya existía (`tools/escanear_texto.py`), pero era un paso manual: nada obligaba a pasarlo antes de commitear.
  > Los ejemplos no se reproducen literalmente: si estuvieran en el repo, la puerta que se describe aquí los detectaría a ellos mismos.
- **Arreglo**: el escáner pasa a ser **una puerta del CI**. Nuevo modo `--tracked`, que escanea **exactamente lo versionado** por git (ni `node_modules`, ni `dist`, ni ficheros generados): lo que se va a publicar es lo que se comprueba. Sale con código 1 si encuentra algo.
- **Dónde está el paso**: en el job `backend`, **antes de instalar dependencias**. El escáner es sólo biblioteca estándar, así que falla en dos segundos en vez de esperar al `pip install`.
- **Criterios de aceptación**:
  - [x] `python tools/escanear_texto.py --tracked` escanea todo lo versionado.
  - [x] El repo entero está limpio: **0 problemas en 312 ficheros versionados**.
  - [x] El paso está en `.github/workflows/ci.yml` y `actionlint` sale con 0.
  - [x] El ejecutor local (`tools/ejecutar_ci_local.py`) lo ejecuta y pasa.
- **Arreglo del ejecutor local**: `tools/ejecutar_ci_local.py` **ignoraba `continue-on-error`**, así que declaraba el job "backend" en rojo por el paso de `mypy`, que el workflow tolera a propósito (lleva `continue-on-error: true` desde el primer commit). Ahora reproduce la semántica de Actions: el paso se marca como fallido, **el job sigue** y el veredicto es el real.
- **Nota de verdad**: `mypy app` **no está en verde** (77 errores en 32 ficheros, en modo `strict`). No es una regresión de este trabajo: el paso del CI lo toleró desde el primer commit. La cabecera de este documento lo decía mal (decía 78 en 33) y ya está corregido.

### T-24+1 · Verificar que el PWA es instalable y arranca sin red (propuesto, no ejecutado en CI)

- **Estado**: **completado en local** · **pendiente de meter en el CI**
- **Contexto**: la QA visual recorre las pantallas del cliente, pero nadie
  miraba lo que hace que una PWA sea instalable. Un icono que devuelve 404,
  un manifiesto mal formado o un service worker que no toma el control sólo
  se ven cuando el usuario intenta instalar la app: y entonces ya es tarde.
- **Qué se ha hecho**: `frontend/scripts/qa_pwa.py` comprueba el manifiesto
  (campos que Chrome exige y tamaños 192/512), que **cada icono se sirva
  con 200**, que el *service worker* se registre, quede activo y **tome el
  control**, y que **la app arranque sin red** (se corta la red, se recarga
  y la pantalla tiene que salir de la caché).
- **Resultado medido (2026-10-21)**: manifiesto OK con 4 iconos y
  `display=standalone`; service worker activo y controlando con 44 entradas
  precacheadas; la app **arranca sin red**. El PWA es instalable.
- **Por qué no entra en el CI todavía**: el job de frontend corre en una
  imagen de Node sin Python ni navegadores; hacer la comprobación allí
  exigiría instalar Playwright y Chromium (+~500 MB y minutos de descarga).
  Y con la facturación de la cuenta resuelta **no se puede validar un
  cambio del workflow**, porque los jobs no arrancan: meter algo que no se
  ha podido probar en el CI es exactamente la forma de dejar el CI en rojo
  sin querer. Queda documentado para cuando el CI vuelva a estar en
  marcha.

### T-25+1 · El inventario de la API se había quedado en 61 de 99 endpoints (y dos rutas estaban registradas dos veces)

- **Estado**: **completado** — inventario regenerado y con comprobación automática
- **Contexto**: `docs/API-INTERNAL.md` (T-25) decía "61 endpoints en 18 grupos", pero la API ya tenía **99**. El documento no se había revisado desde antes del Bloque 3 (planes, incidencias y adjuntos, operadores de sucursal, plantillas faciales, informes, KPIs, PWA del cliente...). La propia sección 6 del documento avisa de que "se actualiza el documento, no al revés", pero no había forma mecánica de saber que estaba desfasado.
- **Al construir el verificador salieron dos defectos de código**:
  1. `POST /users/{user_id}/memberships` y `POST /vehicles/{vehicle_id}/users` tenían **el decorador `@router.post` duplicado**: la ruta se registraba dos veces y FastAPI avisaba en cada arranque con *"Duplicate Operation ID"*, ensuciando el OpenAPI (que es la fuente de la que sale el inventario). Corregido: el aviso desaparece.
  2. La columna "Quién" de dos endpoints no se podía leer del `Depends`: el preview y el SSE llaman a la dependencia **a mano** dentro del cuerpo (el patrón "opt-in por endpoint"), y `logout`/`logout/all` dependen del `AuditMiddleware`, que valida el token Bearer y deja el contexto en `request.state.audit`. El extractor reconoce los tres patrones.
  3. Y además, las dependencias dicen **quién puede llamar** al endpoint, pero no **qué datos ve**: varios endpoints filtran por rol y por membresía a mano en el cuerpo (para no duplicar el JOIN con `parking_context`). La columna "Quién" tiene ahora dos partes: el RBAC de dependencia y el ámbito de datos (`ámbito: membresías de sucursal`, `ámbito: sus vehículos`). El extractor sigue el filtro hasta las **funciones auxiliares** del módulo (`_scoped_query`, `_resolve_parking_id`, `_vehiculos_del_cliente`), distingue filtrar de construir y descarta las anotaciones de tipo.
- **Criterios de aceptación**:
  - [x] `tools/extraer_api.py` extrae rutas y RBAC del código con `ast` y **se valida contra el OpenAPI real** (si se le escapa una ruta, sale con código 1).
  - [x] `tools/generar_seccion_api.py --escribir` regenera la sección 3 del documento.
  - [x] `tools/verificar_api_doc.py` detecta la deriva entre el documento y el código.
  - [x] El inventario documenta los **99 endpoints** con su RBAC real, y el verificador dice "El inventario coincide con el código".
  - [x] Sin avisos de *Duplicate Operation ID* al arrancar.
  - [x] Suite en verde (530 passed en SQLite) tras quitar los decoradores duplicados.

### T-25+2 · Dos endpoints sin ningún test: el OCR de placas

- **Estado**: **completado** — 99 de 99 endpoints con test
- **Contexto**: al medir la cobertura de tests sobre la API (nuevo `tools/cobertura_api.py`) salió que **2 de los 99 endpoints no los ejercitaba ningún test**:
  - `GET /api/v1/parkings/{parking_id}/plates-detected`
  - `POST /api/v1/parkings/{parking_id}/cameras/{camera_id}/plates`

  Son los endpoints que empujan y listan las lecturas del OCR. Nadie había comprobado nunca su RBAC, su validación ni su alcance.
- **Criterios de aceptación**:
  - [x] Los dos endpoints tienen test de 401 (sin token), 403 (sin membresía), 404 (cámara de otra sucursal) y 422 (payload inválido).
  - [x] Se comprueba el **alcance**: el listado no filtra matrículas de otra sucursal, y ordena de la más reciente a la más antigua.
  - [x] Se comprueba el filtro `camera_id` y la validación de `limit` (0 y 501 → 422; defecto 50, tope 500).
  - [x] El POST persiste una fila por hit (la auditoría de la lectura OCR) y devuelve el resultado de la ingesta.
  - [x] Cobertura final: **99 de 99** (96 con la ruta literal en el test, 3 con URL parametrizada).
- **Nota**: el medidor distingue tres estados —ruta literal, URL parametrizada
  (`f"/api/v1/admin/reports/{informe}.pdf"`, que sí ejercita el endpoint pero no
  se puede emparejar) y sin cobertura— para no dar por cubierto algo que no lo
  está, ni alarmar por algo que sí lo está.
- **Hasta dónde da el medidor**: además de "¿tiene test?", el script informa de
  "¿tiene un test que compruebe el 401/403?". Ese segundo dato sale
  **indicativo**, con falsos positivos: muchos tests comprueban la denegación
  construyendo la URL en una variable (`for ruta in ("/plazas", "/tickets")`),
  así que el emparejamiento literal no las ve. Por eso la puerta del script es
  "todo endpoint tiene algún test" (99 de 99), no la de denegación.
- **Y en el CI**: el job de integración ejecuta ahora
  `python ../tools/verificar_api_doc.py`, que compara **la sección 3 entera**
  (no sólo las rutas: también la columna "Quién" con el ámbito de datos) con lo
  que genera el código. Así el inventario no puede volver a quedarse atrás sin
  que el CI lo diga. Al añadir la comparación completa salió un fallo real: el
  orden de los ámbitos no era determinista (venía de un `set`), así que la
  sección generada podía cambiar entre ejecuciones. Corregido ordenando.
- **Validado**: `actionlint` sobre el workflow (exit 0) y el comando exacto
  del CI ejecutado desde `backend/`, que es el `working-directory` del job.

### T-25+3 · P2 — los modelos y las migraciones contaban dos historias distintas

- **Estado**: **completado** — deriva cerrada, migración `0014` y comprobación en el CI
- **Contexto**: no estaba en el plan. Salió al ejecutar `alembic check` (la herramienta estándar para comparar los modelos con el esquema) y descubrir dos cosas:
  1. **`alembic check` no servía para nada**: comparaba los modelos contra la base ENTERA, incluidas las tablas TIGER/Line que trae la imagen de PostGIS y la geometría que crea `infra/seed.sql`. Faltaba el `include_object` que filtra por las tablas del proyecto.
  2. **Con el filtro puesto, la deriva real era de 8 puntos, en los dos sentidos**:
     - Los modelos declaraban `index=True` en `cameras.code`, `parking_spaces.number`, `camera_geofences.parking_space_id` y `tickets.parking_space_id`, y **ninguna migración creó esos índices**: se crearon las columnas y ya. Sin índice, cada listado es un Seq Scan.
     - La migración inicial (0001) creó en las columnas con unicidad *las dos cosas*: la restricción `UNIQUE` (`users_email_key`…) **y** un índice único (`ix_users_email`…). El modelo, con `unique=True, index=True`, produce **sólo** el índice. La base arrastraba cuatro restricciones de sobra.
  3. Y al revés: las migraciones 0007 y 0008 crearon `ix_audit_logs_user_id_created_at` e `ix_audit_logs_created_at` **a propósito** (son consultas de auditoría), pero el modelo no los declaraba → `alembic check` quería borrarlos.
- **Lo que habría pasado si nadie lo miraba**: `alembic check` fallaba, así que el siguiente que autogenerase una migración se habría llevado por delante un `DROP CONSTRAINT` de las cuatro unicidades: **emails, matrículas y códigos habrían dejado de ser únicos** sin que nadie se enterase. Por eso la migración va escrita a mano, con un `downgrade` que las restituye.
- **Criterios de aceptación**:
  - [x] `alembic/env.py` filtra la comparación: sólo las tablas del proyecto, y ni `parkings.geom` ni su índice espacial (los crea `infra/seed.sql`).
  - [x] Los tres índices que las migraciones crearon a propósito están declarados en los modelos.
  - [x] Migración `0014_indices_y_uniques`: crea los 4 índices que faltaban y quita las 4 restricciones `UNIQUE` redundantes. **La unicidad no se pierde**: la garantiza el índice único, comprobado insertando un email duplicado (rechazado con `ix_users_email`).
  - [x] `alembic upgrade head` sobre una base **vacía** aplica las 14 migraciones sin error, y `alembic check` responde *No new upgrade operations detected*.
  - [x] El `downgrade` de la 0014 se probó (restaura las restricciones y quita los índices) y se vuelve a subir.
  - [x] **El CI lo vigila**: los tests crean el esquema con `create_all`, es decir, **no ejecutan las migraciones** (una migración rota sólo se habría visto en producción). El job de integración ahora levanta una base vacía, migra de cero y comprueba que el esquema coincide con los modelos.
- **Nota**: `alembic check` sólo funciona contra PostgreSQL (las migraciones usan `CREATE EXTENSION postgis`).

### T-25+4 · P2 — nadie había probado un despliegue limpio de verdad

- **Estado**: **completado** — smoke test en local y en el CI
- **Contexto**: las migraciones se ejecutaban sobre la base de QA (que ya estaba sembrada) y el seed se ejecutaba a mano, pero **nunca los tres juntos sobre una base vacía**. Un despliegue roto —una migración que no aplica sobre el esquema limpio, o un seed que usa una columna que ya no existe— sólo se habría visto en el primer cliente.
- **Criterios de aceptación**:
  - [x] `tools/verificar_despliegue_limpio.py`: crea una base **vacía**, la migra de cero, la siembra, levanta la aplicación y comprueba que la API responde con los datos del seed. Borra la base al terminar.
  - [x] Resultado medido: 14 migraciones aplicadas, seed completo (5 parkings × 60 plazas, 4 usuarios, 3 planes, 5 tarifas, 2 membresías) y la API respondiendo (login 200, `/parkings` 5, `/plans` 3, `/users` 4, resumen de tickets 200).
  - [x] El seed es **idempotente**: ejecutarlo dos veces da los mismos recuentos.
  - [x] El CI lo ejecuta en el job de integración.
- **Nota**: el script usa `psycopg` (que ya es dependencia del backend) y no `psql`, para que no dependa de que el cliente esté en la imagen.

### T-25+5 · P2 — la infraestructura del compose quedaba expuesta en la red de la sucursal

- **Estado**: **completado** — puertos en loopback y arranque bloqueado con el secreto de ejemplo
- **Contexto**: salió al revisar la higiene de un repositorio **público** (búsqueda de secretos en el árbol y en el historial). Dos cosas:
  1. **La superficie de red**: el `docker-compose.yml` del repo **es** el que se copia a una sucursal (ADR-0001, opción D: Compose en el edge). Publicaba Postgres (`5432:5432`, con la contraseña `parking` escrita en el repo) y **Redis (`6379:6379`, sin contraseña ninguna**, y ahí vive la blacklist de tokens y el estado de sesión), además de OCR, detector, Loki y Grafana (con `admin/admin`). Todo en `0.0.0.0`: cualquiera de la red de la sucursal podía leer la base de datos entera, invalidar tokens ajenos o mirar los logs.
  2. **El secreto JWT**: `JWT_SECRET: ${JWT_SECRET:-change-me-in-production}`. Si a una sucursal se le olvidaba la variable, la API firmaba los tokens con un secreto público: se podía fabricar el token de un administrador.
- **Criterios de aceptación**:
  - [x] La infraestructura (db, redis, ocr, vehicle-detector, loki, grafana) se publica **sólo en loopback**. La API (8000) y el frontend (5173) siguen publicados: el central y los dispositivos de la sucursal los necesitan.
  - [x] **Comprobado**: desde la IP de la red local los puertos 5432, 6379 y 3000 ya no responden; desde el host, sí. Los servicios se siguen hablando por la red de Docker.
  - [x] La aplicación **se niega a arrancar** en `staging`/`production` con el secreto de ejemplo (10 tests nuevos en `tests/test_config_seguridad.py`). En `development` y `test` no se comprueba: el equipo de QA usa ese valor a propósito.
  - [x] Documentado en el ADR-0001, con la tabla de qué puerto necesita quién.
- **Lo que queda para el despliegue real** (follow-up ya anotado en el ADR):
  el `docker-compose.prod.yml` con los valores por entorno (`JWT_SECRET`,
  `CORS_ORIGINS` correctos para el host de la sucursal) y el script de
  alta `infra/deploy/branch.sh`.

### T-25+6 · P3 — dos fallos que sólo aparecían fuera del contenedor

- **Estado**: **completado** — corregidos y verificados en los dos entornos
- **Contexto**: salieron al **ejecutar el job de integración del CI en local**, leyendo el workflow (herramienta nueva `tools/ejecutar_ci_local.py`). La QA y la suite se habían hecho siempre dentro del contenedor, que tiene dos diferencias con el portátil del equipo: la zona horaria (UTC) y la resolución de nombres de Docker.
- **Los dos fallos**:
  1. **Una cámara sin URL de RTSP hacía escupir aserciones de OpenCV.** Con la URL vacía, `cv2.VideoCapture` revienta con una aserción de C++ ("!_filename.empty()") cada vez que se abre: en el sondeo del heartbeat, en el preview y en la captura de un frame. El alta ya lo impedía (`CameraCreate.rtsp_url`, `min_length=8`), pero **el PATCH no**: `CameraUpdate.rtsp_url` no tenía ninguna restricción, así que un `PATCH {"rtsp_url": ""}` dejaba la cámara rota **para siempre** en la BD (y con ella el heartbeat, que además abría una alerta de "cámara caída").
     - El esquema del PATCH ahora exige lo mismo que el alta.
     - Además, los tres servicios que abren la captura comprueban la URL antes de llamar a OpenCV y devuelven el fallo de forma limpia (por si queda alguna cámara sin URL de antes, o escrita a mano en la BD).
  2. **Un test del heartbeat sólo pasaba si la máquina estaba en UTC.** El heartbeat guarda `datetime.now(timezone.utc)` y el test comparaba ese valor (naive) con `datetime.now()`, que es la hora **local**: con un desfase de una o dos horas, la aserción "age < 5 s" fallaba con *"last_heartbeat_at demasiado antiguo"*. En CI y en el contenedor pasaba (los dos en UTC), así que el falso rojo sólo se veía al ejecutar la suite en el portátil del equipo. Ahora la comparación es UTC contra UTC.
- **Herramientas nuevas que lo destaparon**:
  - `tools/ejecutar_ci_local.py`: ejecuta un job del workflow **leyendo el YAML** (no duplicando los pasos), con su `working-directory` y sus variables → comprueba el cableado real, no sólo los comandos.
  - `tools/revisar_esquemas.py`: busca asimetrías de validación entre los esquemas `Create` y `Update`. Ahora no hay ninguna (el `rtsp_url` era la única).
- **Criterios de aceptación**:
  - [x] El PATCH de una cámara rechaza una URL vacía o demasiado corta (8 tests nuevos en `tests/test_camara_sin_url.py`).
  - [x] Con la URL vacía, el preview, el heartbeat y la captura fallan de forma limpia, sin llamar a OpenCV.
  - [x] El test del heartbeat pasa en el host (UTC+2) **y** en el contenedor (UTC).
  - [x] Ninguna asimetría Create/Update en los esquemas.

### T-26 · P1 — la alerta de "cámara caída" nunca enviaba el correo al administrador

- **Estado**: **completado** — corregido, con test que demuestra el fallo
- **Contexto**: no estaba en el plan. Salió al leer la salida de `mypy app` (que el CI no ejecuta de verdad desde hace meses, así que nadie lo había visto): `app/services/email.py:193: error: Name "_render_camera_offline" is not defined`.
- **El bug**: desde el sprint CAMERA_OFFLINE (2026-07-01) existen las plantillas `alerts/camera_offline.{txt,html}.j2`, pero **la función que las renderiza nunca se definió**. `send_alert_email` la llamaba, el `NameError` lo capturaba el `except` general, y la función devolvía `False` con un `log.warning`: **la alerta de cámara caída se guardaba en la BD pero el correo al administrador no salía nunca**. En silencio, y con la alerta ya visible en el panel, así que nadie se enteraba.
- **Por qué no lo detectaron los tests**: todos los tests de alertas **simulan** `send_alert_email` con `monkeypatch` (justo la función que contenía el bug), así que nunca entraban en el renderizado. El `noqa: F821` que llevaba el código silenciaba al linter para que el CI no bloqueara.
- **El arreglo**:
  - Se implementa `_render_camera_offline` en `app/services/email.py`, con el mismo patrón que `_render_ocr_failed` y el mismo contexto que la plantilla ya pedía (`alert_id`, `camera_code`, `parking_name`, `severity`, `count`, `threshold`, `detected_at`, `dashboard_url`).
  - Se retira el comentario que lo daba por pendiente y el `noqa: F821`.
  - `mypy app` baja de 78 a 77 errores y el `NameError` desaparece.
- **Criterios de aceptación**:
  - [x] `_render_camera_offline` existe y renderiza las dos plantillas.
  - [x] `send_alert_email(..., template_kind="camera_offline")` devuelve `True` (antes `False`).
  - [x] Test nuevo `backend/tests/test_email_templates.py` (6 tests) que llama al código **real** en modo dry-run, sin simular `send_alert_email`.
  - [x] El test **detecta el defecto**: ejecutado contra el código anterior, fallan 3 de los 6 (con la corrección, pasan los 6).
  - [x] Un test comprueba que **cada** `template_kind` tiene su fichero de plantilla en disco, para que añadir un tipo sin plantilla no falle en runtime.
  - [x] La suite completa sigue en verde.

### T-27 · P2 — `/health` decía "ok" con la base de datos o Redis caídos

- **Estado**: **completado** — endpoint de readiness nuevo y healthcheck del contenedor corregido
- **Contexto**: tampoco estaba en el plan. Salió al usar `tools/verificar_despliegue_limpio.py`: la app arrancaba, `/health` respondía 200 y el script daba por hecho que todo estaba bien; a continuación el login y `/parkings` devolvían **401 con *"Servicio de autenticación no disponible"***. La causa: **Redis no era alcanzable** desde donde corría el script.
- **El hueco**: `GET /health` devolvía `{"status": "ok"}` **sin comprobar nada**. O sea:
  - con la **base de datos** caída, el contenedor se declaraba sano y todo endpoint que tocara la base devolvía 500;
  - con **Redis** caído, el `AuditMiddleware` va a *fail-closed* (es lo correcto: si no se puede consultar la blacklist de tokens, no se deja pasar ningún token) y **toda** petición autenticada devolvía 401. El contenedor, en ambos casos, decía "healthy" y el operador no tenía ni una pista.
- **El arreglo**: la distinción estándar entre *liveness* y *readiness*.
  - `GET /health` → **liveness**: ¿el proceso vive? Siempre 200. A propósito **no** comprueba dependencias: un health check que dependa de la base reinicia el proceso cuando una dependencia falla, y eso convierte un fallo de red en un bucle de reinicios.
  - `GET /health/ready` → **readiness** (nuevo): comprueba de verdad la base de datos (`SELECT 1`) y Redis (`PING`) y responde **503** con el detalle de cuál falla si alguna no responde.
  - El `HEALTHCHECK` del `Dockerfile` pasa a usar `/health/ready`, así que `docker compose ps` deja de mentir. Nada depende de `condition: service_healthy` del backend, así que esto no puede crear bucles de reinicio.
  - `tools/verificar_despliegue_limpio.py` espera a `/health/ready` (no a `/health`), **aborta en cuanto recibe un 503** en vez de esperar al timeout, y explica que un 401 *"Servicio de autenticación no disponible"* es un fallo de servicio (Redis), no de credenciales.
- **Criterios de aceptación**:
  - [x] `GET /health/ready` devuelve 200 con `dependencies` cuando todo responde, y **503** con el detalle cuando algo falla.
  - [x] `GET /health` sigue siendo liveness (200 siempre) y no mira dependencias.
  - [x] `backend/tests/test_health_ready.py` (8 tests) cubre los dos endpoints y los dos casos de fallo.
  - [x] El `HEALTHCHECK` del `Dockerfile` usa `/health/ready`.
  - [x] `tools/verificar_despliegue_limpio.py` falla **rápido** y con el diagnóstico (verificado con Redis caído: `{"database":"ok","redis":"TimeoutError"}`).
  - [x] El inventario de la API se regenera: **101 rutas** (coincide con el código) y el documento incluye la nueva.
  - [x] La suite completa sigue en verde.

### T-28 · P2 — `mypy` en modo `strict`: de 77 errores a 0, y la puerta del CI deja de tolerarlos

- **Estado**: **completado** — `mypy app` sale con *"no issues found in 107 source files"*
- **Contexto**: el backend estaba en modo `strict` (`[tool.mypy] strict = true`) y el paso del CI llevaba `continue-on-error: true` **desde el primer commit** (*"MVP: todavía hay pocos stubs"*). O sea: 77 errores que nadie miraba, porque el paso que los mostraba era el único que la CI se saltaba. Con el CI remoto muerto desde el 2026-07-07, además, su salida no la leía nadie.
- **Qué se hizo** (32 ficheros, +131/−87):
  - **21 anotaciones que faltaban** (`no-untyped-def`): tipos de retorno y de parámetro.
  - **11 tipos genéricos sin parámetros** (`type-arg`): `dict` → `dict[str, Any]`, `Callable` → `Callable[..., Any]`.
  - **11 `no-any-return`**: `cast(...)` donde la librería no está tipada (passlib, pyjwt, httpx, SQLAlchemy).
  - **14 errores de redis-py**: `Awaitable[Any] | Any` en los tipos de la clase `Redis` (que sirve para el cliente síncrono y el asíncrono). Con `cast(int, ...)` se documenta que el cliente **es síncrono** y el valor **es un int**.
  - **5 decoradores de Celery** sin tipar (`# type: ignore[untyped-decorator]`).
  - **Código muerto eliminado**: el `_ = Ticket` / `_ = Vehicle` del final de `pdf.py` (los imports se usaban de verdad, así que el truco no servía para nada).
  - **Un import en el sitio equivocado**: `UserRole` venía de `app.models.user` (que no lo exporta) y ahora viene de `app.models.enums`, que es donde vive.
  - **`desc(col)` → `col.desc()`** en `api/v1/alerts.py`: en runtime es lo mismo, pero el tipo que devuelve la función no encaja en la firma de `order_by` de SQLAlchemy 2.x.
- **El hallazgo que casi se lleva por delante**: al anotar `request: Request | None = None` en `api/v1/auth.py`, **FastAPI deja de inyectar la request** (sólo lo hace cuando el tipo es exactamente `Request`; con la unión, la toma por un parámetro del cuerpo y el endpoint se rompe). La anotación se dejó como `Request = None` con un `# type: ignore[assignment]` y un comentario que explica por qué. **Un type-checker puede romper la API si se le hace caso sin leer lo que hace el framework.**
- **Criterios de aceptación**:
  - [x] `mypy app` → **0 errores** en modo `strict`.
  - [x] Verde **en los dos entornos**: Python 3.11 (la del CI, con mypy 1.20.2) y Python 3.13 (el del host). El resultado de mypy **depende de la versión** (con 1.20.2 en 3.11 aparecía un error de `order_by` que el host no reportaba), así que se comprobó en los dos.
  - [x] `ruff check app tests` → sin errores.
  - [x] La suite completa sigue en verde: **562 passed** en SQLite y **571** en PostgreSQL.
  - [x] El paso del CI **deja de tolerar** los fallos de mypy (`continue-on-error` fuera), validado con el job replicado en local.
  - [x] `actionlint` exit 0.
- **Qué NO se ha tocado**: la lógica. Todos los cambios son anotaciones, `cast` y dos correcciones de import. El único cambio de comportamiento posible (el `response_model` implícito de `api/v1/incidents.py` al anotar su retorno) lo cubre la suite.

### T-29 · P2 — el simulacro de restauración de backups, automatizado

- **Estado**: **completado** — `python tools/verificar_backup.py` → *SIMULACRO CORRECTO* en 10 s
- **Contexto**: T-12 entregó el `backup.sh`, el `restore.sh` y la retención GFS, y probó la restauración **a mano**. Pero la decisión **D3** fija que el procedimiento se prueba **cada trimestre**, y ese "cada trimestre" era una **checklist en papel** que alguien repasaba y anotaba en un ticket. Entre trimestre y trimestre, un backup roto (passphrase perdida, destino remoto caído, disco lleno) pasaba **meses** sin que nadie se enterara. Y la regla del propio plan es tajante: *"un backup sin restaurar probado no es un backup"*.
- **Qué se ha automatizado** (`tools/verificar_backup.py` + `infra/backup/simulacro.sh`), encadenando lo que ya existía:
  1. `backup.sh` → un volcado cifrado nuevo.
  2. El `.enc` **no es legible en claro** (si `head -c 16` dice `PGDMP`, el backup no está cifrado).
  3. `restore.sh` → restauración en una base limpia, con su verificación.
  4. **El recuento de filas coincide** entre el origen y la restauración (8 tablas).
  5. **`alembic check` contra la base restaurada**: el esquema del backup tiene que ser **el que espera el código de hoy**.
  6. El **backend arranca** contra la base restaurada y `/health` da 200.
  7. Se borra la base de prueba.
- **El paso 5 es el que de verdad duele**: un backup de hace tres meses, restaurado, y la app no arranca porque le falta una columna. Con el simulacro automatizado eso se ve en el momento, no en el trimestre.
- **Por qué corre dentro de un contenedor**: el host no tiene `pg_dump`, `pg_restore` ni `openssl`, y el `pg_dump` tiene que ser **de la misma versión que el servidor** (si no, `pg_restore` falla con *"unsupported version"*). Por eso corre en `postgis/postgis:16-3.4` —la imagen del servidor— dentro de la red de Docker.
- **Lo que el simulacro automático NO sustituye**: la checklist manual sigue siendo obligatoria, porque el automático comprueba que la **cadena** funciona, y el manual comprueba lo que la cadena no puede (que el destino S3 remoto está bien, que la passphrase real está en el gestor de secretos, que hay una persona responsable). Las dos conviven en `infra/backup/README.md`.
- **Criterios de aceptación**:
  - [x] El simulacro completo pasa: **SIMULACRO CORRECTO en 10 s**.
  - [x] El volcado se comprueba cifrado (no legible en claro).
  - [x] La base restaurada tiene **los mismos recuentos** que la original.
  - [x] `alembic check` verde contra la base restaurada.
  - [x] El backend arranca contra ella y `/health` da 200.
  - [x] La base de prueba se borra al terminar.
  - [x] Entra en la puerta del repo: `python tools/verificar_repo.py` lo comprueba en el modo rápido.
  - [x] La checklist manual sigue documentada (no se elimina el simulacro trimestral en papel).

### T-30 · P2 — el linter del frontend no existía (el script estaba roto y el CI no lo ejecutaba)

- **Estado**: **completado** — `npm run lint` sale con **0 problemas** y es una puerta del CI
- **Contexto**: el `package.json` del frontend definía un script `lint` (`eslint --ext .ts,.vue src`) que **nunca funcionó**: ESLint 9 exige un `eslint.config.js` (config plano) y **en el repo no había ninguno**. Y el job `frontend` del CI **no ejecutaba el linter**, así que el script roto pasó desapercibido. El backend sí tenía linter (`ruff`) desde el principio: la asimetría era de origen, no de decisión.
- **Qué se ha hecho**:
  - `frontend/eslint.config.js`: configuración plana con `js.configs.recommended` + `pluginVue.configs['flat/essential']` + `vueTsConfigs.recommended`.
  - Se usa **`flat/essential`**, no `flat/recommended`: "recommended" arrastra reglas de **formato** (una etiqueta por línea, un atributo por línea) que son opinión y que obligarían a reformatear el frontend entero (1 425 avisos). Con "essential" el linter avisa de lo que está **mal**, no de lo que está escrito de otra manera.
  - Se añade el paso **"Linter (eslint)"** al job `frontend` del CI, validado con el job replicado en local: *"El job 'frontend' pasa entero en local"*.
- **Lo que el linter encontró al activarlo (5 errores + 1 aviso, todos reales)**:
  - `api/gestorOps.ts`: el parámetro `labels` de `filterMovements` **no se usaba** dentro de la función (el caller lo pasaba). Código muerto: se quitó el parámetro y el argumento.
  - `views/gestor/MovementsView.vue`: `const ui = useUiStore()` **sin usar** (ni en el script ni en la plantilla). Restos de una iteración anterior: se quitó el import y la constante.
  - `views/gestor/CalibrateView.vue`: un `// eslint-disable-next-line no-console` **obsoleto** (la regla no se disparaba): se quitó.
  - `env.d.ts`: el shim estándar de Vue (`DefineComponent<{}, {}, any>`) dispara la regla de "objeto vacío". Se apaga **sólo** en `*.d.ts`, con un comentario que explica por qué.
- **Criterios de aceptación**:
  - [x] `npm run lint` → **0 problemas** (0 errores, 0 avisos).
  - [x] `vue-tsc --noEmit` → 0 errores (sigue en verde tras tocar los ficheros).
  - [x] El paso "Linter (eslint)" está en el job `frontend` del CI y el job replicado en local pasa entero.
  - [x] `actionlint` exit 0.
  - [x] La QA visual sigue en verde (21 pantallas × 5 anchos, 0 desbordes) tras tocar `MovementsView.vue` y `CalibrateView.vue`.
  - [x] La configuración usa `flat/essential`: el linter no exige reformatear el código.

### T-31 · P2 — hook de commit: el texto corrupto no vuelve a entrar por la puerta de atrás

- **Estado**: **completado** — probado en los dos sentidos (bloquea lo sucio, deja pasar lo limpio)
- **Contexto**: el escáner de texto es un paso del CI desde T-13+10, pero **el CI no corre en este repositorio** (la facturación de la cuenta lo bloquea desde el 2026-07-07). Es decir: la puerta contra la corrupción de texto llevaba días sin efficacy. Y la corrupción había llegado al commit **cuatro veces en un solo día**; una de ellas tocó un identificador de JavaScript y dejó una vista en blanco con un 500.
- **Qué se ha hecho**: `.githooks/pre-commit` escanea **los ficheros que se van a versionar** y rechaza el commit si detecta texto corrupto, indicando fichero, línea y carácter sospechoso.
  - Se filtra por **extensión** antes de escanear: el escáner da un falso positivo con un binario (un PNG no es UTF-8 válido) y eso bloquearía commits de imágenes legítimas.
  - El detalle se lee del **informe UTF-8** que deja el escáner, no de su salida por consola (que en Windows se come los acentos).
- **Cómo se activa** (una vez por clon): `git config core.hooksPath .githooks`. Está documentado en el README raíz y en `tools/README.md`. Para saltarlo: `git commit --no-verify`.
- **Criterios de aceptación**:
  - [x] Con un fichero corrupto en el índice, el commit **se rechaza** (código 1) con el fichero, la línea y el carácter señalados.
  - [x] Con un fichero limpio, el commit **pasa** (código 0).
  - [x] Los ficheros binarios no bloquean el commit.
  - [x] Documentado cómo activarlo en los dos README.

### T-32 · P1 — los scripts de backup no eran ejecutables: en Linux no habría backups

- **Estado**: **completado** — los tres scripts versionados con modo `100755`
- **Contexto**: tampoco estaba en el plan, y salió al mirar los modos en el índice de git al añadir el hook de commit. Los tres scripts de `infra/backup/` (`backup.sh`, `restore.sh` y el nuevo `simulacro.sh`) estaban versionados con modo **100644** (sin bit de ejecución).
- **Por qué es un P1**: el procedimiento documentado los invoca **directamente**:
  - el `cron` de backups: `17 3 * * * root ... /opt/solidapp/infra/backup/backup.sh >> ...` → **`Permission denied`** en un despliegue Linux;
  - la restauración: `./restore.sh --file ... --target-db ...` → ídem.
  Es decir: **en un despliegue real en Linux no se habría hecho ni un solo backup**, y el único indicio sería la alerta de "no hay ningún backup". En el entorno de desarrollo (Docker, `sh script.sh`) no se nota, por eso pasó inadvertido.
- **El arreglo**: `git update-index --chmod=+x` para los tres scripts (es el modo del **índice** el que viaja al clon; en Windows el bit local no se conserva porque `core.filemode` es `false`).
- **Criterios de aceptación**:
  - [x] `git ls-files -s` muestra los tres scripts con modo `100755`.
  - [x] No hay más scripts `.sh` en el repo con el modo equivocado (comprobado: son los tres).

### T-33 · P2 — cuatro servicios sin healthcheck: el stack nunca aparecía "todo healthy"

- **Estado**: **completado** — los **11 servicios** del stack aparecen `(healthy)`
- **Contexto**: la definición de hecho del plan dice *"docker compose up -d → **todos los servicios healthy**"*, pero `docker compose ps` mostraba el frontend, Loki, promtail y Grafana **sin** estado de salud: esos cuatro servicios **no tenían healthcheck**. O sea que el criterio se daba por cumplido sin que nada lo comprobara.
- **Qué se ha añadido** (y por qué cada probe es el que es):

  | Servicio | Probe | Motivo |
  |---|---|---|
  | `frontend` | `wget http://127.0.0.1:5173/` | El dev-server de Vite *es* la app. La imagen es `node:20-alpine`: `wget` de busybox, no `curl` |
  | `loki` | `wget http://127.0.0.1:3100/metrics` | **El `/ready` de Loki devuelve 503 aunque esté perfectamente en pie**, así que no sirve. `/metrics` responde 200 mientras el servidor HTTP esté vivo, que es lo que debe comprobar un healthcheck |
  | `promtail` | `grep -q promtail /proc/1/comm` | Promtail no expone endpoint HTTP (empuja logs) y su imagen **no trae `wget` ni `pgrep`**. Lo comprobable es que el proceso del contenedor siga siendo el promtail |
  | `grafana` | `wget http://127.0.0.1:3000/api/health` | Responde 200 con el estado de su base de datos |

- **Criterios de aceptación**:
  - [x] `docker compose config` sigue siendo válido.
  - [x] `docker compose up -d` levanta el stack y **los 11 servicios aparecen `(healthy)`**.
  - [x] La app sigue funcionando tras recrear los contenedores (QA visual en verde).

### T-34 · P2 — auditoría de la "definición de hecho": cifras obsoletas y una deriva silenciosa

- **Estado**: **completado** — todas las cifras contrastadas con comandos reales
- **Contexto**: la definición de hecho del plan es el contrato del trabajo, y varios de sus números se habían quedado obsoletos (o no se habían comprobado nunca con el rigor que la propia definición exigía).
- **Lo que salió al auditarla, criterio por criterio**:
  - **Deriva silenciosa**: `docs/API-INTERNAL.md` decía *"100 endpoints"* cuando ya eran **101**. La causa: el número de endpoints de salud estaba **duplicado** en dos herramientas (`verificar_api_doc.py` los sumaba a mano; `generar_seccion_api.py` sumaba `+1` por `/health`), así que al añadir `/health/ready` (T-27) el generador siguió contando uno. **Ahora la lista vive en un solo sitio** (`extraer_api.RUTAS_FUERA_DE_ROUTER`) y las dos herramientas la importan. Comprobado que el aviso funciona: con el generador arreglado, el verificador detectó la deriva (documento=100, código=101) y falló con código 1; tras regenerar, vuelve a pasar, y la autoprueba sigue detectando las dos caras.
  - **Cifras obsoletas**: "530 tests" y "100 endpoints" en el README, "22 routers" en el CODEMAP (son 24), "548/557 passed" en la definición de hecho (ahora 562/571) y un "10 pantallas" que ya se había corregido a 6 en otro sitio del mismo documento.
  - **Criterios que se daban por cumplidos sin comprobar**: *"todos los servicios healthy"* → **faltaban cuatro healthcheck** (T-33) y *"sin 4xx/5xx en el log del backend"* → comprobado ahora contra el log real (145 líneas en 30 min, cero 4xx/5xx).
- **Criterios de aceptación**:
  - [x] Todas las cifras de la documentación contrastadas con comandos reales: **101 endpoints** (en 24 routers), **19 modelos**, **562 tests**, **11 servicios healthy**.
  - [x] La lista de rutas fuera de los routers tiene **una sola fuente** (`extraer_api.RUTAS_FUERA_DE_ROUTER`).
  - [x] El verificador de la API **detecta** la deriva en la prosa (probado: falla con código 1 si el documento no se regenera).
  - [x] La autoprueba del verificador sigue en verde.

### T-35 · P1 — el inventario de la API documentaba como "Público" 9 endpoints que exigen admin

- **Estado**: **completado** — el RBAC del documento coincide con el código
- **Contexto**: auditando la columna **"Quién"** de `docs/API-INTERNAL.md` (el contrato que lee quien integra la API) contra el código, los 9 endpoints de `/plans` aparecían como **"Público"**: el catálogo de planes, el alta y el borrado de planes, las suscripciones y "mi plan". En el código, **todos exigen autenticación** y casi todos son **de admin**.
- **Por qué pasaba**: `tools/extraer_api.py` sacaba las dependencias de FastAPI **sólo del valor por defecto** del parámetro (`x: User = Depends(...)`). El idioma moderno es **en la anotación** (`x: Annotated[User, Depends(require_role(...))]`), y ese camino no se miraba. Encima, el bucle de los posicionales recorría únicamente los parámetros **que tenían valor por defecto**, así que los que llevan la dependencia en la anotación ni siquiera se visitaban.
- **Por qué nadie lo vio**: el verificador (`tools/verificar_api_doc.py`) compara el **conjunto de rutas**, que no había cambiado: 9 endpoints "Público" y 9 endpoints con el RBAC correcto dan el mismo juego de rutas. La deriva estaba en la **columna**, y nadie la miraba porque el gate no la cubría.
- **El arreglo**:
  - `extraer_api.py` mira **las dos** formas (valor por defecto **y** anotación `Annotated[...]`), y recorre **todos** los parámetros, no sólo los que tienen default.
  - `verificar_api_doc.py --autoprueba` tiene ahora una **tercera** cara: cambiar el "Quién" de una fila debe detectarse. Antes sólo comprobaba que se detectara añadir y quitar rutas.
- **Criterios de aceptación**:
  - [x] Los 9 endpoints de `/plans` documentan su RBAC real (`require_role('admin')` / `require_role('admin', 'cliente')`).
  - [x] Los 7 endpoints que **sí** son públicos siguen marcándose como tal: login, login OAuth, refresh, forgot-password, reset-password y los dos de salud. Comprobado contra el código.
  - [x] La autoprueba detecta las **tres** caras de la deriva (quitar ruta, añadir ruta inexistente y cambiar el RBAC).
  - [x] El documento regenerado y el verificador en verde.

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
- **Pendiente de frontend**: RESUELTO al cierre de la sesión. La pantalla `/recuperar-contrasena` (pública, con o sin `?token=`) ya existe: con token muestra el formulario de contraseña nueva; sin token, el de "envíame el enlace". Verificada con la QA visual en Chromium (las dos variantes renderizan, 0 errores de consola) y contra el backend real (`forgot-password` → 200 con el mensaje genérico; `reset-password` con token falso → 400 con mensaje claro).

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
9. **Cerrar el preview congelaba el backend y bloqueaba la cámara**:
   el teardown del RTSP corría en el hilo del event loop (hasta 5 s con la
   cámara colgada) y el slot de la cámara se liberaba **después** de ese
   teardown, así que reabrirla daba 409. Además, `release()` no identificaba
   la sesión y el `finally` de un generador viejo podía matar el stream de un
   cliente nuevo (T-13+6).

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

> **La puerta que manda mientras el CI remoto no arranque** (facturación):
> `python tools/verificar_repo.py` corre todo lo de esta lista en un
> comando y devuelve 0/1. Con `--completo` añade el CI replicado en local
> y la QA visual en los cinco anchos. Es la red de seguridad del repo
> mientras GitHub no ejecute nada.

- [x] `cd backend && ruff check app tests` → sin errores.
- [x] `cd backend && mypy app` → **sin errores** (modo `strict`). Antes daba 77 y su paso iba con `continue-on-error: true`; ver T-28.
- [x] `docker exec parking-backend-1 pytest -q` → 265 passed, 0 failed (o más, nunca menos). → **562 passed en SQLite y 571 en PostgreSQL**.
- [x] `docker compose up -d` → todos los servicios *healthy* y `/health` responde 200.
- [x] QA visual en el navegador de las pantallas tocadas (con la app real, no sólo tests).
      → **HECHA** con Chromium headless (Playwright) sobre la app real
      (`frontend/scripts/qa_visual.py`): las **21 pantallas** de los tres
      roles se renderizan, **0 errores de consola** y **0 peticiones de red
      fallidas**. Se revisaron una a una las capturas: catálogo de planes,
      mi plan, mis vehículos, mi perfil, mi plaza, pagos, entradas/salidas,
      alertas, operadores, tickets, mapa, cámaras, vivo y alta manual.
      La QA destapó un defecto visual: el aviso de cobro contable se leía
      "Cobro contable. Cobro contable: ..." (la etiqueta se anteponía a un
      texto que ya empezaba así). Corregido.
      → La QA se ha ampliado desde entonces: recorre además **5 anchos**
      (414, 768, 1024, 1232 y 1440 px) y **detecta el contenido que no cabe**
      (recortado o desbordado), lo que destapó 6 defectos de maquetación
      (T-13+7 y T-13+8) y, al añadir el ancho de móvil, otros 26
      desbordes repartidos en **6 pantallas** —3 de ellas con la página
      entera desplazable— (T-13+9). También hay `frontend/scripts/qa_pwa.py`, que
      verifica que el PWA es instalable y arranca sin red.
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
