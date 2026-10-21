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

- **Estado**: pendiente (código listo y verificado, sin commitear)
- **Contexto**: `git status` muestra 8 ficheros modificados. 3 los dejó esta sesión (`Dockerfile`, `stream.py`, `ticket_summary.py`), 3 venían sin commitear de antes (`cameras_live.py`, `middleware.py`, `live_streams.py`) y 2 son de tests (`test_vehicle_detector.py`, `test_dashboard_kpis.py`).
- **Resultado esperado**: la rama `feat/live-preview-cameras` contiene los arreglos, con un mensaje de commit que explique **por qué** (no sólo qué): el bug del modal negro, el 500 de Postgres y el middleware que anulaba la auditoría y la blacklist.
- **Criterios de aceptación**:
  - [ ] `git status` limpio (salvo lo que se decida explícitamente).
  - [ ] `pytest -q` → 265 passed.
  - [ ] `ruff check app tests` → sin errores.
  - [ ] El mensaje de commit menciona los tres bugs de producción, no sólo "fix".
- **Cómo verificarlo**: `cd backend && ruff check app tests && docker exec parking-backend-1 pytest -q`
- **Depende de**: nada. **Es el primero de todos.**
- **Ficheros**: `backend/Dockerfile`, `backend/app/api/v1/cameras_live.py`, `backend/app/core/middleware.py`, `backend/app/services/cameras/live_streams.py`, `backend/app/services/cameras/stream.py`, `backend/app/services/ticket_summary.py`, `backend/tests/test_dashboard_kpis.py`, `backend/tests/test_vehicle_detector.py`

### T-02 · Cerrar el CI rojo de PR #14

- **Estado**: causa raíz identificada, fix aplicado, falta push
- **Contexto**: `gh pr checks 14` → *Backend (ruff, mypy, pytest)* = **FAIL**, Frontend = OK. El CI empezó a fallar en `007c8ad` y siguió en `5848c13` y `20f6cac`. El paso que falla es **`ruff check app tests`** (por eso `pytest` ni siquiera llega a ejecutarse): 2 × `F401` en `backend/tests/test_vehicle_detector.py` (líneas 22 y 26: `get_vehicle_detector_client` y `_login` importados y nunca usados — el test los parchea por *string* vía `monkeypatch`).
- **Resultado esperado**: el job "Backend (ruff, mypy, pytest)" del PR #14 pasa en verde.
- **Criterios de aceptación**:
  - [ ] `ruff check app tests` → *All checks passed!*
  - [ ] `mypy app` no empeora (hoy va con `continue-on-error: true`).
  - [ ] `gh pr checks 14` → todos los checks en SUCCESS.
- **Cómo verificarlo**: `cd backend && ruff check app tests && gh pr checks 14`
- **Depende de**: T-01 (el fix está en `test_vehicle_detector.py`, sin commitear).

### T-03 · Cerrar PR #13 (R5) y PR #14 (live preview)

- **Estado**: pendiente
- **Contexto**: hay **dos PR abiertos** contra `main`: #13 (`feat/r5-sidebar-reorder-change-pass`, CI verde) y #14 (`feat/live-preview-cameras`, CI rojo). La rama actual está 10 commits por delante de `main` (26 ficheros, +3026/−73) y **mezcla tres trabajos distintos**: rate-limit R5, live preview MJPEG y vehicle-detector.
- **Resultado esperado**: PR #14 en verde y mergeado a `main`; PR #13 cerrado por merge o por rebase, sin dejar trabajo a medias.
- **Criterios de aceptación**:
  - [ ] PR #14: CI verde y `main` con la rama integrada.
  - [ ] PR #13: cerrado con su contenido en `main` (o descartado explícitamente).
  - [ ] `git log main --oneline` incluye los commits de R5 y de live preview.
- **Depende de**: T-01, T-02.

### T-04 · Que los tests se ejecuten contra Postgres, no siempre contra SQLite

