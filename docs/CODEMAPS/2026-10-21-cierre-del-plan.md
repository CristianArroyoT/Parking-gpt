# Codemap — cierre del plan de pendientes (2026-10-21)

> Mapa del código **después** del cierre del plan de pendientes. Para la
> superficie de API con su RBAC, ver [`../API-INTERNAL.md`](../API-INTERNAL.md).
> Para el estado de cada ítem, ver
> [`../superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md`](../superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md).
>
> Convención: un codemap por trabajo grande, en `docs/CODEMAPS/AAA-MM-DD-<slug>.md`.

## 1. Mapa del backend

```
backend/app/
├── api/v1/                    100 endpoints en 22 routers
│   ├── __init__.py            el concentrador (registra todos los routers)
│   ├── auth.py                login, oauth, refresh, logout
│   ├── password_reset.py      recuperación de contraseña (T-22)
│   ├── users.py               CRUD de usuarios (admin) + ámbito /me
│   ├── gestor_operadores.py   alta/listado de operadores por sucursal (T-20)
│   ├── planes.py              planes y suscripciones (T-18)
│   ├── cliente.py             "mi plaza" y "mis tickets" del cliente (T-24)
│   ├── incidents.py           incidentes + adjuntos/fotos (T-21)
│   ├── face_templates.py      biometría PREPARADA, deshabilitada (T-23)
│   ├── cameras_live.py        preview MJPEG (T-06)
│   ├── events.py              bus de eventos SSE (T-17)
│   └── reports.py             exportes PDF/CSV (T-16)
├── core/
│   ├── config.py              settings (pydantic-settings) — incluye FACE_TEMPLATES_ENABLED
│   ├── deps.py                auth y RBAC (get_current_user, parking_context, …)
│   └── middleware.py           AuditMiddleware (T-11)
├── models/                    modelos SQLAlchemy
│   ├── pricing.py             Plan, Subscription (ya existían)
│   ├── incident.py            IncidentAttachment (T-21) ← NUEVO
│   └── user.py                PasswordResetToken (T-22) ← NUEVO
├── services/
│   ├── cameras/
│   │   ├── stream.py          mjpeg_generator + CapturaSincronizada (T-06+1/T-13+2)
│   │   └── live_streams.py    registro de streams vivos con lock (T-10) — API síncrona (P2 del preview)
│   ├── incident_attachments.py  almacenamiento de fotos en volumen (T-21) ← NUEVO
│   ├── plans.py               suscripciones (T-18) ← NUEVO
│   └── pricing.py             cálculo del descuento (NO tocar: T-18 lo replica)
├── scripts/
│   └── purge_incident_attachments.py  purga por retención (T-21) ← NUEVO
└── alembic/versions/           0012_reset_and_face_templates, 0013_incident_attachments
```

## 2. Mapa del frontend

```
frontend/src/
├── views/
│   ├── admin/PlansView.vue        catálogo de planes (T-18) ← NUEVO
│   ├── cliente/
│   │   ├── MyPlanView.vue         "Mi plan" (T-18) ← NUEVO
│   │   ├── MySpotView.vue         "Mi plaza" (T-24) ← NUEVO
│   │   ├── PaymentsView.vue       "Pagos" (T-24) ← NUEVO
│   │   ├── VehiclesView.vue       "Mis vehículos" (T-19) ← NUEVO
│   │   └── ProfileView.vue        "Mi perfil" (T-19) ← NUEVO
│   ├── gestor/
│   │   ├── MovementsView.vue      entradas/salidas (T-20) ← NUEVO
│   │   ├── AlertsView.vue         alertas activas (T-20) ← NUEVO
│   │   └── OperatorsView.vue      operadores (T-20) ← NUEVO
│   └── operador/IncidentModal.vue  selector de hasta 3 fotos (T-21)
├── api/gestorOps.ts            cliente HTTP de las vistas de gestor
├── pwa/                        modo PWA + registro del service worker (T-24) ← NUEVO
├── router/index.ts             rutas + guard de rol + guard de PWA
└── layouts/AppLayout.vue       menú por rol (en PWA, sólo cliente)
```