- **Estado**: pendiente — **es la causa raíz de que un 500 en producción pasara el CI**
- **Contexto**: `backend/tests/conftest.py:7` hace `os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")` y las líneas 25-29 crean el motor **hardcodeado** a `sqlite+pysqlite:///:memory:`. El job de CI levanta un Postgres real (`.github/workflows/ci.yml`, servicio `postgis/postgis:16-3.4`) → **nunca se usa**. Consecuencia medida: el `strftime()` de SQLite se coló en `ticket_summary.py` y llegó a `main` (commit `568a062`) porque los tests pasaban; en Docker devolvía 500 (`function strftime(character varying, timestamp with time zone) does not exist`).
- **Resultado esperado**: existe una vía de test que ejecuta la suite contra Postgres, y cualquier función SQL dependiente del dialecto queda cubierta por ella.
- **Criterios de aceptación**:
  - [ ] `conftest.py` parametrizable por variable de entorno (`TEST_DATABASE_URL`), con SQLite como default local y Postgres en CI.
  - [ ] El job de CI ejecuta **al menos una vez** la suite contra el Postgres que ya levanta (o un job nuevo `integration`).
  - [ ] Existe un test explícito que falle si alguien vuelve a usar una función sólo de SQLite (p. ej. buscar `strftime(` en el código de aplicación).
  - [ ] `pytest -q` sigue verde en ambos motores.
- **Cómo verificarlo**: `docker exec parking-backend-1 pytest -q` (SQLite) y `DATABASE_URL=postgresql+psycopg://… pytest -q` (Postgres).
- **Depende de**: T-01.

### T-05 · Verificar el build de la imagen de backend en CI

- **Estado**: código corregido (T-01), falta cobertura en CI
- **Contexto**: el `Dockerfile` estaba roto desde hacía tiempo: `RUN mkdir -p /var/log/solidapp` **después** de `USER app` ⇒ `Permission denied` (el directorio `/var/log` es `root:root`). El `| tail -40` del comando de build **se tragaba el exit code**, así que el fallo pasaba desapercibido. Además, el job de CI **no construye la imagen**: instala el paquete con `pip install -e ".[dev]"`, así que el `Dockerfile` puede volver a romperse sin que nadie se entere.
- **Resultado esperado**: `docker compose build` de backend y frontend funciona en local **y** hay un paso en CI que construye las imágenes (o al menos un `docker build` de humo).
- **Criterios de aceptación**:
  - [ ] `docker compose build backend frontend` → 0 (con `set -o pipefail` o sin `| tail`).
  - [ ] `/var/log/solidapp/backend.log` existe y el `RotatingFileHandler` escribe (con el usuario no-root `app`).
  - [ ] CI tiene un paso de build de imagen (o documenta explícitamente por qué no).
- **Depende de**: T-01.

---

## Bloque 1 — Robustez del live preview y del servicio (P1)

### T-06 · El stream MJPEG bloquea el shutdown de uvicorn

- **Estado**: pendiente — **reproducido en esta sesión**
- **Contexto**: con una vista en vivo abierta en el navegador, `uvicorn --reload` se queda en `Waiting for connections to close` **para siempre**: el generador MJPEG ([backend/app/services/cameras/stream.py](backend/app/services/cameras/stream.py)) sólo termina si el cliente se desconecta (`request.is_disconnected()`) o si `live_streams` activa el `shutdown_event`. Durante un graceful shutdown **nadie activa ese evento**, así que la conexión no se cierra y el backend deja de responder (`/health` → 000, contenedor `unhealthy`). Se reproduce al editar cualquier fichero: reload → cuelgue → hay que `docker restart`.
- **Resultado esperado**: editar código nunca deja el backend colgado; el stream se cierra al apagar el servidor.
- **Criterios de aceptación**:
  - [ ] El generador termina cuando la app entra en shutdown (evento de `lifespan` compartido, o equivalente).
  - [ ] Con una vista en vivo abierta, `touch backend/app/main.py` → el backend vuelve a servir en < 10 s.
  - [ ] `/health` sigue respondiendo 200 tras el reload.
  - [ ] Test de regresión: se abre un stream, se dispara el evento de shutdown y se comprueba que el generador termina en < 2 s.
- **Cómo verificarlo**: abrir el preview en vivo → tocar un fichero → observar los logs del contenedor.
- **Depende de**: T-01.

### T-07 · Fijar el fps objetivo del preview (docstrings vs realidad)

- **Estado**: pendiente (decisión de producto)
- **Contexto**: la documentación de `cameras_live.py` y `stream.py` anuncia **"5 fps (cada 200 ms)"**, pero `FRAME_INTERVAL_S = 0.0` (sprint "Latencia-Mínima") y la medición real da **35 fps / 1,2 MB/s** con primer frame a 1,85 s. El código y los docstrings no coinciden.
- **Resultado esperado**: una cifra de fps **acordada y escrita en el código** (constante efectiva + docstring coherente), o bien un throttle que la respete.
- **Criterios de aceptación**:
  - [ ] Decisión tomada y anotada (5 fps "bonito" vs "tan rápido como la cámara").
  - [ ] Si es 5 fps: `FRAME_INTERVAL_S = 0.2` con la lógica real (no sólo el nombre) y el docstring corregido.
  - [ ] Si es "libre": `FRAME_INTERVAL_S` se elimina y el docstring dice "sin limitador, limitado por la cámara".
  - [ ] El docstring de `cameras_live.py` (línea 13) coincide con el comportamiento.
- **Decisión del usuario**: 5 fps fijo (ahorra ~85 % de ancho de banda y CPU) frente a flujo libre (latencia mínima).

### T-08 · Auditar el login con `user_id`

- **Estado**: pendiente (menor)
- **Contexto**: la auditoría `login_success` se graba **siempre con `user_id=None`**, porque en la request de login no hay header `Authorization` y el `AuditMiddleware` no puede saber quién entra. Se comprobó en vivo: `login_success → user_id=None`, `logout_success → user_id=1`. Con el middleware arreglado (T-01) el resto de auditorías sí llevan `user_id`.
- **Resultado esperado**: la fila de auditoría del login identifica al usuario (el handler ya sabe quién es tras validar la contraseña).
- **Criterios de aceptación**:
  - [ ] `record_audit_from_request` (o `record_audit`) del login incluye `user_id` y `resource="users/{id}"`.
  - [ ] Test que comprueba `user_id is not None` en la fila de `login_success`.

### T-09 · Validar el servicio vehicle-detector de punta a punta

- **Estado**: pendiente — **nunca se levantó en la QA**
- **Contexto**: en esta sesión sólo se levantó el stack *núcleo* (decisión explícita del usuario): db, redis, backend, frontend, celery. El servicio `vehicle-detector` (contenedor propio, Ultralytics YOLO) **no se ejecutó ni una vez**, así que el botón "🔍 Detectar vehículos" sólo se probó en su rama *fail-open* (detector caído → 200 con `[]`).
- **Incoherencias detectadas**:
  - `docker/vehicle-detector/Dockerfile:17` fija `VD_MODEL=yolov8n.pt` mientras `docker-compose.yml:81` usa `VD_MODEL: "best.pt"` (yolov8m fine-tuned en VisDrone). El valor por defecto del Dockerfile está obsoleto.
  - `best.pt` (~50 MB) se descarga de HuggingFace en el arranque: el primer boot es lento y depende de la red externa.
  - El commit `20f6cac` cambió a yolov8m-visdrone; el cliente backend no ha cambiado (mismo contrato `/detect`).