Rutas nuevas: `/admin/planes`, `/mi-plan`, `/mi-plaza`, `/pagos`, `/mis-vehiculos`,
`/mi-perfil`, `/gestor/movimientos`, `/gestor/alertas`, `/gestor/operadores`.

## 3. Cambios de contrato (lo que un consumidor nota)

### Endpoints nuevos

| Endpoint | Rol | Notas |
|---|---|---|
| `POST /api/v1/auth/forgot-password` | público | Respuesta **uniforme**: no revela si el email existe |
| `POST /api/v1/auth/reset-password` | público (con token) | Invalida los JWT previos del usuario |
| `GET /api/v1/plans` · `POST` · `GET/PATCH/DELETE /plans/{id}` | admin | |
| `GET /api/v1/plans/me` | cliente | `billing_mode: contable` (decisión D2) |
| `GET/POST /api/v1/plans/subscriptions` · `DELETE /plans/subscriptions/{id}` | admin | Un usuario, como mucho, una suscripción vigente |
| `GET /api/v1/parkings/{id}/operadores` | gestor/admin | Acotado a las sucursales del gestor |
| `POST /api/v1/parkings/{id}/operadores` | gestor/admin | Rol **forzado** a `operador` |
| `GET /api/v1/cliente/plazas` · `/cliente/tickets` | cliente | |
| `POST /api/v1/incidents/{alert_id}/attachments` | operador | Hasta 3 ficheros, validados **por bytes** |
| `GET /api/v1/incidents/attachments/{id}/thumbnail` · `/download` | gestor/admin | `nosniff` + `Content-Disposition: attachment` |
| `GET /api/v1/users/me/vehicles` (+ `POST/PATCH`) · `/users/me/tickets` · `/users/me/profile` | cliente | Ámbito propio |
| `POST/DELETE /api/v1/face-templates` | — | **404**: `FACE_TEMPLATES_ENABLED` apagado (T-23) |
| `GET /api/v1/admin/reports/{informe}.pdf` · `.csv` | admin | ingresos, ocupacion, tickets, alertas, margins |

### Cambios de comportamiento (los importantes)

| Cambio | Por qué |
|---|---|
| **`GET /api/v1/tickets` acota por vehículos para el rol `cliente`** (antes por membresía de sucursal) | Fuga de datos entre clientes: un cliente con membresía veía los tickets de **todos** los vehículos de la sucursal |
| `GET /api/v1/users` y `POST /users/{id}/memberships` **siguen siendo admin-only** | No se han relajado al abrir el router de operadores |
| El preview MJPEG va a **5 fps** (`LIVE_PREVIEW_FPS`; `0` = sin limitador) | Decisión D1: −85,5 % de ancho de banda |
| Los streams de preview y SSE **no retienen sesión de BD** | Con 50 streams se agotaba el pool de conexiones |
| El stream SSE y el MJPEG **se cierran al apagar el servidor** | Uvicorn se quedaba esperando conexiones abiertas para siempre |
| `UserUpdate.full_name` exige `min_length=2` | Un nombre de 1 carácter hacía fallar con 500 `GET /users` |
| El login con `?token=` funciona en `/parkings/{id}/events` (antes 401 siempre) | El endpoint lo anunciaba pero no lo cumplía |
| La ronda de heartbeat sondea las cámaras **en paralelo** | En serie, con 50 cámaras, monopolizaba un slot del pool y el healthcheck del worker lo reiniciaba en bucle (T-13+4) |

## 3-bis. P2 del preview: el slot de la cámara (2026-10-21)

Arreglado **después** de cerrar el plan. El síntoma: un operador cerraba
el modal de previsualización y, al volver a abrirlo, recibía un **409**
durante hasta ~8 s (el umbral del barrido de sesiones huérfanas).