- **Resultado esperado**: el servicio arranca, responde `/health`, y la detección sobre una captura real de cámara devuelve cajas coherentes con las geocercas.
- **Criterios de aceptación**:
  - [ ] `docker compose up vehicle-detector` → healthy.
  - [ ] `VD_MODEL` por defecto coherente entre Dockerfile y compose (y documentado).
  - [ ] Una captura de la cámara de prueba devuelve detecciones no vacías, y las geocercas se marcan en rojo/verde como está previsto.
  - [ ] `best.pt` cacheado en un volumen, y el arranque no lo re-descarga.
  - [ ] El modelo real usado queda registrado en el README del servicio.

### T-10 · Blindar el registro de streams vivos (`live_streams`)

- **Estado**: pendiente
- **Contexto**: `backend/app/services/cameras/live_streams.py` tiene `heartbeat()` **sin lock** y `STALE_AFTER_S = 8.0`. Se verificó el flujo bueno (409 en cliente duplicado, recuperación al cerrar y reabrir) pero no el concurrente.
- **Resultado esperado**: dos clientes simultáneos sobre la misma cámara se comportan de forma determinista (uno recibe 409, el otro ve video), sin condiciones de carrera en el `heartbeat`.
- **Criterios de aceptación**:
  - [ ] `heartbeat()`/`release()` protegidos por `asyncio.Lock`.
  - [ ] Test con dos requests concurrentes a `/live` sobre la misma cámara: exactamente uno 200 y el otro 409.
  - [ ] Test de sesión huérfana (> 8 s sin heartbeat) → la sesión se libera.

### T-11 · Tests de regresión del middleware de autenticación

- **Estado**: pendiente
- **Contexto**: el bug del middleware (T-01) no lo cubría ningún test: los tests de auditoría pasaban con `user_id=None` porque… no lo miraban. Ahora que el fix está aplicado, falta blindarlo.
- **Resultado esperado**: la suite falla si alguien vuelve a anidar mal el parseo del header `Authorization`.
- **Criterios de aceptación**:
  - [ ] Tests para los 4 formatos: `Bearer <tok>`, `bearer <tok>` (minúsculas), `Bearer` (sin token), `Bearer ` (prefijo vacío).
  - [ ] Test que comprueba que `logout` **sí** blacklistea (token reutilizado → 401).
  - [ ] Test que comprueba que la auditoría de una acción autenticada lleva `user_id` (no `None`).

---

## Bloque 2 — Backlog del roadmap (P2)

> Fuente: memoria `roadmap-solidapp` (snapshot 2026-07-06). Verificado contra el código el 2026-10-21: **ninguno** de estos ítems está implementado.

### T-12 · I1 — Backups automatizados (pg_dump + WAL)

- **Contexto**: no hay ningún `pg_dump`, ni archivado de WAL, ni tarea programada de backup en todo el repo. Lo único que se llama "backup" es el `RotatingFileHandler` de logs (`backupCount: 5`), que **no** son backups de datos.
- **Resultado esperado**: dumps automáticos con retención + **procedimiento de restauración probado** (un backup sin restaurar probado no es un backup).
- **Criterios de aceptación**:
  - [ ] Script `pg_dump` diario (retención configurable, p. ej. 7 diarios + 4 semanales + 6 mensuales).
  - [ ] Restauración verificada en una base limpia (documentada paso a paso).
  - [ ] Cifrado en reposo y copia fuera del host (LOPDGDD).
  - [ ] Alerta si el dump falla o si el último backup es más antiguo de X horas.

### T-13 · I2 — Pruebas de carga con Locust

- **Contexto**: no existe ningún `locustfile.py` en el repo. Los objetivos de carga del producto: 50 streams (MVP 5 sucursales × 10 cámaras) y 50+ sucursales en producción.
- **Resultado esperado**: un escenario de carga ejecutable que fije el SLO y detecte regresiones de rendimiento.
- **Criterios de aceptación**:
  - [ ] `locustfile.py` con escenarios: login, mapa en vivo (SSE), cierre de ticket, preview MJPEG.
  - [ ] SLO documentado (p. ej. p95 < 300 ms en lectura; streaming sin cortes).
  - [ ] Informe de una ejecución de referencia con los números guardados en el repo.
  - [ ] Falla si el p95 supera el SLO (integrable en CI aunque sea nocturno).

### T-14 · I3 — OCR con GPU

- **Contexto**: el OCR corre en CPU (PaddleOCR). Con 50+ cámaras el coste de CPU es el cuello de botella declarado.
- **Resultado esperado**: evaluación con números de si la GPU aporta o no, y decisión documentada.
- **Criterios de aceptación**:
  - [ ] Medición CPU vs GPU (latencia por frame, throughput con 50 cámaras).
  - [ ] Recomendación escrita: activar GPU, o descartar con datos.

### T-15 · I4 — Orquestación Swarm/K8s

- **Contexto**: hoy el despliegue es `docker compose` en un único host. La memoria del proyecto describe el objetivo de "50+ sucursales con servidores locales + cluster central HA".
- **Resultado esperado**: decisión de orquestación tomada con criterios (coste, complejidad, equipo).
- **Criterios de aceptación**:
  - [ ] Documento de decisión (ADR) comparando Compose/Swarm/K8s con el escenario real de 50 sucursales.
  - [ ] Si se elige Swarm: stacks de ejemplo para una sucursal y para el central.

### T-16 · P3 — Exportes PDF/CSV de informes

- **Contexto**: hoy hay **CSV** de márgenes (`GET /admin/reports/margins.csv`) y **PDF sólo de ticket** (`app/services/pdf.py` → `render_ticket_pdf`). Los informes de ingresos, ocupación, tickets y alertas no se pueden exportar.
- **Resultado esperado**: exporte de los informes de `ReportsView` en PDF y CSV.
- **Criterios de aceptación**:
  - [ ] `GET /admin/reports/{informe}.pdf` y `.csv` para: ingresos, ocupación, tickets, alertas, márgenes.
  - [ ] Plantilla con la paleta `park` del producto y los datos de la sucursal.
  - [ ] Filtros por fecha y sucursal respetados en el exporte.
  - [ ] Test por endpoint del status, content-type y cabecera `Content-Disposition`.

### T-17 · O2 (seguimiento) — Extender SSE a LiveView y CalibrateView

- **Contexto**: el SSE de eventos (`app/services/event_bus.py` + `useParkingEvents`) **sólo** lo consume `frontend/src/views/gestor/MapView.vue`. El wireframe del Operador (vista en vivo) y el de Calibración no reciben eventos en tiempo real.
- **Resultado esperado**: las vistas de Operador y Gestor-Cámara se actualizan en vivo sin recargar.
- **Criterios de aceptación**:
  - [ ] `LiveView` y `CalibrateView` suscritos al bus de eventos.
  - [ ] Actualización de plazas/incidentes/alertas sin F5.
  - [ ] Reconexión automática si cae el SSE.

---

## Bloque 3 — Módulos de producto (P2-P3, **propuestos — requieren validación**)

> **Origen de estos ítems**: contraste entre los **wireframes aprobados** (memoria `wireframes-solidapp`, 2026-06-30) y lo que existe hoy en `frontend/src/views/` y `backend/app/api/v1/`. Los wireframes son el contrato: si algo no está en ellos, es propuesta nueva y necesita tu visto bueno.

### T-18 · Módulo de Planes y Suscripciones (API + interfaz)