### Qué pasaba

| # | Problema | Consecuencia |
|---|---|---|
| 1 | El `cap.release()` (teardown del RTSP) se ejecutaba **en el hilo del event loop** | Con la cámara colgada, `CapturaSincronizada.release()` espera a la lectura en vuelo (hasta el timeout de FFmpeg: 5 s) → **el backend entero se congelaba** |
| 2 | El slot se liberaba en el `finally` del generador **externo**, que corre **después** del teardown del generador **interno** | El slot quedaba ocupado durante todo el teardown → 409 para quien quisiera reabrir |
| 3 | La liberación dependía del **finalizador de generadores asíncronos** del event loop | No era determinista: en el peor caso el slot se quedaba hasta el barrido de huérfanas (8 s) |
| 4 | `release(camera_id)` no sabía **a qué sesión** pertenecía la llamada | El `finally` de un generador viejo podía liberar la sesión de un cliente **nuevo** y matarle el stream (LIMITACIÓN CONOCIDA) |

### Qué se ha cambiado

| Fichero | Cambio |
|---|---|
| `app/services/cameras/stream.py` | `mjpeg_generator` acepta `on_session_end` (callback **síncrono**) que se invoca **antes** de la limpieza de la captura; el `cap.release()` va a un hilo (`asyncio.to_thread`), fuera del event loop |
| `app/services/cameras/live_streams.py` | API **síncrona** (`try_acquire` / `release` / `heartbeat` / `shutdown_all`); `release(camera_id, session)` y `heartbeat(camera_id, session)` sólo tocan la sesión indicada; lock `threading.Lock` |
| `app/api/v1/cameras_live.py` | `_PreviewResponse` (subclase de `StreamingResponse`) suelta el slot de forma **determinista** al terminar la petición, pase lo que pase |

**Por qué la API del registro pasó a ser síncrona**: la liberación del
slot tiene que ser una operación que **ninguna cancelación pueda
interrumpir** y que tenga que ocurrir **antes** del teardown. Con
`await` dentro de un `finally` de un generador que se cierra por
cancelación, la cancelación puede cortarlo a mitad.

### Antes / después, medido

El mismo fichero de tests (`backend/tests/test_live_preview_release_order.py`)
ejecutado contra el código viejo (HEAD `817a51c`) y contra el nuevo:

| Test | Código viejo | Código nuevo |
|---|---|---|
| El slot se libera antes de la limpieza de la captura | ❌ | ✅ |
| La limpieza **no bloquea** el event loop | ❌ **5 ticks en 1 s** (loop congelado) | ✅ ~100 ticks en 1 s |
| El slot se libera aunque el stream se cancele | ❌ | ✅ |
| Cerrar y reabrir la cámara no da 409 | ✅ | ✅ |

El 5 ticks frente a ~100 es la medida del congelamiento: con el código
viejo, el teardown bloqueaba el event loop del backend entero.

### 3-ter. El SLO atado al P2: la regla `mjpeg_sin_409`

Al revalidar la carga con el código nuevo salieron dos cosas del
instrumental, ambas corregidas:

| Hallazgo | Por qué importaba | Arreglo |
|---|---|---|
| El locustfile leía en runtime `SOLIDAPP_CAMERA_IDS` (dos R) mientras la constante y el README documentan `SOLIDAPP_CAMARA_IDS` (una R) | Poner la variable como dice la documentación **no surtía efecto**: la ejecución se quedaba siempre con la cámara 81, que es justo la que provoca la contención (409) | El locustfile acepta los dos nombres; el documento manda en el nombre |
| Los previews descartados con un 409 los cuenta Locust como **éxito** (un 409 es una regla de negocio, no un fallo HTTP) | El SLO **no veía** la métrica clave del P2: una regresión del 409 habría pasado el CI sin que nadie se enterase | Nueva métrica `max_peticiones` (cuenta ocurrencias, no fallos) y regla `mjpeg_sin_409` con umbral 0 |