- **Estado**: **a medio construir** — los modelos existen y el descuento se aplica, pero no hay interfaz para gestionarlo
- **Contexto**: `backend/app/models/pricing.py` ya define `Plan` (con `discount_percent`) y `Subscription`, y `app/services/pricing.py` calcula el descuento al cerrar el ticket (`tickets.py:142` → `ticket.discount`). **Pero no existe router `api/v1/plans.py`**: nadie puede crear planes ni suscribir usuarios desde la aplicación, y el seed es lo único que los puebla.
- **Resultado esperado**: el administrador gestiona planes y el gestor/cliente ve su suscripción y su descuento aplicado.
- **Criterios de aceptación**:
  - [ ] `api/v1/plans.py` (CRUD de planes + alta/baja de suscripciones).
  - [ ] Vista admin "Planes" con la lista wireframeada.
  - [ ] Vista cliente "Mi plan" (plan, fecha de alta/vencimiento, % de descuento, próximo cobro).
  - [ ] El ticket cerrado refleja el descuento del plan y es visible en el PDF y en "Mis tickets".
  - [ ] Test: alta de plan → suscripción → cierre de ticket → `discount` = porcentaje esperado.
- **Decisión del usuario**: números definitivos de los planes (Básico 30 €, Familiar 60 €, Empresa 200 €) y si el cobro es real (pasarela) o de momento sólo contable.

### T-19 · Vistas del Cliente: Mis vehículos, Mi perfil

- **Estado**: pendiente — el wireframe del Cliente tiene 4 pantallas y **sólo existe 1** (`cliente/TicketsView.vue`)
- **Contexto**: faltan "Mis vehículos" (la API `vehicles.py` y el modelo ya existen, con la relación N:M `VehiculoUsuario` con rol `propietario|conductor`) y "Mi perfil" (hay endpoint de cambio de contraseña, pero no de datos de perfil).
- **Resultado esperado**: el cliente gestiona sus vehículos (alta, baja, vincular/desvincular como propietario o conductor) y edita su perfil desde la web.
- **Criterios de aceptación**:
  - [ ] Vista "Mis vehículos" con alta/edición y vínculo de roles (propietario/conductor).
  - [ ] Vista "Mi perfil" con nombre, teléfono y cambio de contraseña.
  - [ ] Un conductor ve los tickets de los vehículos que conduce, no los de otros.
  - [ ] Route guards por rol en el router.

### T-20 · Gestor: log de entradas/salidas, alertas activas y operadores

- **Estado**: pendiente — el wireframe del Gestor tiene 7 pantallas y faltan 3
- **Contexto**: existen la API de tickets (filtrable por fecha) y la de alertas, pero **no hay vista** de "Entradas/Salidas (log)" ni de "Alertas activas"; la asignación de operadores a la sucursal se hace desde el CRUD de usuarios del admin, no desde la vista del gestor.
- **Resultado esperado**: el gestor ve el log de movimiento de vehículos de su sucursal, sus alertas activas y gestiona sus operadores sin salir del rol.
- **Criterios de aceptación**:
  - [ ] Vista de entradas/salidas con filtros por fecha, plaza, vehículo y origen (`automatic` / `manual`).
  - [ ] Vista de alertas activas con acción de resolver/ignorar.
  - [ ] Vista de operadores con alta y asignación a la sucursal.
  - [ ] Todo filtrado por sucursal según el RBAC del gestor.

### T-21 · Adjuntos/fotos en incidentes (hasta 3)

- **Estado**: pendiente — el wireframe del Operador pide "formulario de incidente con tipo, plaza y **adjuntos (hasta 3 fotos)**"
- **Contexto**: `api/v1/incidents.py` y el modelo de incidentes **no tienen ningún campo de fichero** (no hay `upload`, ni almacenamiento de objetos). Hoy sólo hay `kind`, `space_id`, `parking_id`, `description`.
- **Resultado esperado**: el operador puede adjuntar hasta 3 fotos al reportar un robo o una avería.
- **Criterios de aceptación**:
  - [ ] Endpoint de subida con validación (tipo MIME, tamaño máximo, hasta 3 ficheros).
  - [ ] Almacenamiento definido (volumen local con nombre por hash; NO base64 en la BD).
  - [ ] Miniaturas y descarga en la vista de incidentes.
  - [ ] Retención y borrado según LOPDGDD (incluido el derecho al olvido).
  - [ ] Sanitización de ficheros (no servirlos como HTML inline).

### T-22 · Recuperación de contraseña del cliente

- **Estado**: pendiente
- **Contexto**: **no existe** flujo de "olvidé mi contraseña" (ni backend ni correo). El login sólo acepta usuario+contraseña. Hoy la única forma de recuperar el acceso es que un admin lo reinicie a mano.
- **Resultado esperado**: el cliente (y el operador) puede recuperar el acceso por correo con un token de un solo uso.
- **Criterios de aceptación**:
  - [ ] `POST /auth/forgot-password` → correo con token de un solo uso y caducidad (p. ej. 30 min).
  - [ ] `POST /auth/reset-password` → cambia la contraseña e invalida los tokens previos.
  - [ ] El token se guarda **hasheado** y se invalida al usarlo.
  - [ ] Plantilla de correo en español (`app/services/templates/`).
  - [ ] Registro de auditoría `password_reset_requested` / `password_reset_completed`.
  - [ ] Anti-abuso: rate-limit por IP y por email.

### T-23 · Tabla y endpoint de reconocimiento facial (preparación)

- **Estado**: pendiente (explícito en la memoria: "fuera del MVP, dejar la tabla y endpoint preparados")
- **Resultado esperado**: la estructura de datos existe, pero **no se usa** para autenticar a nadie.
- **Criterios de aceptación**:
  - [ ] Modelo `FaceTemplate` (usuario, embedding, cámara, fecha) + Alembic.
  - [ ] Endpoint de alta/baja **deshabilitado por feature flag** y sin uso en el login.
  - [ ] Nota explícita en el README: reconocimiento facial fuera del MVP.

### T-24 · Portal/app del cliente final (PWA)

- **Estado**: propuesta mayor — **no está en los wireframes**
- **Contexto**: hoy el "Cliente" es un usuario del mismo frontend con menú propio. No hay app móvil ni portal público. En un parking, el conductor final es quien realmente valoriza el producto (saber si su coche está dentro, cuánto le va a costar, pagar).
- **Resultado esperado**: un PWA instalable para el cliente final con: entrada con matrícula, plaza asignada en tiempo real, ticket y pago.
- **Criterios de aceptación**:
  - [ ] Definir si es PWA responsive o app nativa (recomendación: PWA, un solo codebase).
  - [ ] Pantallas: mis vehículos, mi plaza, mis tickets, pago.
  - [ ] Sin login de gestor: sólo cliente.
  - [ ] Publicación en tiendas de apps (PWA instalable) o al menos APK interno.

### T-25 · API pública para terceros (documentada, no expuesta)

- **Estado**: pendiente (la memoria dice: "En MVP no se expone API pública; se deja documentada la estructura interna")
- **Resultado esperado**: la estructura interna queda documentada y versionada, lista para exponerse cuando se decida (movilidad, autoridades).
- **Criterios de aceptación**:
  - [ ] Documento de la API interna con los recursos y su RBAC.
  - [ ] Versionado (`/api/v1`) ya presente → documentar la política de deprecación.
  - [ ] Sin exposición pública hasta que se firme el modelo de datos y los términos.

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

- [ ] `cd backend && ruff check app tests` → sin errores.
- [ ] `cd backend && mypy app` → sin errores nuevos (hoy `continue-on-error: true`).
- [ ] `docker exec parking-backend-1 pytest -q` → 265 passed, 0 failed (o más, nunca menos).
- [ ] `docker compose up -d` → todos los servicios *healthy* y `/health` responde 200.
- [ ] QA visual en el navegador de las pantallas tocadas (con la app real, no sólo tests).
- [ ] Sin 4xx/5xx inesperados en `docker logs backend` durante la QA.

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