**Referencia regenerada** con el código nuevo (6 usuarios, 180 s, 10
cámaras): **491 peticiones, 0 fallos, 0 cortes, 0 reinicios del worker, 0
previews omitidos con un 409** → **SLO 14 de 14 reglas OK** (antes 13 de
13; la nueva es la que ata el P2).

### 3-quater. Maquetación: contenido que no cabía en su tarjeta (2026-10-21)

Encontrado en la **QA visual en el navegador integrado** (ventana de
1232 px), no en la headless (que recorre a 1440 px, donde no se nota).

| Vista | Qué pasaba | Medida |
|---|---|---|
| Operadores | La tabla se salía de su mitad de rejilla y la columna "Estado" (badges "Activo") quedaba **cortada a media** | 470 px de tabla en 435 px de tarjeta |
| Cámaras | La tabla se recortaba dentro de la tarjeta (`overflow-hidden`) | 950 px en 928 px |
| Planes | Ídem | 887 px en 611 px |
| Usuarios | Ídem | 650 px en 611 px |
| Tarifas | Ídem | 744 px en 611 px |

**Arreglo**: las cinco tablas van dentro de un contenedor
`overflow-x-auto` y con `min-w-max`, de modo que conservan su ancho de
contenido y la tarjeta las deja desplazar en horizontal en vez de
recortarlas. A 1440 px se ven igual que antes.

**Y el instrumento**: `frontend/scripts/qa_visual.py` ahora **detecta**
contenido que no cabe (recortado *o* desbordado, distinguiendo los
absolutos y fijos, que desbordan a propósito) y acepta `--ancho` para
recorrer las pantallas con la medida del panel lateral. Sale con código
1 si encuentra algo. Resultado: de **5 contenidos desbordados a 0** a
1232 px, y 0 a 1440 px (sin regresión).


| Modelo | Tabla | Notas |
|---|---|---|
| `IncidentAttachment` | `incident_attachments` | `alert_id` con `ON DELETE CASCADE`; el binario **no** está en la BD, vive en el volumen `incident_attachments` |
| `PasswordResetToken` | `password_reset_tokens` | Se guarda el **hash SHA-256** del token, nunca el token en claro |

Migraciones: `0012_reset_and_face_templates` (T-22 + T-23) y `0013_incident_attachments` (T-21).

## 5. Variables de entorno nuevas

| Variable | Default | Para qué |
|---|---|---|
| `LIVE_PREVIEW_FPS` | `5` | fps del preview (0 = sin limitador) |
| `FACE_TEMPLATES_ENABLED` | `false` | estructura de biometría preparada (fuera del MVP) |
| `INCIDENT_ATTACHMENTS_DIR` | `/var/lib/solidapp/incident-attachments` | volumen de las fotos |
| `INCIDENT_ATTACHMENT_MAX_BYTES` | `10485760` | tope por fichero |
| `INCIDENT_ATTACHMENT_MAX_FILES` | `3` | ficheros por incidente |
| `INCIDENT_ATTACHMENT_RETENTION_DAYS` | `90` | retención y purga |

## 6. Documentación relacionada

- `docs/adr/0001-orquestacion-produccion.md` — Compose en el edge, K8s en el central.
- `docs/adr/0002-ocr-cpu-vs-gpu.md` — la GPU no aporta con la carga real.
- `docs/API-INTERNAL.md` — los 100 endpoints con su RBAC y la política de deprecación.
- `infra/backup/README.md` — procedimiento de backup, restauración y simulacro trimestral.
- `backend/locust/README.md` — escenarios de carga y SLO.
- `docker/vehicle-detector/README.md` — el modelo real y el bug de canales BGR/RGB.
- `frontend/README.md` — PWA, QA visual y la trampa del HMR en Docker Desktop/Windows.
