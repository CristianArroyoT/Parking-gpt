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
├── api/v1/                    101 endpoints en 24 routers
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

Al revisar además a **1024 px** (tablet, con el menú colapsado) salió el
último defecto: la etiqueta **"Minutos/fracción"** de Tarifas era un
único token sin espacios (98 px) en una caja de 86 px, y se salía de su
columna. Ahora dice "Minutos por fracción", que parte en dos palabras como
la etiqueta de al lado. Los tres anchos (1024, 1232 y 1440) quedan con
**0 desbordes y 0 errores de consola**.

El detector **excluye a propósito** los controles de formulario
(`select`, `input`, `textarea`), que el navegador recorta de forma nativa
con puntos suspensivos: no es un defecto de maquetación, y marcarlo
haría que la comprobación dejara de servir como puerta.

El barrido responsive queda cerrado en cuatro anchos (768, 1024, 1232 y
1440 px), todos con **0 desbordes y 0 errores de consola**.

### 3-seis. El contrato de la API, revisado por el código (2026-10-21)

El inventario de `docs/API-INTERNAL.md` se había quedado en **61 de los
100 endpoints** que exponía la aplicación (no se tocaba desde T-25, antes
del Bloque 3). Como el propio documento avisa de que "se actualiza el
documento, no al revés", se construyó la forma de comprobarlo:

| Script | Qué hace |
|---|---|
| `tools/extraer_api.py` | Extrae rutas y RBAC de los routers con `ast` y los **valida contra el OpenAPI real** |
| `tools/generar_seccion_api.py` | Regenera la sección 3 del documento desde el código |
| `tools/verificar_api_doc.py` | Detecta la deriva, con **autoprueba** (quita una ruta y añade otra inexistente, y comprueba que las ve). Compara la sección 3 **entera** con la que genera el código, no sólo las rutas |
| `tools/cobertura_api.py` | Mide **qué endpoints tienen test** |
Tres cosas salieron de ahí:

1. **Dos rutas estaban registradas dos veces** (`POST
   /users/{user_id}/memberships` y `POST
   /vehicles/{vehicle_id}/users`): el decorador `@router.post` estaba
   duplicado y FastAPI avisaba en cada arranque con *"Duplicate
   Operation ID"*, ensuciando el OpenAPI, que es justo la fuente del
   inventario. Corregido.
2. **La columna "Quién" tenía que decir dos cosas**: quién puede llamar
   al endpoint (las dependencias) **y qué datos ve** (el ámbito que el
   endpoint filtra en el cuerpo: membresías de sucursal, sus vehículos).
   El extractor sigue el filtro hasta las funciones auxiliares del
   módulo y distingue filtrar de construir y de anotar.
3. **Dos endpoints no los ejercitaba ningún test**: los del OCR de
   placas (`GET /plates-detected` y `POST /cameras/{id}/plates`).
   Ahora tienen 9 tests (401, 403, 404, 422, alcance, orden, filtro y
   persistencia) y la cobertura es **99 de 99**.
4. **Y el CI lo vigila**: el job de integración ejecuta
   `python ../tools/verificar_api_doc.py`, que compara la sección 3
   entera con la que genera el código. Al añadir esa comparación
   completa salió un fallo real: el orden de los ámbitos no era
   determinista (venía de un `set`) y la sección podía cambiar entre
   ejecuciones. Corregido.

### 3-nueve. Dos fallos que sólo aparecían fuera del contenedor (2026-10-21)

Salieron al **ejecutar el job de integración del CI en local**, leyendo el
workflow (`tools/ejecutar_ci_local.py`). La QA y la suite se habían hecho
siempre dentro del contenedor, que difiere del portátil del equipo en dos
cosas: la **zona horaria** (UTC) y la **resolución de nombres** de Docker.

| Fallo | Por qué sólo fuera del contenedor | Arreglo |
|---|---|---|
| Una cámara **sin URL de RTSP** hacía escupir aserciones de OpenCV ("!_filename.empty()") en cada sondeo, preview y captura | El alta ya lo impedía (`CameraCreate.rtsp_url`, `min_length=8`), pero **el PATCH no**: `CameraUpdate.rtsp_url` no validaba nada, así que un `PATCH {"rtsp_url": ""}` dejaba la cámara rota para siempre en la BD | El PATCH exige lo mismo que el alta; además los tres servicios que abren la captura comprueban la URL antes de llamar a OpenCV y fallan de forma limpia |
| Un test del heartbeat **sólo pasaba si la máquina estaba en UTC** | El heartbeat guarda `datetime.now(timezone.utc)` y el test lo comparaba con `datetime.now()` (hora **local**): desfase de 1-2 h → *"last_heartbeat_at demasiado antiguo"*. En CI y en el contenedor pasaba (ambos en UTC) | La comparación es UTC contra UTC. Verificado en el host (UTC+2) y en el contenedor (UTC) |

Herramientas que lo destaparon y que se quedan:

| Script | Para qué |
|---|---|
| `tools/ejecutar_ci_local.py` | Ejecuta un job del workflow **leyendo el YAML** (no duplicando los pasos), con su `working-directory` y sus variables → comprueba el cableado real |
| `tools/revisar_esquemas.py` | Busca asimetrías de validación entre los esquemas `Create` y `Update` (ahora no hay ninguna) |

### 3-octies. Un despliegue limpio, probado de verdad (2026-10-21)

Las migraciones se ejecutaban sobre la base de QA (ya sembrada) y el seed
por separado, pero **nunca los tres juntos sobre una base vacía**. Un
despliegue roto (una migración que no aplica sobre el esquema limpio, o un
seed que usa una columna que ya no existe) sólo se habría visto en el
primer cliente.

`tools/verificar_despliegue_limpio.py` lo cubre entero:

| Paso | Qué comprueba | Resultado medido |
|---|---|---|
| 1 | Base de datos **vacía** | creada de cero |
| 2 | `alembic upgrade head` | 14 migraciones, sin error |
| 3 | `python -m app.scripts.seed` | 5 parkings × 60 plazas, 50 cámaras, 4 usuarios, 3 planes, 5 tarifas, 2 membresías |
| 4 | La aplicación, contra esa base | arranca y responde 200 en `/health` |
| 5 | La API con los datos del seed | login 200, `/parkings` 5, `/plans` 3, `/users` 4, resumen de tickets 200 |

Y el seed resultó ser **idempotente** (ejecutarlo dos veces da los mismos
recuentos). El CI lo ejecuta en el job de integración.

### 3-septies. Los modelos y las migraciones contaban dos historias (2026-10-21)

Salió al ejecutar `alembic check`, la herramienta estándar para comparar los
modelos con el esquema. Antes de eso, `alembic check` no servía para nada:
comparaba contra la base entera, incluidas las tablas TIGER/Line de la imagen
de PostGIS y la geometría que crea `infra/seed.sql`. Con el filtro puesto,
la deriva real era de 8 puntos, **en los dos sentidos**:

| Sentido | Qué | Por qué importa |
|---|---|---|
| Los modelos declaraban 4 índices que la BD no tenía (`cameras.code`, `parking_spaces.number`, `camera_geofences.parking_space_id`, `tickets.parking_space_id`) | Ninguna migración los creó: se crearon las columnas y ya | Cada listado con filtro es un Seq Scan |
| La BD tenía 4 restricciones `UNIQUE` que el modelo no produce (`users_email_key`, `vehicles_plate_key`, `parkings_code_key`, `plans_code_key`) | La migración 0001 creó la restricción **y** el índice único; el modelo con `unique=True, index=True` produce sólo el índice | `alembic check` fallaba, así que la siguiente migración autogenerada se habría llevado un `DROP CONSTRAINT`: **emails, matrículas y códigos habrían dejado de ser únicos** |
| La BD tenía 3 índices que el modelo no declaraba (`ix_audit_logs_created_at`, `ix_audit_logs_user_id_created_at`, `ix_plates_detected_detected_at`) | Las migraciones 0007/0008/0002 los crearon a propósito (consultas de auditoría) y el modelo no los recogió | `alembic check` quería borrarlos |

**Arreglo**: los tres índices se declaran ahora en los modelos; la
migración `0014_indices_y_uniques` (escrita a mano, con `downgrade` que
restituye las restricciones) crea los 4 que faltaban y quita las 4
redundantes. **La unicidad no se pierde** —la garantiza el índice único—
comprobado insertando un email duplicado: rechazado con `ix_users_email`.

**Y en el CI**: los tests crean el esquema con `Base.metadata.create_all`,
así que **no ejecutan las migraciones**: una migración rota sólo se habría
visto en producción. El job de integración ahora levanta una base vacía,
migra de cero y comprueba con `alembic check` que el esquema resultante
coincide con los modelos.

### 3-quinquies. El PWA, verificado de verdad (2026-10-21)

Nadie comprobaba lo que hace que una PWA sea instalable. Nueva
`frontend/scripts/qa_pwa.py`, que verifica:

| Qué | Resultado medido |
|---|---|
| Manifiesto con los campos que Chrome exige (`name`, `start_url`, `display`, `icons`) y los tamaños 192/512 | OK: 4 iconos, `display=standalone` |
| **Cada icono se sirve con 200** y no está vacío | OK (un icono en 404 sólo se ve al instalar) |
| El *service worker* se registra, queda activo y **toma el control** | OK: activo, controlando, **44 entradas precacheadas** |
| **La app arranca sin red** (se corta la red y se recarga) | OK: la pantalla sale desde la caché del SW |

**No entra en el CI todavía**, a propósito: el job de frontend corre en
una imagen de Node sin Python ni navegadores, y añadirlo exigiría
instalar Playwright y Chromium (+~500 MB). Con la facturación de la cuenta
resuelta **no se puede validar un cambio del workflow** (los jobs no
arrancan), así que meter algo sin probar dejaría el CI en rojo sin
querer. Queda como T-24+1 para cuando el CI vuelva a estar en marcha.

### 3-novies. El móvil (414 px) desplazaba la página entera de lado a lado (2026-10-21)

La QA visual recorría cuatro anchos (768, 1024, 1232 y 1440 px), pero
**ninguno era de móvil**: el más estrecho era una tablet vertical. Al
añadir el ancho de un móvil (414 px) salieron **26 contenidos desbordados
en 6 de las 21 pantallas**, y **3 pantallas con la página entera
desplazable** de lado a lado (Movimientos, Operadores y Tickets).

La línea base está medida sobre el commit anterior al arreglo
(`8315d2f`), no de memoria: se restauró ese código, se pasó la QA a
414 px y el resultado fueron 26 desbordes en 6 pantallas.

**La causa tiene dos capas**, y es por eso que arreglar sólo una no sirve:

| Capa | Qué pasa | Arreglo |
|---|---|---|
| La tabla | Un `<table>` no baja del ancho de su contenido, así que se sale de su tarjeta | Envolverla en un `div` con `overflow-x-auto` y `min-w-max` **dentro** del `class` de la tabla |
| La columna | Un ítem de rejilla o de flex tiene `min-width: auto`, que lo ata a la anchura mínima de su contenido: la columna no encoge y la página hereda el desbordamiento | `min-w-0` **en el ítem de la rejilla**, no sólo en el envoltorio de la tabla |

Se comprobó midiendo en el navegador, no adivinando: el `<section>` de
Operadores seguía con `min-width: auto` y **611 px** en una columna de
**366 px**, mientras la tabla (571 px) ya cabía desplazándose dentro de su
envoltorio de 326 px.

Dos herramientas nuevas:

| Script | Para qué |
|---|---|
| `tools/envolver_tablas.py` | Envolver las tablas de todas las vistas de forma mecánica. Mueve la directiva `v-if`/`v-else` al envoltorio (si se queda en la tabla, Vue no compila) y añade `min-w-max` **dentro** del atributo `class` |
| `frontend/scripts/sonda_anchura.py` | Medir la cadena de ancestros del elemento más ancho, con su `min-width` calculado, su `overflow-x` y su `display`: distingue el culpable del que sólo lo arrastra |

Y un arreglo de la propia QA: las pantallas de **mapa** y de **vídeo en
directo** nunca dejan de cargar (teselas del mapa y flujo SSE), así que la
espera de "networkidle" se agotaba siempre ahí y se reportaba como **error
de red**. Ahora se reporta como **aviso**: es tráfico de fondo perpetuo,
no una pantalla rota.

Resultado medido: **0 desbordes** en las 26 pantallas a los **cinco**
anchos (414, 768, 1024, 1232, 1440 px), 0 errores de consola y 0
peticiones fallidas.

### 3-decies. El texto corrupto era una puerta abierta (2026-10-21)

Al modelo de lenguaje se le cuelan caracteres de otros alfabetos (CJK,
cirílico, coreano) al escribir en español. **Pasó dos veces en esta misma
sesión**: una en un docstring (una palabra china colada entre dos
españolas) y otra en un **identificador de JavaScript** (un identificador
con caracteres CJK), que dejó una vista entera en blanco con un 500.

> Los ejemplos no se reproducen aquí literalmente a propósito: si
> estuvieran en el repo, la puerta de corrupción que se describe más
> abajo los detectaría a ellos mismos y el CI se pondría en rojo.

El escáner (`tools/escanear_texto.py`) ya existía, pero era un paso
manual. Ahora es **una puerta del CI**, con un modo nuevo:

| Cambio | Detalle |
|---|---|
| `tools/escanear_texto.py --tracked` | Escanea **exactamente lo versionado** por git: ni `node_modules`, ni `dist`, ni ficheros generados. Lo que se va a publicar es lo que se comprueba |
| `.github/workflows/ci.yml` (job `backend`) | Paso nuevo **antes de instalar dependencias**: el escáner es sólo biblioteca estándar, así que falla en dos segundos en vez de esperar al `pip install` |
| `tools/ejecutar_ci_local.py` | **Ignoraba `continue-on-error`**, así que declaraba el job "backend" en rojo por el paso de `mypy`, que el workflow tolera a propósito. Ahora reproduce la semántica de Actions: el paso se marca como fallido, **el job sigue** |

Medido: **0 problemas en los 312 ficheros versionados**, `actionlint` con
salida 0 y el paso en verde en la ejecución local del job.

De paso, una afirmación inexacta del plan quedó corregida: **`mypy app`
no está en verde** (78 errores en 33 ficheros, en modo `strict`). No es
una regresión: el paso del CI lleva `continue-on-error: true` desde el
primer commit. La cabecera del plan lo daba por bueno sin serlo.

### 3-undecies. El CI llevaba más de tres meses sin validar nada (2026-10-21)

El último criterio del plan pedía `gh pr checks 14`. Al comprobarlo con
la API de GitHub, el **PR #14 está fusionado desde el 2026-07-07** y no
queda ningún PR abierto: el criterio apuntaba a un PR que ya no existía.
La referencia correcta es el CI sobre `main`.

Y al mirarlo de verdad, la cosa es bastante más seria de lo que parecía:

| Medición (con la API de GitHub) | Resultado |
|---|---|
| Runs revisados | los 100 más recientes |
| Runs que **ejecutaron** algún paso | 56 |
| Runs **rechazados sin ejecutar ninguno** | **44** |
| Último run que ejecutó un paso | **2026-07-07T20:52:15Z** (rama `feat/live-preview-cameras`: Backend en rojo por el `F401`, Frontend en verde) |
| Commits de `main` sin validar por el CI | **87** |

La firma del rechazo es inequívoca: los 4 jobs terminan en `failure` con
**0 pasos**, en 3-5 segundos. Eso no es el código fallando — un job
rechazado nunca llega a un runner.

Herramienta nueva: **`tools/estado_ci.py`**, que distingue los tres casos
que se confundían:

| Código de salida | Significado |
|---|---|
| 0 | El CI de `main` está **en verde** |
| 1 | **Rojo de verdad**: algún job ejecutó pasos y falló → es el código |
| 2 | **Rechazado por la cuenta**: los jobs mueren con 0 pasos → es la facturación |

Sale con 0 / 1 / 2 para poder encadenarlo en un script, y escribe el
informe en `tools/_informe_ci.txt` (UTF-8) porque la consola de Windows
se come los acentos.

### 3-duodecies. La alerta de "cámara caída" nunca enviaba el correo (2026-10-21)

Como el CI no ejecuta `mypy` de verdad desde hace meses, su salida **no se
miraba**. Al leerla, apareceu esto:

```
app/services/email.py:193: error: Name "_render_camera_offline" is not defined
```

**El bug**: desde el sprint CAMERA_OFFLINE (2026-07-01) existen las
plantillas `alerts/camera_offline.{txt,html}.j2`, pero la función que las
renderiza **nunca se definió**. `send_alert_email` la llamaba, el
`NameError` lo capturaba el `except` general, y la función devolvía
`False`: **la alerta de cámara caída se guardaba en la BD pero el correo al
administrador no salía nunca**. En silencio, y con la alerta ya visible en
el panel, así que nadie se enteraba.

**Por qué los tests no lo detectaban**: todos los tests de alertas
**simulan** `send_alert_email` con `monkeypatch` —justo la función que
contenía el bug—, así que nunca entraban en el renderizado. Y el
`noqa: F821` que llevaba el código silenciaba al linter para que el CI no
bloqueara.

| Cambio | Detalle |
|---|---|
| `app/services/email.py` | Se implementa `_render_camera_offline` con el mismo patrón que `_render_ocr_failed` y el contexto que la plantilla ya pedía. Se retira el `noqa: F821` y el comentario que lo daba por pendiente |
| `backend/tests/test_email_templates.py` (nuevo) | 6 tests que llaman al código **real** en modo dry-run, sin simular `send_alert_email`. Uno comprueba que **cada** `template_kind` tiene su fichero de plantilla, para que añadir un tipo sin plantilla no falle en runtime |

El test **demuestra el defecto**: ejecutado contra el código anterior
fallan 3 de los 6; con la corrección pasan los 6. `mypy app` baja de 78 a
77 errores y el `NameError` desaparece.

### 3-terdecies. `/health` decía "ok" con todo caído (2026-10-21)

Al usar `tools/verificar_despliegue_limpio.py` saltó esto: la aplicación
arrancaba, `/health` respondía 200, y a continuación el login y
`/parkings` devolvían **401 con *"Servicio de autenticación no disponible"***.
La causa era Redis, no era alcanzable desde donde corría el script.

**El hueco**: `GET /health` devolvía `{"status": "ok"}` **sin comprobar
nada**. Con la base de datos caída, el contenedor se declaraba sano y
todo endpoint devolvía 500. Con Redis caído, el `AuditMiddleware` va a
*fail-closed* (correcto: si no se puede consultar la blacklist de
tokens, no se deja pasar ningún token) y **toda** petición autenticada
devolvía 401. En los dos casos, `docker compose ps` decía "healthy".

**El arreglo** es la distinción estándar entre *liveness* y *readiness*:

| Endpoint | Significado | Código |
|---|---|---|
| `GET /health` | *Liveness*: ¿el proceso vive? **No** mira dependencias a propósito (un health check que dependa de la base reinicia el proceso cuando una dependencia falla, y eso convierte un fallo de red en un bucle de reinicios) | 200 siempre |
| `GET /health/ready` | *Readiness*: ¿puede servir tráfico? Comprueba la base (`SELECT 1`) y Redis (`PING`) | 200 o **503** con el detalle |

El `HEALTHCHECK` del `Dockerfile` pasa a usar `/health/ready`, así que
`docker compose ps` deja de mentir. Nada depende de
`condition: service_healthy` del backend, así que no puede crear bucles
de reinicio.

De paso, `tools/verificar_despliegue_limpio.py` mejoró en los tres
puntos que fallaban:

| Antes | Ahora |
|---|---|
| Esperaba a `/health` (que siempre dice 200) | Espera a `/health/ready` |
| Se comía los 45 s de espera y decía "no respondió" | **Aborta en cuanto recibe un 503**, con el detalle de la dependencia |
| Un 401 parecía un problema de credenciales | Dice que es un fallo de servicio (Redis) y no de credenciales |

Verificado con Redis caído: `{"database":"ok","redis":"TimeoutError"}` a
la primera, sin esperar.

### 3-quattuordecima. El CI local se colgaba: `localhost` es IPv6 en Windows (2026-10-21)

El job "integration" de la réplica local se quedaba **minutos** en el paso
"Las migraciones y los modelos coinciden", sin error visible. La causa no
era el código:

| Medida | Tiempo |
|---|---|
| `psycopg.connect` a `localhost:5432` | **8,42 s** |
| `psycopg.connect` a `127.0.0.1:5432` | **1 ms** |

En esta máquina (Windows) `localhost` resuelve **primero a IPv6
(`::1`)**, y Docker publica PostgreSQL y Redis **sólo en IPv4**. El
cliente prueba `::1`, se queda esperando el *timeout* de conexión y sólo
después prueba IPv4. En un runner de Linux (el de GitHub) no pasa: ahí
`localhost` es `127.0.0.1`. Por eso el arreglo va **sólo en la réplica
local**, no en el workflow.

El arreglo, en `tools/ejecutar_ci_local.py`: las variables de entorno de
cada paso se pasan por un filtro que cambia `localhost` por `127.0.0.1`
cuando va seguido de `:<puerto>`. Ojo con el patrón: la URL del CI es
`postgresql+psycopg://parking:parking@localhost:5432/...`, así que
`localhost` va **detrás de la arroba**, no detrás de `://` (la primera
versión del filtro no cubría ese caso y no arreglaba nada).

De paso, dos robustezas de la misma tanda:

| Cambio | Por qué |
|---|---|
| La salida de los subprocesos va a un **fichero** temporal, con `stdin` a `DEVNULL` y un tope de 600 s | Un hijo que hereda una tubería puede quedarse esperando un EOF que no llega: el paso se cuelga sin ningún error visible |
| Los `print` del ejecutor van con `flush=True` y los pasos con `PYTHONUNBUFFERED=1` | Sin esto, si el proceso muere a mitad, la salida ya producida se queda en el búfer y se pierde: el informe de una ejecución colgada era una pantalla en blanco |

Y una nota de método: **`task_stop` no mata a los hijos**. Al limpiar
había **tres** ejecuciones del CI local simultáneas peleándose por las
mismas bases de datos (`solidapp_migraciones`, `solidapp_despliegue`),
que se dropeaban mutuamente. Eso también provocaba "cuelgues" que no
tenían nada que ver con el código. Hay que matar a los hijos a mano
antes de relanzar.

**Resultado**: los cuatro jobs del workflow pasan en local (backend,
integration, docker-build y frontend), con el único `mypy` tolerado por
`continue-on-error`.

### 3-vicesima. Por qué el CI remoto sigue sin poder arrancar (2026-10-21)

El repositorio es **privado** (`gh api repos/… → "private": true`). En un
repo privado, los runners de GitHub Actions son de pago, y la cuenta de
la organization/personal tiene el pago pendiente: GitHub rechaza el job
**antes de asignarle un runner** (los 4 jobs mueren en 2-5 s con 0
pasos). Por eso el último run que ejecutó algo fue el del 2026-07-07.

Se evaluaron **tres vías** para recuperar el CI:

| Vía | Qué implica | Veredicto |
|---|---|---|
| Arreglar la facturación | Nada en el repo ni en el workflow | **La recomendada** |
| Hacer el repo público | Las Actions son gratuitas en repos públicos | Fix y gratis, pero es una decisión de producto sobre la visibilidad (histórico completo + datos de ejemplo) |
| Runner self-hosted en esta máquina | El token de registro funciona y no hay runners dados de alta | **Descartada**: el job de integración declara servicios Linux en `localhost`, y dentro de un runner en contenedor los servicios se alcanzan por **nombre**; además los puertos 5432/6379 ya los ocupa el stack local, así que los servicios chocarían. Habría que tocar el workflow sin poder validarlo |

La tercera vía se descartó a propósito: el propio plan avisa de que
"meter algo que no se ha podido probar en el CI es exactamente la forma
de dejar el CI en rojo sin querer". Y con la factura arreglada, el
workflow actual pasa entero (probado en local, paso a paso).

### 3-quadragesima. La red de seguridad del repo, en un comando (2026-10-21)

Con el CI remoto muerto, el repo no tenía forma de saber si estaba
sano: cada comprobación era un comando aparte, con su recordatorio, y
olvidarse de una era fácil. `tools/verificar_repo.py` es esa puerta:

```bash
python tools/verificar_repo.py            # rapido: ~1 min
python tools/verificar_repo.py --completo # + CI local y QA visual: ~26 min
```

| Comprobación | Resultado medido |
|---|---|
| Texto versionado sin corrupción | 0 problemas |
| Sin secretos (árbol e historial) | 0 |
| El inventario de la API coincide con el código | 101 rutas |
| Todo endpoint con test | `SIN ningun test: 0` |
| Esquemas Create/Update simétricos | OK |
| Modelos y migraciones coinciden | `alembic check` limpio |
| SLO de carga | 14/14 reglas |
| El PWA es instalable y arranca sin red | OK |
| CI local (los 4 jobs del workflow) | **Todos los jobs pasan en local** (19 min) |
| QA visual en 414 / 768 / 1024 / 1232 / 1440 px | 5 × 26 pantallas, 0 desbordes |
| CI remoto en `main` | rechazado por la cuenta (facturación) → **aviso**, no fallo |

Sale con 0 si todo está bien y 1 si algo falla, como haría el CI. Cada
comprobación tiene su propio límite de tiempo, y antes de las pesadas
comprueba que el stack esté en marcha y avisa (`docker compose up -d`)
en vez de fallar con errores confusos de navegador o de backend.

### 3-vigésimoprimera. `mypy` en verde (de 77 errores a 0) y la puerta del CI deja de tolerarlo (2026-10-21)

El backend estaba en modo `strict` y el paso de mypy en el CI llevaba
`continue-on-error: true` **desde el primer commit**: 77 errores que
nadie miraba, porque el paso que los mostraba era el único que la CI se
saltaba. Con el CI remoto muerto desde el 2026-07-07, además, su salida
no la leía nadie.

**Qué se corrigió** (32 ficheros, +131/−87, sin tocar la lógica):

| Tipo | Cuántos | Cómo |
|---|---|---|
| `no-untyped-def` | 21 | Anotaciones de retorno y de parámetro |
| `type-arg` | 11 | `dict` → `dict[str, Any]`, `Callable` → `Callable[..., Any]` |
| `no-any-return` | 11 | `cast(...)` donde la librería no está tipada (passlib, pyjwt, httpx) |
| Ruido de redis-py | 14 | `cast(int, ...)`: la clase `Redis` de redis-py sirve para el cliente síncrono y el asíncrono, y sus tipos son `Awaitable[Any] \| Any` |
| `untyped-decorator` | 5 | `# type: ignore[untyped-decorator]` en los decoradores de Celery |
| `misc` / `assignment` | 4 | Código muerto eliminado (`_ = Ticket` en `pdf.py`), import de `UserRole` movido a `app.models.enums`, `desc(col)` → `col.desc()` |

**Dos cosas que casi rompen el producto, y que un type-checker no
avisa:**

1. **Anotar `request: Request | None = None` rompe FastAPI.** Sólo
   inyecta la request cuando el tipo es exactamente `Request`; con la
   unión, la toma por un parámetro del cuerpo y el endpoint deja de
   funcionar. Se dejó `Request = None` con un `# type: ignore[assignment]`
   y un comentario que lo explica.
2. **El resultado de mypy depende del entorno.** Con mypy 1.20.2 sobre
   Python 3.11 (la del CI) aparecía un error de `order_by` de SQLAlchemy
   que el host (Python 3.13) no reportaba. Por eso se comprobó **en los
   dos**: `Success: no issues found in 107 source files` en ambos.

**Resultado**: la puerta de mypy en el CI **deja de tolerar fallos**
(`continue-on-error` fuera), validado con el job replicado en local
("El job 'backend' pasa entero en local").

### 3-vigésimosegunda. La suite ya aguanta dos ejecuciones en paralelo (2026-10-21)

Al revalidar en paralelo (la réplica local del CI y la suite contra
PostgreSQL a la vez) falló
`test_rate_limit_blocks_after_max_attempts`: las dos suites usaban la
**base Redis 15** y una veía los contadores de la otra.

La base de Redis de la suite se elige ahora **por PID** (de la 8 a la
15, la 0 es de la app), así que dos ejecuciones simultáneas no se
pisan. Verificado: dos suites de rate-limit en paralelo → **9 passed**
las dos; en solitario, también.

Esto no era un fallo del CI (allí los jobs van de uno en uno), pero era
un problema real: cualquier dos ejecuciones simultáneas de la suite se
contaminaban.

### 3-vigésimotercera. El simulacro de restauración de backups, automatizado (2026-10-22)

T-12 entregó el `backup.sh` y el `restore.sh` y probó la restauración a
mano, pero la decisión **D3** pide probarla **cada trimestre**, y eso era
una checklist en papel. Entre trimestre y trimestre, un backup roto
(passphrase perdida, destino remoto caído, disco lleno) pasaba meses sin
que nadie se enterara.

`tools/verificar_backup.py` (+ `infra/backup/simulacro.sh`) hace la
cadena entera, en unos 10 s:

| # | Paso | Qué comprueba |
|---|---|---|
| 1 | `backup.sh` | volcado cifrado nuevo |
| 2 | el `.enc` | que **no** es legible en claro |
| 3 | `restore.sh` | restauración en una base limpia |
| 4 | recuentos | que la base restaurada tiene **los mismos datos** (8 tablas) |
| 5 | `alembic check` | que el **esquema del backup es el que espera el código de hoy** |
| 6 | el backend | que **arranca** contra la base restaurada (`/health` 200) |
| 7 | limpieza | borra la base de prueba |

El paso 5 es el que duele: un backup de hace tres meses, restaurado, y
la app no arranca porque le falta una columna. Con el simulacro
automatizado eso se ve en el momento, no en el trimestre.

**Por qué corre dentro de un contenedor**: el host no tiene `pg_dump`,
`pg_restore` ni `openssl`, y el `pg_dump` tiene que ser de la **misma
versión que el servidor** (si no, `pg_restore` falla con *"unsupported
version"*). Corre en `postgis/postgis:16-3.4` —la imagen del servidor—
dentro de la red de Docker.

La checklist **manual** no se elimina: el automático comprueba que la
cadena funciona, el manual comprueba lo que la cadena no puede (destino
S3 remoto, passphrase real en el gestor de secretos, responsable). Las
dos conviven en `infra/backup/README.md`.

### 3-vigésimocuarta. El linter del frontend no existía (2026-10-22)

El `package.json` del frontend definía un script `lint` que **nunca
funcionó**: ESLint 9 exige un `eslint.config.js` (config plano) y en el
repo no había ninguno. Y el job `frontend` del CI **no lo ejecutaba**,
así que el linter roto pasó desapercibido. El backend sí tenía linter
(`ruff`) desde el principio: la asimetría era de origen, no de decisión.

`frontend/eslint.config.js` (config plano) y un paso nuevo en el job
`frontend` del CI. Se usa **`flat/essential`**, no `flat/recommended`:
"recommended" arrastra reglas de **formato** (una etiqueta por línea…) que
son opinión y que obligarían a reformatear el frontend entero (1 425
avisos). Con "essential" el linter avisa de lo que está **mal**.

Lo que encontró al activarlo (5 errores + 1 aviso, todos reales):

| Fichero | Qué era |
|---|---|
| `api/gestorOps.ts` | El parámetro `labels` de `filterMovements` no se usaba dentro de la función (el caller lo pasaba) |
| `views/gestor/MovementsView.vue` | `const ui = useUiStore()` sin usar, ni en el script ni en la plantilla |
| `views/gestor/CalibrateView.vue` | Un `// eslint-disable-next-line no-console` obsoleto |
| `env.d.ts` | El shim estándar de Vue dispara la regla de "objeto vacío": se apaga **sólo** en `*.d.ts` |

Con esto: `npm run lint` → **0 problemas**, `vue-tsc` → 0 errores, y el
job `frontend` replicado en local pasa entero.

### 3-vigésimoquinta. Los cuatro servicios sin healthcheck (2026-10-22)

La definición de hecho del plan dice *"docker compose up -d → **todos los
servicios healthy**"*, pero `docker compose ps` mostraba el frontend,
Loki, promtail y Grafana **sin** estado de salud: **no tenían
healthcheck**. El criterio se daba por cumplido sin que nada lo
comprobara.

| Servicio | Probe | Por qué ese |
|---|---|---|
| `frontend` | `wget :5173/` | El dev-server de Vite *es* la app; la imagen es alpine (busybox `wget`, no `curl`) |
| `loki` | `wget :3100/metrics` | El `/ready` de Loki devuelve **503 aunque esté en pie**: no sirve. `/metrics` responde 200 mientras el servidor HTTP esté vivo |
| `promtail` | `grep -q promtail /proc/1/comm` | No expone endpoint HTTP (empuja logs) y su imagen **no trae `wget` ni `pgrep`** |
| `grafana` | `wget :3000/api/health` | Responde 200 con el estado de su base de datos |

Ahora `docker compose ps` muestra los **11 servicios** como `(healthy)`.

### 3-vigésimoseptima. El inventario de la API decía "Público" en 9 endpoints de admin (2026-10-22)

Auditando la columna **"Quién"** de `docs/API-INTERNAL.md` (el contrato que
lee quien integra la API) contra el código, los **9 endpoints de
`/plans`** aparecían como **"Público"**: catálogo, alta y borrado de
planes, suscripciones y "mi plan". En el código **todos exigen
autenticación** y casi todos son **de admin**.

**Por qué**: `tools/extraer_api.py` sacaba las dependencias de FastAPI
sólo del **valor por defecto** del parámetro (`x: User = Depends(...)`).
El idioma moderno es **en la anotación**
(`x: Annotated[User, Depends(require_role(...))]`), y ese camino no se
miraba. Encima, el bucle de los posicionales recorría únicamente los
parámetros **con valor por defecto**, así que los que llevan la
dependencia en la anotación ni se visitaban.

**Por qué nadie lo vio**: el verificador compara el **conjunto de
rutas**, que no había cambiado (9 endpoints "Público" y 9 con el RBAC
correcto son el mismo juego de rutas). La deriva estaba en la **columna**,
y el gate no la cubría.

| Cambio | |
|---|---|
| `extraer_api.py` | Mira las **dos** formas (default **y** `Annotated[...]`) y recorre **todos** los parámetros, no sólo los que tienen default |
| `verificar_api_doc.py --autoprueba` | **Tercera** cara: cambiar el "Quién" de una fila debe detectarse (antes sólo añadía y quitaba rutas) |

Verificado: los 9 endpoints de `/plans` documentan su RBAC real, y los
7 que **sí** son públicos (login, login OAuth, refresh, forgot-password,
reset-password y los dos de salud) siguen marcándose como públicos,
comprobado contra el código.

### 3-vigésimooctava. Las puertas, a prueba de sí mismas (2026-10-22)

El patrón de los últimos hallazgos: los bugs más caros **no estaban en
la aplicación**, sino en las **herramientas que la describen o la
miden** (extractor de RBAC, script de lint, healthcheck, recuento de
endpoints). A todas les faltaba lo mismo: **ninguna tenía forma de
demostrar que detectaba** lo que dice detectar.

| Herramienta | Autoprueba |
|---|---|
| `tools/verificar_api_doc.py` | Detecta las **tres** caras de la deriva: quitar ruta, añadir ruta inexistente y **cambiar el RBAC** de una fila (esta última es la que se coló en T-35) |
| `tools/escanear_texto.py` | Detecta CJK, cirílico, coreano, moneda rara y fichero no-UTF-8; y **no dispara con el español normal con acentos** |
| `tools/escanear_secretos.py` | Detecta los 5 tipos de secreto; y **no dispara** con valores de ejemplo, ficheros exentos (`.env.example`, `tests/`, `docs/`) ni comentarios |
| `tools/autopruebas.py` (nuevo) | La **meta-puerta**: ejecuta todas las autopruebas y falla si alguna ha dejado de detectar. Está en el CI y en `tools/verificar_repo.py` |

Un detalle que salió al escribir la autoprueba del escáner de secretos:
los tokens de mentira **se construyen en tiempo de ejecución**, no se
escriben literales en el source. Si estuvieran literales, el propio
escaner los encontraría — y con razón: el repositorio es público y un
token real en un literal es una credencial filtrada.

### 3-vigésimonovena. La puerta de asimetrías no comparaba nada (2026-10-22)

`tools/revisar_esquemas.py` es la puerta que el plan cita como la que
encontró el hueco del `CameraUpdate.rtsp_url`. Al añadirle su autoprueba
(T-36) salió que **llevaba desde su creación sin comparar nada**:

1. Buscaba la pareja con `nombre[:-5]`, pero **"Create" tiene seis
   letras** → la pareja se llamaba `CameraCUpdate` y no se encontraba
   jamás. Su "OK: los campos validados en el alta se validan igual en la
   edicion" era **vacío**.
2. Miraba sólo el **cuerpo** de la clase, así que era ciego a los
   esquemas que **heredan** sus campos de una clase base
   (`ParkingCreate(ParkingBase)`, `UserCreate(UserBase)`).

Al arreglarlo aparecieron **5 asimetrías vivas**, del mismo tipo que el
hueco del `rtsp_url` (T-25) y el del `full_name` (T-19): el POST los
rechazaba y el PATCH los aceptaba.

| Esquema | Campo | En el alta | En la edición |
|---|---|---|---|
| `CameraUpdate.name` | `name` | 2-128 | **sin límite** |
| `ParkingUpdate.name` | `name` | 2-255 | **sin límite** |
| `ParkingUpdate.address` | `address` | 2-512 | **sin límite** |
| `ParkingUpdate.city` | `city` | 2-128 | **sin límite** |
| `UserUpdate.phone` | `phone` | máx. 32 | **sin límite** |

Un PATCH podía dejar una sucursal sin nombre o un teléfono de 500
caracteres, que después invalidaba la fila al serializar.

**Las dos lecciones:**

- El arreglo: los 5 campos Update validan lo mismo que sus altas, el
  detector corrige el `[:-5]` y resuelve la herencia, y se añade
  `backend/tests/test_esquemas_simetricos.py`, que recorre **todos** los
  pares Create/Update de todos los esquemas y compara sus restricciones
  con las de pydantic. La regla queda cubierta por la suite, no sólo por
  la herramienta: si alguien añade una validación en un alta y olvida
  el PATCH, lo dice el CI. Se ha comprobado que el test **falla**
  reintroduciendo el defecto (sólo en el lado Update).
- **La lección**: una puerta que nunca ha saltado no es una puerta. El
  "OK" de este detector era tan vacío como su código: informaba de que
  no había asimetrías sin haber mirado ninguna. La autoprueba es lo que
  destapa ese tipo de puerta zombie.

Y con el IPv4 arreglado, la réplica local pasó a poder ejecutar **el CI
completo**, incluidos los dos pasos de test que antes se saltaban
porque el host no resolvía los nombres de servicio de Docker:

| Paso del CI | En el host |
|---|---|
| Tests (pytest, SQLite) | **604 passed, 9 skipped** |
| Tests contra PostgreSQL (pytest) | **613 passed** |
| Test de funciones sólo de SQLite | **13 passed** |
| Type-check (vue-tsc) y build del frontend | exit 0 |
| Los cuatro jobs | **VERDE** |

O sea: mientras la facturación de GitHub siga pendiente, la réplica local
es el **CI completo** de facto. Lo que falta para cerrar el criterio es
sólo que GitHub deje de rechazar los jobs.


### 3-trigésima. El frontend y el backend no se hablaban (2026-10-22)

El frontend habla con el backend a través de su propio cliente HTTP
(`frontend/src/api/*.ts`) y el backend expone **101 rutas**. **Nada**
comparaba las dos listas.

La QA visual recorre 26 pantallas, pero sólo llega a los endpoints que
esas pantallas tocan. Una ruta mal escrita en un cliente que nadie abre se
queda escondida hasta que un usuario la encuentra. Y el caso inverso —un
endpoint con el **método equivocado**— es el más caro: no da 404, da 405 en
producción, y como la ruta existe, parece un problema de permisos.

`tools/verificar_contrato_frontend.py` cierra el hueco comparando, de
forma estática, **cada ruta que el cliente pide** con **las rutas que el
backend expone**:

| | |
|---|---|
| Rutas del backend | **101** |
| Llamadas del cliente | **83** (39 en los módulos de `@/api/` + 44 escritas a mano en las vistas) |
| Desajustes | **0** |

Distingue dos fallos, porque se arreglan distinto:

- la ruta **no existe** en el backend;
- la ruta **existe pero con otro método**.

El detalle que hace que la puerta sirva: **normaliza los dos lados**. El
frontend escribe `${parkingId}` y el backend `{parking_id}`, y la query
string se quita (`/alerts?type=x` y `/alerts` son la misma ruta). Sin esa
normalización, las 83 llamadas darían 83 falsos positivos y la puerta no
serviría para nada —o, peor, se desactivaría por ruidosa.

**Dónde vive**: en la meta-puerta (`tools/autopruebas.py`, que pasa de 5 a
**8 autopruebas**), en `tools/verificar_repo.py` (la salud del repo en un
comando) y en el CI, como paso del job `integration`. Sólo usa la
biblioteca estándar —el extractor de la API parsea el código con `ast`—,
así que no depende de las dependencias del backend.

**La lección**: el hallazgo no fue un bug, sino una **ausencia**. En este
repositorio los fallos caros se accumulan en la zona que nadie mira
—las herramientas que describen y miden el código—, y una zona sin
comprobaciones es indistinguible de una zona correcta.


### 3-trigésimoprimera. El guard de rol del frontend no se comparaba con el RBAC del backend (2026-10-22)

El router protege cada pantalla con `meta: { roles: [...] }` y el backend
protege cada endpoint con `require_role(...)`. **Nada comparaba las dos
listas.**

Es el reverso exacto de T-35 (allí el inventario decía "Público" en 9
endpoints de admin; aquí una pantalla promete un rol que el backend no
concede). El síntoma es silencioso y confuso: el router deja entrar al
gestor en una pantalla, la pantalla carga sus datos y el backend responde
**403**. Desde el frontend no parece un problema de permisos —la ruta
existe y el método es el correcto—: sólo el rol no encaja.

`tools/verificar_roles_frontend.py` recorre las **22 pantallas con guard
de rol**, sus componentes (cierre transitivo) y sus llamadas, y avisa si
alguna llama a un endpoint que exige un rol que la pantalla no contempla.

Cubre **las dos** formas de llamar, y esto es lo que casi se le escapa:

| Forma | Llamadas |
|---|---|
| Funciones de los módulos de `@/api/` | 39 |
| `http.get(...)` escrito a mano en las vistas | 44 |
| **Total** | **83** (82 de las 22 pantallas con guard) |

Mirar sólo los módulos habría dejado fuera casi la mitad del cliente.

**La puerta tiene un guardia anti-puerta-zombie**: si no resuelve ni una
sola llamada contra el backend, **falla** en vez de salir verde. Y su
autoprueba es **extremo a extremo**: inyecta una ruta de mentira que
abre la pantalla de usuarios al gestor y comprueba que la puerta canta
el desajuste, y que una pantalla con el rol correcto **no** lo canta.

#### Los 2 bugs que encontró

1. **El extractor de la API leía sólo el primer rol.** En
   `tools/extraer_api.py`, `_roles_de` hacía `return _roles_de(nodo.args[0], ...)`:
   leía el **primer** argumento de `require_role(...)` y se olvidaba del
   resto. Así documentaba `require_role('admin')` para endpoints cuyo
   código pide **tres** roles.

   Consecuencia: **`docs/API-INTERNAL.md` mentía sobre 5 endpoints** —
   decía "sólo admin" donde el gestor y el operador sí pueden entrar
   (`POST /incidents/parkings/{parking_id}`, `POST /incidents/{alert_id}/attachments`,
   `GET /incidents/{alert_id}/attachments`, `DELETE /incidents/attachments/{attachment_id}`,
   `POST /tickets/manual`).

   Es el mismo tipo de deriva que T-35 y por el mismo motivo: una
   herramienta que describe el código sin mirar el código entero.

2. **La puerta de contrato no veía las llamadas directas.**
   `verificar_contrato_frontend.py` (T-38) miraba sólo los módulos de
   `@/api/`: las 44 llamadas escritas a mano en las vistas quedaban sin
   comprobar. Ampliada a los `.vue`.

#### La query string

Las dos herramientas la quitan antes de comparar: `/alerts?type=x` y
`/alerts` son la misma ruta para el backend. Sin esa normalización, las
2 llamadas de `LiveView.vue` con query string salían como rutas
inexistentes — un falso positivo que habría hecho que la puerta se
desactivara por ruidosa.


### 3-trigésimosegunda. La puerta del inventario comparaba el documento contra el extractor, y los dos mentían (2026-10-22)

El bug de T-39 (el extractor leía sólo el primer rol) vivió **sin que
ninguna comprobación se enterara**, y el motivo es estructural:

`tools/verificar_api_doc.py` compara el documento contra el **extractor**.
Es decir, la puerta comparaba dos cosas que salían del **mismo código con
el mismo defecto**. Cuando el extractor mentía, el documento se
regeneraba con la misma mentira y la puerta daba el visto bueno: **verde
sobre mentira**.

**La lección**: dos comprobaciones que comparten la fuente de verdad no se
vigilan entre sí. Para que una puerta vigile a otra hace falta una
**tercera** fuente: el caso de mentira escrito a mano.

`tools/extraer_api.py --autoprueba` monta **6 routers de mentira** en un
directorio temporal y comprueba qué roles saca el extractor de cada uno:

| Caso | Roles esperados |
|---|---|
| `require_role("admin")` | admin |
| `require_role(UserRole.ADMIN.value, UserRole.GESTOR.value, UserRole.OPERADOR.value)` | admin, gestor, operador |
| `require_role(UserRole.ADMIN.value, UserRole.GESTOR.value)` | admin, gestor |
| `require_role('admin', 'cliente')` | admin, cliente |
| `require_role(UserRole.ADMIN.value)` | admin |
| `require_role(*_STAFF)` | los de la constante desplegada |

El fichero nunca se importa: sólo se parsea con `ast`. Además se recorre
el **código real** y se comprueba que ningún `require_role` con varios
roles se queda con sólo el primero.

**Comprobado en los dos sentidos**: con el defecto reintroducido, 3 de los
6 casos pasan a rojo; al arreglarlo, los 6 vuelven a verde. La meta-puerta
pasa de 9 a **10 autopruebas**.


### 3-trigésimotercera. La QA visual se bloqueaba a sí misma con el rate-limit de login (2026-10-22)

Al ir a medir las cifras de la documentación, la QA falló en 2 de los 5
anchos con "no se pudo iniciar sesión". El mensaje no decía por qué, así
que no era diagnosticable.

**La causa, medida**: `POST /auth/login` tiene un rate-limit de **10
intentos por IP cada 5 minutos** (`login_rate_limit_max_attempts=10`,
`login_rate_limit_window_seconds=300`, con buckets por IP **y** por email;
cuenta **todos** los intentos, los exitosos también).

La QA inicia sesión **una vez por rol** (gestor, cliente, admin) → **3
inicios por ejecución**. Recorrer 5 anchos en 5 procesos son **15
inicios** → a partir del cuarto, el login devolvía **429**.

Comprobado a mano: 12 inicios seguidos contra la API → los 9 primeros
`200`, el 10º ya `429`.

**Consecuencia**: `python tools/verificar_repo.py --completo` era una
**puerta que fallaba por el rate limit, no por el código**. Y como el
mensaje no decía "429", el diagnóstico empezaba por el sitio equivocado.

**El arreglo (3 cosas)**:

1. **`--anchos`**: un solo proceso recorre varios anchos. Se **inicia
   sesión una sola vez por rol** y para cada ancho se cambia el
   **viewport de la misma página** (`page.set_viewport_size`), con lo que
   la sesión se conserva. De 15 inicios a **3**.
2. **El motivo del fallo de login se reporta**: `_login` devuelve
   `(ok, motivo)` y distingue el **429** ("límite de intentos, no es un
   fallo de la pantalla") de un timeout o un error de navegación.
3. **Los manejadores de consola y de red se registran una vez por
   página** en vez de uno por pantalla: antes se acumulaban (26 pantallas
   × 5 anchos = 130 manejadores disparando a la vez).

**Resultado medido tras el arreglo**:

| | |
|---|---|
| Anchos en un proceso | 5 (414, 768, 1024, 1232, 1440) |
| Inicios de sesión | **3** (en vez de 15) |
| Capturas | **130** (26 pantallas × 5 anchos) |
| Desbordes | **0** |
| Errores de consola | **0** |
| Errores de login | **0** |
| Avisos | 10 (2 por ancho: `/mapa` y `/vivo`, que nunca dejan la red en reposo) |


### 3-trigésimocuarta. La herramienta que decide si el CI está verde tenía un falso verde (2026-10-22)

`tools/estado_ci.py` es la herramienta que decide si el **último criterio
del plan** está cumplido (los 4 checks del CI sobre `main` en SUCCESS). Si
clasifica mal, el plan se cierra —o se deja abierto— por un motivo falso.
Es la puerta más delicada del repo, y era la **única sin autoprueba**.

**Los 2 defectos que tenía**:

1. **Falso verde con un run en curso.** Si el run todavía no había
   terminado (por ejemplo, recién acabas de hacer `git push`), no hay jobs
   todavía: la lista salía vacía, no había ningún job en rojo, y caía en
   el mensaje **"El CI de main está EN VERDE"**. Justo en el momento en
   que se decide si el criterio está cumplido.
2. **No filtraba por rama.** El docstring dice "sobre `main`" y el
   criterio es "los checks del CI **sobre `main`**", pero usaba el run
   más reciente **sea cual sea su rama**. Medido: hoy los 30 runs más
   recientes son todos de `main`, así que no muerde todavía — pero el día
   que haya una rama con runs, morderá.

**El arreglo**:

- La clasificación se separa en una función pura `_clasificar(run, jobs)`
  → (código, líneas), que se puede probar con casos de mentira.
- Un **estado nuevo `EN_CURSO` (código 3)**: un run que no ha terminado no
  es verde, y `verificar_repo.py` lo dice así ("todavía en curso, no se
  puede afirmar"). Un run completado **sin jobs** tampoco es verde.
- **Filtro por rama** (`--rama`, por defecto `main`) y el commit del run
  en el informe, para poder compararlo con el `HEAD` local.

**La autoprueba distingue los 5 casos**:

| Caso | Resultado esperado |
|---|---|
| 4 jobs en `success` | VERDE |
| 1 job en `failure` **con** pasos | ROJO DE CÓDIGO |
| 4 jobs en `failure` **sin** pasos | RECHAZADO POR LA CUENTA |
| Run en curso, sin jobs | EN_CURSO (no verde) |
| Run completado, sin jobs | no verde |

La meta-puerta pasa de 10 a **11 autopruebas**. Comprobado contra el CI
real: el último run de `main` (4 jobs, 0 pasos) se clasifica como
**rechazado por la cuenta** (código 2).


### 3-trigésimoquinta. La cadena del inventario de la API tenía un eslabón sin comprobar (2026-10-22)

T-40 arregló el extractor de la API (leía un solo rol de `require_role`)
y le añadió su autoprueba como tercera fuente. Pero quedaba un hueco por
delante: la puerta del inventario (`tools/verificar_api_doc.py`) comparaba
el documento contra el **generador**, y el generador usa el **mismo
extractor**.

**El hueco**: si el extractor **no veía una ruta**, esa ruta tampoco
estaría en el documento (se genera con el extractor) y la puerta diría
"el inventario coincide con el código". Una ruta invisible en el extractor
era invisible en el documento **y** en la puerta. Y la puerta del contrato
sólo la habría cantado si el frontend la llamara.

**La tercera fuente ya existía y no se usaba**: `extraer_api.py` (sin
`--autoprueba`) compara el extractor contra el **OpenAPI de la aplicación
real**. Pero ninguna puerta lo ejecutaba: era un dato que se comprobaba a
mano de vez en cuando.

**El arreglo**: la cadena pasa a ser *app real → extractor → documento*,
y cada eslabón se comprueba contra el anterior:

```
   app real (OpenAPI)  ──►  extractor  ──►  documento
        ▲                     ▲
        │                     └── las 5 caras de la deriva (autoprueba)
        └── si el extractor no ve una ruta, se ve aquí
```

- `verificar_api_doc.py` compara el extractor contra el OpenAPI **antes**
  de comparar el documento, y dice las tres cifras: **101 / 101 / 101**.
- La comparación se extrae a una función pura, para que la autoprueba
  pueda probarla **sin** la app instalada (importa la app en el camino
  normal, no en la autoprueba: el job `backend` corre las autopruebas
  antes del `pip install`).
- La autoprueba del verificador pasa de **3 a 5 caras**: quitar ruta,
  añadir ruta inexistente, cambiar el RBAC, **una ruta que el extractor
  no ve** y **una ruta que el extractor inventa**.


### 3-trigésimosexta. El CI habría salido rojo en cuanto se arreglase la facturación (2026-10-22)

El job `backend` del workflow corre `tools/autopruebas.py` **antes** del
`pip install` (a propósito: así las autopruebas fallan en segundos en
vez de después de un install largo). De las 11 autopruebas, **10 sólo
usan la biblioteca estándar**. La undécima —la del detector de
desbordes de la QA visual— necesita **playwright**, porque evalúa el
JavaScript en un Chromium de verdad (el JS mide anchos de elementos, y
eso sólo lo sabe un motor de layout).

**El problema**: `playwright` **no es dependencia del backend** (ni de
`.[dev]`), y el `import` de `qa_visual.py` estaba en la cabecera del
módulo. En un runner limpio, el paso "Las puertas se prueban a sí
mismas" moría con `ModuleNotFoundError: No module named 'playwright'`
→ la meta-puerta fallaba → **el job `backend` salía rojo**.

**La réplica local no lo detectaba**: el host ya tenía playwright
instalado, y la réplica ejecuta los pasos del YAML en esta máquina, no en
un runner limpio. Es decir: **la réplica local daba un verde que el CI
real no daría**. Justo el tipo de puerta que este repo lleva toda la
sesión desmontando.

**Probado, no supuesto**: se creó un venv vacío (`python -m venv`, sin
playwright) y se ejecutó la meta-puerta dentro: `ModuleNotFoundError` y
salida 1. El fallo es real, no una hipótesis.

**El arreglo (3 cosas)**:

1. **`qa_visual.py` se importa sin playwright**: el `import` pasa a ser
   opcional y, si falta, la autoprueba devuelve un código nuevo,
   **3 = "no se ha podido comprobar"**, con el mensaje de cómo
   instalarlo. Nada de reventar con un `ModuleNotFoundError`
   disfrazado de problema de código.
2. **La meta-puerta distingue los tres estados**: `0` pasa, `1` falla,
   **`3` no se ha podido comprobar**. Con la opción **`--estricto`** (la
   que usa el CI y `verificar_repo.py`), lo no comprobado **es un
   fallo**; sin ella, se avisa con claridad y **no** se dice "las
   autopruebas pasan". El resumen distingue "10 pasan y 1 no se han
   podido comprobar" de "las 11 pasan".
3. **El CI instala el navegador antes de las autopruebas**: un paso
   nuevo en el job `backend` (`pip install playwright` +
   `playwright install chromium`, con `--with-deps` sólo en Linux, que
   es donde hace falta instalar las librerías del sistema). Así, en el
   CI, **las 11 autopruebas se comprueban de verdad**.

**Por qué esto era P0**: el último criterio del plan pide que los 4
checks del CI sobre `main` terminen en SUCCESS. Con el CI roto por este
`ModuleNotFoundError`, arreglar la facturación no habría servido de
nada: el job `backend` habría seguido en rojo y el criterio seguía sin
poder marcarse. La causa no era la cuenta: era del repo.


### 3-trigésimoséptima. Las acciones del workflow iban 3 versiones por detrás y dependían de un workaround sin validar (2026-10-22)

T-44 destapó que la réplica local del CI no reproduce un runner limpio.
Aplicando esa misma mirada al **workflow en sí**, salió otra cosa.

El workflow fijaba `actions/checkout@v4`, `actions/setup-python@v5` y
`actions/setup-node@v4` — tres versiones mayores por detrás — y su
propio comentario explicaba por qué:

> *"GH Actions deprecó Node 20 en 2025-09-19 y fuerza Node 24. Las
> acciones @v4/@v5 targetean Node 20 → conflicto en cache de
> dependencias. Esta env var autoriza a las acciones deprecadas a seguir
> corriendo en su versión original."*

**Medido contra la API de GitHub** (el runtime de Node de cada versión,
leído del `action.yml` de cada etiqueta):

| Acción | Fijada | Runtime | Primera con node24 |
|---|---|---|---|
| `actions/checkout` | v4 | **node20** | v5 |
| `actions/setup-python` | v5 | **node20** | v6 |
| `actions/setup-node` | v4 | **node20** | v5 |

Las tres estaban en **node20, un runtime desuscrito**, y dependían de
`ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` — cuyo nombre dice, literalmente,
que autoriza a ejecutar versiones de Node **inseguras**. Como el CI no
arranca un job desde el 2026-07-07, esas versiones estaban **completamente
sin validar** contra la plataforma de hoy: el workflow podía fallar en el
**primer paso** (el checkout), antes de ejecutar nada del proyecto.

**El arreglo: el salto mínimo al runtime soportado**, no el más grande.
`checkout@v5`, `setup-python@v6`, `setup-node@v5` — una versión mayor, no
tres. Los cambios incompatibles se revisaron uno a uno:

- `setup-python@v6`: sólo "upgrade a node 24" (requiere runner ≥ v2.327.1;
  los runners hospedados lo son). Ninguna entrada cambia.
- `setup-node@v5`: "upgrade a node 24" y **auto-cache de npm** si el
  `package.json` trae un campo `packageManager`. Este proyecto no lo
  tiene, pero se desactiva explícitamente con `package-manager-cache:
  false` (la forma que documenta la acción), en vez del `cache: ""` de
  antes.
- `checkout@v5`: node 24, sin cambios que afecten (no usa entradas).

Y se **elimina** `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` de los tres
jobs: ya no hay nada que autorizar.

**Lo que se verificó al mismo tiempo** (la otra mitad del mismo audit):

| Entorno | Simulación | Resultado |
|---|---|---|
| Job `frontend` | contenedor `node:20`, `npm ci` desde cero | lint, type-check y build **en verde** (36 assets en el precache) |
| Job `backend` | contenedor `python:3.11-slim`, `pip install -e ".[dev]"` desde cero | **565 passed, 10 skipped** |
| Job `integration` | `postgis/postgis:16-3.4` recién creado + `python:3.11-slim` limpio | **574 passed, 1 skipped** + 13 del test SQLite + los 5 pasos de herramientas en verde |
| Fin de línea | `git ls-files --eol` | todos los ejecutables guardados con **LF** ✓ |
| Dependencias | `package-lock.json` | **existe y está versionado** (el comentario decía lo contrario) |

Nota: el host usa **Node 24** y el CI usa **Node 20**, y el host usa
Python 3.13 y el CI 3.11. Las dos simulaciones de arriba son las que
verifican de verdad esos jobs.


### 3-trigésimoctava. La puerta del CI daba por bueno un run al que le faltara un job (2026-10-22)

El último criterio del plan dice, literalmente, "los **4 checks** del CI
sobre `main` en SUCCESS (Backend, Integration, Build de imágenes Docker y
Frontend)".

Pero `tools/estado_ci.py` miraba **los jobs que tuviera el run**: si
alguien quitaba un job del workflow (o el run era de un commit anterior
del workflow), la herramienta decía **"EN VERDE"** con los que quedaran.
Un verde que no cumple el criterio.

**El arreglo**: la herramienta lee **los jobs que define el workflow de
este repo** (`.github/workflows/ci.yml`) y los compara con los del run.
Si falta alguno, no es verde: nuevo estado **INCOMPLETO (código 4)**, con
el mensaje de qué job falta.

Se parsea el workflow con una **expresión regular**, no con PyYAML:
PyYAML llega sólo como dependencia transitiva de `uvicorn[standard]`, y
este repo ya ha sufrido bastante con depender de cosas que nadie
declaró (T-44).

**La autoprueba distingue ahora 8 casos**: verde · job que falta (**no**
verde) · todos los esperados · rojo con pasos · rechazado por la cuenta ·
en curso · sin jobs · y que el workflow real define 4 jobs.

Comprobado contra el CI real: el último run de `main` sigue
clasificándose como **rechazado por la cuenta** (código 2).


### 3-trigésimonovena. Las credenciales de las cuentas demo estaban escritas tres veces sin que nada las comparara (2026-10-22)

Las credenciales de las cuentas demo están escritas **tres veces**:

| Sitio | Qué es |
|---|---|
| `backend/app/scripts/seed.py` → `DEMO_USERS` | lo que hay de verdad en la base de datos |
| `frontend/src/views/LoginView.vue` → `fillDemo()` | lo que el usuario ve y con lo que rellena el formulario al pulsar "Admin", "Gestor", "Operador" o "Cliente" |
| `frontend/scripts/qa_visual.py` → `CUENTAS` | con lo que la QA visual inicia sesión |

**Nada las comparaba**, y el modo de fallo es de las peores: si el seed
cambia una contraseña, la pantalla de login sigue rellenando la vieja y
**el usuario del demo no puede entrar**, con un "email o contraseña
incorrectos" que no dice absolutamente nada; y la QA falla con un error
de navegación que culpa al navegador. Nadie pensaría en mirar el seed.

Y la puerta de "despliegue limpio" (que sí existe) comprueba que el
seed cree **4 usuarios**, pero **no** que sus contraseñas sean las que
la pantalla de login ofrece.

**La puerta** (`tools/verificar_cuentas_demo.py`) lee las tres listas
(el seed y la QA con `ast`; el mapa del login con una expresión regular
acotada, porque es TypeScript dentro de un `.vue`) y comprueba:

- cada cuenta que ofrece el login **existe en el seed con la misma
  contraseña** y con **ese rol**;
- lo mismo para las cuentas que usa la QA visual;
- los roles del seed existen en el enum `UserRole` (leído del código);
- el login ofrece **todas** las cuentas del seed (si hay una cuenta,
  tiene que ser alcanzable desde la pantalla).

**Probado con el defecto reintroducido**: cambiando la contraseña del
admin en el seed, la puerta canta las **2** discrepancias (la del login
y la de la QA) y sale con código 1; al restoring, vuelve a verde.

Es estática (no necesita base de datos ni dependencias), así que va en
la meta-puerta (que pasa de 11 a **12 autopruebas**), en
`tools/verificar_repo.py` (14 comprobaciones) y en el job `integration`
del CI.


### 3-trigésimotercera. La QA visual no cubría 6 pantallas del router y nada lo decía (2026-10-22)

La QA visual recorre una lista de pantallas escrita a mano (`PANTALLAS`
en `frontend/scripts/qa_visual.py`) que es una **copia** de las rutas del
router. **Nada las comparaba.**

**Seis rutas no se revisaban nunca**:

| Ruta | Pantalla |
|---|---|
| `/dashboard` | el dashboard de admin |
| `/admin/parkings` | la lista de parkings |
| `/admin/costs` | la lista de costes |
| `/forbidden` | la pantalla de acceso denegado |
| `/:pathMatch(.*)*` | la pantalla de "no encontrada" |

La puerta de "despliegue limpio" comprueba que el seed cree 5 parkings, y
la de cobertura de endpoints que todos los endpoints tengan test: ninguna
mira **qué pantallas se revisan visualmente**. Y la propia auditoría móvil
encontró 26 desbordes en 6 pantallas **de las que sí se revisaban** — las
3 pantallas de admin **nunca se habían mirado a 414 px**.

**El arreglo (2 cosas)**:

1. **Las 5 pantallas se añaden a la QA** (la de "no encontrada" se visita
   con una ruta que no existe, a propósito). La QA pasa de 21 a **26
   pantallas**.
2. **Puerta nueva** (`tools/verificar_cobertura_frontend.py`): comprueba
   que **toda** ruta del router se recorre, avisa de las que no, avisa de
   las que la QA recorre y no existen (la visita al 404 es la única
   admitida) y avisa si la pantalla de "no encontrada" no se comprueba
   nunca. Las rutas que no se puedan recorrer van en una lista de
   **exenciones con su motivo** (hoy dos: `/`, que es una redirección por
   rol, y `/calibrate/:parkingId/:cameraId`, que necesita ids reales de
   parking y cámara).

A propósito, esta puerta **no** reutiliza el extractor de rutas de
`verificar_roles_frontend.py`: dos extractores independientes que se
vigilan mutuamente valen más que uno compartido (si los dos usan el
mismo código, los dos pueden quedarse ciegos a la vez).

**Probado en los dos sentidos**: añadiendo una ruta de prueba al router,
la puerta la canta y sale con código 1; al quitarla, vuelve a verde.


### 3-trigésimocuarta. El frontend replica a mano los enums del backend y nada lo comparaba (2026-10-22)

El frontend replica las enumeraciones del backend **a mano, en muchos
sitios**:

| Sitio | Qué replica |
|---|---|
| `layouts/AppLayout.vue` y `views/cliente/ProfileView.vue` | el mapa de etiquetas de cada rol (**dos copias**) |
| `views/admin/UsersView.vue` | la lista de roles que el admin puede asignar |
| `api/client.ts` y `api/gestorOps.ts` | el tipo `role` (**dos copias**) |
| `views/cliente/TicketsView.vue` | el tipo `TicketStatus` |
| `views/gestor/MovementsView.vue` y `views/cliente/TicketsView.vue` | la función `statusBadge()` |
| `views/gestor/AlertsView.vue` | el mapa de tipos de alerta |
| `views/gestor/CamerasView.vue` | el tipo de cámara y el sentido de la geocerca |

**Nada lo comparaba.** Hoy los dos lados coinciden, pero si el backend
añade un rol, un tipo de alerta o un estado de ticket:

- el mapa de etiquetas devuelve `undefined` y la pantalla muestra un
  **hueco**;
- el desplegable de "asignar rol" del admin **no ofrece el rol nuevo**,
  así que ese rol no se puede asignar desde la interfaz;
- y, lo peor, `statusBadge()` **etiquetaba cualquier estado desconocido
  como "Anulado"**: la pantalla afirmaba que un ticket estaba anulado
  cuando no lo estaba.

**El arreglo (2 cosas)**:

1. **Puerta nueva** (`tools/verificar_enums_frontend.py`): si el frontend
   conoce algún valor de un enum del backend, tiene que conocer **todos**.
   El mensaje dice **en qué ficheros** se usa ese enum, para que se sepa
   dónde tocar. Con 11 enums en el backend y 11 usados por el frontend,
   hoy sale en verde.
2. **`statusBadge` deja de mentir**: los tres estados del backend se
   tratan explícitamente y **cualquier otro se muestra tal cual**, con
   etiqueta neutra. La UI ya no afirma nada falso sobre el estado de un
   ticket.

**Probado con el defecto reintroducido**: añadiendo `SUSPENDIDO` a
`TicketStatus` en el backend, la puerta canta `TicketStatus.suspendido`
y dice que se usa en `MapView.vue`, `MovementsView.vue` y
`TicketsView.vue`; al quitarlo, vuelve a verde.


### 3-trigésimoquinta. La lectura automática de matrículas no estaba conectada a nada (2026-10-22)

`solidapp.ping_camera` es la tarea que agarra el frame de la cámara, se lo
manda al servicio OCR y **crea el ticket**. Es el corazón del producto.

**Lo que se encontró (medido, no supuesto)**:

- La tarea **existe** y está **registrada** en el worker
  (`celery inspect registered` la lista).
- **No está** en el `beat_schedule`.
- **Nadie la despacha**: en todo el backend no hay ni un `.delay()`, ni un
  `.apply_async()`, ni un `send_task()`. El único que consume el servicio
  OCR es esa misma tarea.
- El commit que la creó (66c172f, 2026-06-30) lo dijo explícitamente:
  *"solidapp.ping_camera (bajo demanda): stub de health-check de una
  cámara concreta... **Diseñado para que el endpoint
  `/admin/cameras/{id}/ping` lo enqueue cuando se añada**"*. Ese endpoint
  **nunca se añadió**.
- Al día siguiente (0e9057f) se escribió el comentario que la daba por
  viva: *"``ping_camera`` sigue corriendo en paralelo con
  ``kind='frame'``"*. Y en `celery_app.py`: *"Comparte lock de 1 h con el
  detector de ``frame`` para no duplicar"*. **Los dos comentarios
  describían un comportamiento que no existía.**
- **La prueba en la base de datos**: las 8 filas de `plates_detected` son
  del **2026-06-30** y son datos de prueba empujados a mano (`1234ABC`,
  `9999XYZ`); la última matrícula que el sistema leyó en su vida es de
  hace **más de tres meses y medio**. En cambio hay **98 alertas de
  cámara caída**, todas del detector de *heartbeat*
  (`probe_heartbeats`), que sí se despacha cada 60 s.

Es decir: **la detección de cámaras caídas funciona; la lectura de
matrículas no**. El pipeline que hoy funciona es el **push externo** al
endpoint `POST /parkings/{id}/plates-detected` (el que usa el
`rtsp-push` de QA), no la tarea de Celery.

**El arreglo (3 cosas)**:

1. **Los comentarios que mentían, corregidos**. Un comentario que
   describe un comportamiento inexistente es peor que no tener
   comentario: hace que el próximo que lo lea dé por hecho que el
   pipeline funciona.
2. **Puerta nueva** (`tools/verificar_tareas_celery.py`): comprueba que
   **toda tarea de Celery se ejecuta de verdad** (está en el beat, o
   alguien la despacha, o alguien la llama directamente). Recorre el
   **AST**, no un grep: por eso ve el comentario que mentía y lo ve como
   lo que es (un comentario). Las tareas que no se ejecutan *a propósito*
   van en una lista de exenciones con su motivo; las demás son un
   **fallo del CI**.
3. **El hallazgo queda escrito** en el código, en el plan y en el
   codemap, con su medida (la fecha de la última matrícula leída).

**Lo que queda para el usuario**: decidir si `ping_camera` se despacha.
No es un olvido, es una decisión de producto con cuatro partes: cómo (es
*por cámara*, así que el beat tendría que encolarla una a una), qué pasa
con las cámaras de demo (apuntan a `rtsp://demo.invalid` a propósito y
`ping_camera` no las skipea), qué pasa con la carga (decodificar un JPEG
por cámara y minuto es mucho más caro que el `grab()` sin decodificar) y
qué pasa con la detección de caídas (con los dos detectores vivos hay que
confiar en el lock de 1 h, que ya está implementado y testeado pero nunca
se ha ejercido en producción).


### 3-trigésimoseptima. Siete ajustes del backend que nadie leía (2026-10-22)

Un ajuste **muerto** (declarado, configurable por entorno y que **nadie
lee**) es una trampa silenciosa: parece configurable y no hace nada.

| Ajuste | Por qué está muerto | Dónde vive de verdad |
|---|---|---|
| `ocr_confidence_threshold` (0.85) | parecía un filtro global de confianza | el filtro real es el `confidence_threshold` de **cada geocerca** (lo calibra el operador) |
| `ocr_lang` ("es") | parecía decidir el idioma del OCR | lo decide el **servicio** OCR (`docker/ocr`, `OCR_LANG=en` para matrículas EU) |
| `ocr_engine` | parecía elegir el motor | lo elige el servicio OCR (`OCR_ENGINE`) |
| `async_database_url` | la app es **síncrona**: no hay `create_async_engine` | — |
| `api_host` / `api_port` | el `CMD` del Dockerfile los fija en duro | — |
| `loki_url` | la app no habla con Loki | los logs salen por stdout y los reenvía Promtail |

**Los dos engañados**: `ocr_confidence_threshold` y `ocr_lang`. Con
`ocr_lang` hay además una contradicción: el backend dice "es" y el
servicio va con "en", y **el valor del backend no hace nada**. Un
operador que lo cambiara creyendo que el OCR lee en español no lo
estaría haciendo.

**El arreglo (2 cosas)**:

1. **Cada ajuste muerto lleva ahora un comentario que dice que no se usa
   y por qué**, con el puntero a dónde vive lo que sí manda. Nada de
   "parece configurable": o funciona, o dice que no.
2. **Puerta nueva** (`tools/verificar_ajustes_muertos.py`): recorre los
   47 ajustes declarados en `Settings` y cuenta cuántas veces se leen
   (por acceso al atributo, en todo el backend, tests incluidos). Los
   que no se leen salen listados; los conocidos están en una lista con su
   motivo y **cualquier otro es un fallo del CI**.


### 3-trigésimooctava. El OCR aceptaba cualquier texto como matrícula (2026-10-22)

T-50 dejó al descubierto que `ping_camera` no se despacha. Al ejecutarla
**a mano, una vez, como diagnóstico**, se vio que la cadena sí funciona
(frame → OCR → ingesta) y que el OCR **lee texto, no matrículas**.

**La medida (con la cámara real del entorno)**: el vídeo de QA lleva **dos
rótulos quemados en la imagen** — `SOLIDAPP QA — CAM 01` arriba y el
timestamp `t=105.0s frame=2625` abajo —. El OCR devolvió
`"t=105.0sframe=2625"` como si fuera una matrícula, y en la siguiente
pasada `"SOLIDAPPQACAM01"`.

El primero se descartó **sólo por medir 19 caracteres** (el `max_length=16`
del esquema), por casualidad. El segundo (15 caracteres) **pasaba**.

**Por qué es grave**: `vehicles.plate` es `String(16) unique`. Una basura
corta aceptada crea un **vehículo fantasma permanente**, y si la geocerca
estuviera pintada encima, un **ticket** a un vehículo que no existe. Y no
es hipotético: **casi todas las cámaras reales queman el timestamp en la
imagen**, y a veces la marca.

**El arreglo**:

1. **Nuevo módulo** `app/services/plates.py` con la regla
   `parece_matricula()`: normaliza (mayúsculas, sin separadores) y exige
   la forma de una matrícula — `1234ABC` (español actual), `1234B`
   (antiguo), `E1234A` (diplomática). La regla es **permisiva a
   propósito**: no se quiere rechazar una matrícula legítima, sólo el
   texto que no la es.
2. **El filtro va en `process_plate_hit`**, que es el **punto único** por
   el que pasa una lectura para convertirse en vehículo y ticket (lo usan
   tanto la tarea de Celery como el push HTTP
   `POST /parkings/{id}/plates-detected`). Un hit que no es matrícula
   devuelve el estado nuevo `skipped_not_a_plate` y **no toca la base**.
3. **También en `ping_camera`**, antes de persistir la fila de auditoría:
   `plates_detected.plate` es de 16 caracteres, así que un texto más
   largo **reventaba el INSERT** ("value too long").
4. **Los contadores ya no mienten**: `plates_found` cuenta las matrículas
   válidas y hay un `plates_descartadas` para el texto quemado.

**Verificado con la cámara real**: el OCR leyó los dos rótulos, los dos se
descartaron, `plates_found: 0`, `plates_descartadas: 1`, **0 vehículos y
0 tickets creados**. Y **por la API real** (el otro camino de ingesta,
`POST /api/v1/parkings/11/cameras/81/plates`): `"CAM 01"` →
`skipped_not_a_plate` sin vehículo ni ticket, y `"1234ABC"` sigue su
curso normal. La demostración salió sin que hizo falta: con el proceso
viejo todavía en memoria, la petición basura **creó un vehículo**
`CAM 01` (que se deshizo por rollback porque la plaza estaba ocupada;
con plaza libre se habría quedado **para siempre**).

Y **20 tests nuevos** (`backend/tests/test_plates_ocr.py`): la regla
acepta las matrículas legítimas (incluida la diplomática y la antigua,
con y sin separadores) y rechaza las formas de texto quemado; un hit
basura **no crea vehículo ni ticket**; y una matrícula de verdad **sí**
crea el vehículo.

**Lo que queda fuera (documentado, no escondido)**: un rótulo como
`HD 1080P` tiene **exactamente la misma forma** que una matrícula antigua
(`M 1234 A`) o diplomática (`E 1234 A`), así que **ningún formato las
distingue**. En la práctica ese caso lo filtra el cruce con la geocerca
(el rótulo está en una esquina, fuera del rectángulo pintado) y el umbral
de confianza.


### 3-trigésimonovena. La suite del host tardaba 25 minutos y además fallaba por contaminación (2026-10-22)

Al medir la cifra de la suite para el CI, la del host se quedó **colgada
con 0 % de CPU** y luego tardó 25+ minutos. No era el código: era el
`conftest.py`.

**La causa, medida**:

- El `conftest.py` cogía la URL de Redis de `REDIS_URL` y, si no estaba,
  usaba `"redis://redis:6379/0"`: el **nombre del servicio de Docker**,
  que sólo resuelve **dentro** de la red de Docker. Desde el host
  (Windows) **no resuelve** y el intento tardaba **2,7 s** en fallar (el
  resolver del sistema).
- Como el fixture de limpieza de contadores (`_clean_redis_counters`)
  corre en **TODOS** los tests, eran 585 × 2,7 s ≈ **26 minutos de
  espera pura** por un fallo de DNS.
- Peor: la limpieza **no se hacía**. Los buckets de rate-limit (`rl:*`)
  no se aislaban, así que la suite veía los contadores **de la app que
  está en marcha en el mismo Redis** → 429 → `test_costs.py` y otros
  fallando. Es el "fallo intermitente" que el propio comentario del
  `conftest.py` describía desde el 2026-10-21, sin saber la causa.

**El arreglo (3 cosas)**:

1. **El `conftest.py` prueba candidatos y se queda con el que
   responde**: el `REDIS_URL` del entorno (en el CI,
   `redis://localhost:6379/0`), el nombre del servicio de Docker (que es
   donde corre la suite en el contenedor) y el puerto publicado en el
   host (`127.0.0.1:6379/0`). La comprobación es un `PING` con timeout
   de 1 s.
2. **El fixture usa un cliente con timeout de socket corto** y, si
   Redis no está accesible, **no se reintenta en cada test**.
3. El aislamiento por PID de la base de Redis (8..15) **ahora funciona
   en todas partes**: en el host también.

**Medido**: la suite del host pasa de **25+ min a 6,7 min** (587 passed,
9 skipped) y **sin** los fallos de `test_costs.py`. El contenedor sigue
igual (585 en SQLite; 595 contra PostgreSQL). El CI no cambia de
comportamiento: allí `REDIS_URL` viene en el entorno.


### 3-trigésimotercera. La QA recogía los errores de red y de consola, los imprimía y no fallaba (2026-10-22)

La QA visual ya recogía **dos** cosas que no llegaban al veredicto: las
**peticiones fallidas (4xx/5xx)** y los **errores de consola**. Los
imprimía en el informe y en la salida… y devolvía el código 0. Es decir:
una pantalla cuyo `fetch` devolviera un 500 (o con un error de
JavaScript) dejaba **la puerta en verde**.

**Por qué importa más de lo que parece**: la QA es la única puerta que
mira la app **en funcionamiento**. Todo lo demás (la suite, los
linters, las comprobaciones estáticas) ve el código; la QA ve **lo que el
usuario ve**. Si el fetch de una pantalla falla, la pantalla se queda en
blanco o vacía, y eso era justo lo que la puerta no valoraba.

**Por qué no se vio antes**: en el entorno actual hay **0 peticiones
fallidas y 0 errores de consola** (medido en las 26 pantallas × 5
anchos), así que la puerta "funcionaba" por casualidad. El fallo era
**latente**: aparecería el primer día que un endpoint devolviera un 500.

**El arreglo**:

- El veredicto pasa a una función pura `_evaluar(resultados,
  errores_login)` que devuelve `(código, motivos)` y cuenta también las
  peticiones fallidas y los errores de consola.
- **Sólo los *errores* de consola rompen la puerta; los *avisos* se
  informan pero no la rompen.** Una puerta que falla por ruido acaba
  apagada, y eso es peor que un aviso. (La diferencia se nota justo al
  arreglar esto: el handler de consola recogía `error` **y** `warning`
  en la misma lista.)
- **Las peticiones que nunca reciben respuesta** (conexión rechazada,
  DNS, abortada) no emiten `response`: emiten `requestfailed`. Sin esa
  escucha, ese fallo era invisible para la puerta. Ahora se recogen como
  `SIN RESPUESTA <método> <url> (<motivo>)`.
- **PERO `net::ERR_ABORTED` no es un fallo**: es el navegador cancelando
  una petición que la app ya no espera (al cambiar de pantalla antes de
  que termine el fetch, o al cerrar el **SSE** `/parkings/{id}/events`,
  que está abierto por diseño). Al añadir la escucha aparecieron 13
  "fallos" que eran todos abortos: el SSE en las 5 anchuras y dos
  fetches al cambiar de pantalla. Las cancelaciones se cuentan aparte y
  se informan ("13 peticiones canceladas (no son fallos)"); el resto de
  fallos de red (conexión rechazada, DNS, reset, timeout) **sí** rompen
  la puerta.
- La autoprueba de la QA pasa de 5 a **12 casos**: además de los del
  detector de desbordes, comprueba que una petición fallida, un error de
  consola y un fallo de login **ponen la puerta en rojo**, y que **un
  aviso de consola** y **una petición cancelada** no la rompen.


### 3-trigésimocuarta. La caché del service worker nunca se purga, y el build se rompía en silencio (2026-10-22)

**La caché**: `frontend/public/sw.js` usaba `const VERSION = 'v1'` **fijo**.
El plugin de Vite inyecta la lista de assets del build en `dist/sw.js`, así
que el service worker **sí** se actualiza en cada despliegue (el byte
cambia) → el `activate` borra las cachés cuyo nombre **no** sea el
actual… pero como el nombre era siempre el mismo
(`solidapp-estaticos-v1`), **nunca se borraba nada**: los assets de cada
despliegue se acumulaban **para siempre** en el móvil del cliente. El
handler `activate` existía exactamente para eso, pero no podía hacer
nada.

**El build**: el plugin hacía `sw.replace('/* __ASSETS_BUILD__ */',
inyeccion)`. Si alguien renombraba ese marcador, el `replace` **no hacía
nada y el build terminaba en verde**: la PWA se quedaba sin la lista de
assets, la app abría sin conexión **pero en blanco**, y nadie se enteraba
hasta que un cliente la instalaba.

**El arreglo**:

1. **La versión de la caché va dentro del nombre y cambia con cada
   build**: `const VERSION = 'v1-<hash>'`, donde el hash es el SHA-256 de
   la lista de assets (12 hex). Ahora el `activate` **sí** purga la caché
   anterior, que es justo lo que estaba para hacer. El hash es de
   **contenido**: el mismo build da el mismo nombre (idempotente) y un
   build con otro contenido da otro.
2. **El build falla si falta el marcador** o si no encuentra la
   constante `VERSION` en `public/sw.js`, con un mensaje que dice qué
   hacer. Una PWA rota tiene que romper el build, no aparecer en
   producción.

**Verificado**: el build inyecta la versión (`36 assets para precachear
(versión v1-a2283906863f)`), el hash es **estable** entre builds con el
mismo contenido, y **renombrando el marcador el build falla** con
`error during build: solidapp-pwa-precache: no se encuentra el
marcador…` y código 1 (antes: build verde y PWA rota).


### 3-trigésimonovena. No había imagen de producción del frontend, y los requisitos del servidor no los cumplía nadie (2026-10-22)

El único `frontend/Dockerfile` era el de **desarrollo** (Vite con HMR), con
un comentario que lo reconocía: *"para producción usaríamos `npm run build`
+ nginx, fuera del MVP"*.

Pero `frontend/README.md` (§ PWA) documenta **los tres requisitos que
tiene que cumplir el servidor estático de producción** (el manifiesto con
su content-type, el service worker sin caché y el `index.html` sin caché) —
y **nadie los cumplía**, porque no había servidor de producción: la QA del
PWA servía el build con un `http.server` de usar y tirar.

**El arreglo (3 cosas)**:

1. **`frontend/nginx/templates/default.conf.template`**: la configuración
   de nginx que cumple los tres requisitos, más el proxy de `/api` (el
   bundle usa rutas relativas a propósito), el fallback de la SPA
   (`try_files … /index.html`), el cacheo inmutable de los assets con hash
   y la sonda `/healthz`.
2. **`frontend/Dockerfile.prod`**: imagen multi-etapa (node:20-alpine
   construye → nginx:1.27-alpine sirve), con `ENV API_UPSTREAM` para el
   proxy y `HEALTHCHECK`.
3. **`frontend/scripts/verificar_servidor_produccion.py`** + un paso en el
   job `docker-build` del CI: levanta la imagen y **comprueba de verdad**
   los requisitos contra el contenedor (no "debería funcionar": se mide).

**Dos fallos que sólo aparecieron al verificar** (y que habrían roto la
app en producción):

- **`${API_UPSTREAM:-http://backend:8000}`**: el `envsubst` de la imagen
  de nginx sólo sustituye las variables que existen **tal cual** (no
  entiende la sintaxis `:-`), así que nginx se comía el texto y **no
  arrancaba**. El valor por defecto va ahora en el `ENV` de la imagen.
- **El bloque `types` de nginx sustituye el mapa MIME heredado** (no lo
  amplía). Con el tipo del manifiesto declarado a nivel de `server`, el
  JS y el HTML se servían como `application/octet-stream` y **el
  navegador no ejecutaba el bundle**. El tipo del manifiesto se declara
  ahora **sólo** en su ubicación, y el resto conserva el mapa heredado.

**Verificado**: la imagen se construye, el contenedor queda *healthy*, los
tres requisitos se cumplen **medidos**, el bundle se sirve como
`application/javascript` con `immutable`, el fallback de la SPA devuelve
el shell en `/mis-tickets`, y el proxy de `/api` responde (login a través
del proxy → 200 con token).

### 3-trigésimotrigésima. La puerta del servidor de producción no podía fallar, y el paso del CI tapaba su fallo (2026-10-22)

Dos defectos en lo que se había añadido el día antes (T-56):

1. **La puerta era una puerta de mentira.**
   `frontend/scripts/verificar_servidor_produccion.sh` corría **dentro**
   del contenedor con el `wget` de busybox: sin `wget` en el host y sin
   forma de inyectar un servidor de mentira, nadie podía comprobar que
   detectara lo que dice detectar.
2. **El paso del CI tapaba el fallo.** El `docker rm` de limpieza era el
   último comando del bloque `run:` y su `0` enmascaraba el fallo de la
   verificación: un servidor de producción roto pasaba el CI en verde.

**El arreglo**:

- La puerta se reescribe en **Python con la biblioteca estándar**
  (`frontend/scripts/verificar_servidor_produccion.py`): habla con el
  servidor por HTTP y trae `--autoprueba`, que levanta un **servidor de
  mentira escrito a mano** (no derivado de la config real de nginx).
- El paso del CI **propaga el código de salida**:
  `codigo=0; … || codigo=$?; docker rm … || true; exit $codigo`.
- La réplica local fija `MSYS_NO_PATHCONV=1` y `MSYS2_ARG_CONV_EXCL=*`
  para que Git Bash no convierta las rutas POSIX al pasarlas a programas
  Windows.

**Verificado**: 5/5 requisitos contra el contenedor real; 5/5 fallos
detectados contra el **mismo contenedor con la config de nginx mutada**;
5 mutaciones de la puerta detectadas por su autoprueba; y el job
`docker-build` en **rojo** cuando la puerta falla.

### 3-trigésimocuarta. La QA del PWA verificaba la PWA sobre un servidor que no cumplía los requisitos (2026-10-22)

Con la puerta de T-57 (que mide los requisitos del servidor **por HTTP**)
se pudieron medir los servidores que el repo usa de verdad:

| Servidor | Requisitos |
|---|---|
| Imagen de producción (nginx) | **5/5** |
| `npm run preview` (Vite) | **5/5** |
| El servidor de la QA del PWA | **2/5** → ahora **5/5** |

Al de la QA le faltaban el `no-store` del service worker, el `no-cache` del
`index.html` y el fallback de la SPA (una ruta profunda daba 404). Es decir:
la PWA se verificaba sobre un servidor que el usuario real no tiene, y la
QA lo daba por bueno.

**El arreglo**: `qa_pwa.py` sirve el build con las mismas cabeceras que el
servidor de producción (y declara el tipo del manifiesto sin depender de la
versión de Python), y **mide los cinco requisitos con la misma puerta del
CI** en vez de reimplementarlos.

**Verificado**: la QA sigue en verde con 5/5, y se pone en **rojo** (código 1,
3 requisitos señalados) contra un servidor que incumple.

### 3-trigésimocuarta. El rate-limit de login se esquivaba cambiando el `Content-Type` (2026-10-22)

`POST /auth/login` (JSON) limitaba por IP y email (10 intentos / 5 min);
`POST /auth/login/oauth` (form-urlencoded) hacía el mismo `verify_password`
**sin pasar por el limitador**.

Medido contra la API en marcha:

| Vía | 15 intentos |
|---|---|
| OAuth2 | **15 × 401, ningún 429** |
| JSON | `[401, 401, 401, 401, 429, 429, …]` |

**El arreglo**: el limitador se extrae a una función compartida que llaman
las dos vías, más dos tests (la vía OAuth2 da 429; alternar las vías no
esquiva el límite). Probado que los tests detectan el defecto
reintroducido.

### 3-trigésimoquinta. nginx rechazaba con 413 las fotos de los incidentes (2026-10-22)

nginx limita el tamaño de la petición a **1 MB** si no se dice nada; el
backend acepta 3 × 10 MB. Medido: una petición de 2 MB devolvía el 413 de
nginx (HTML) y el backend no la veía. En desarrollo (Vite) no hay límite.

**El arreglo**: `client_max_body_size 32m;` + `tools/verificar_nginx_body_size.py`,
que compara el límite de nginx con el tope real del backend (leído del
`config.py`) para que los dos no se desincronicen en silencio.

### 3-trigésimosexta. El correo de recuperación apuntaba a localhost:5173 (2026-10-22)

El enlace del correo de "restablece tu contraseña" era una constante a
`http://localhost:5173`: en producción el cliente pulsaba el enlace y no
llegaba a nada.

**El arreglo**: nuevo ajuste `FRONTEND_BASE_URL`; en staging/producción la
aplicación **no arranca** si no es una URL real por HTTPS (mismo patrón
que el secreto JWT).

### 3-trigésimoséptima. La IP del cliente la elegía el atacante (2026-10-22)

`get_real_ip` tomaba el **primer** elemento del `X-Forwarded-For` (el que
escribe el cliente) y nginx **concatenaba** el XFF del cliente: mandando un
XFF distinto en cada intento se esquivaba el rate-limit de login. Además,
tres endpoints auditaban `request.client.host` (la IP del proxy).

**El arreglo**: se toma el **último** elemento (el que añade el proxy de
confianza), nginx **sobreescribe** el XFF con `$remote_addr`, y los tres
endpoints usan `get_real_ip`. Con `backend/tests/test_ip.py` y un test
funcional de la auditoría.

### 3-trigésimoctava. La imagen de producción arrastraba el `node_modules` del host (2026-10-22)

El contexto de build de `frontend/Dockerfile.prod` es `frontend/`, y Docker
busca el `.dockerignore` en la raíz del **contexto**: el de la raíz del
repositorio no se aplica. El `COPY . .` se llevaba el `node_modules` del
host (el de Windows) dentro de la imagen.

**El arreglo**: `frontend/.dockerignore` + `tools/verificar_contexto_build.py`.

### 3-trigésimonovena. Dos ajustes de lista no se podían configurar (2026-10-22)

`pydantic-settings` sólo entiende JSON para los campos `list`, así que
`TRUSTED_PROXIES="172.16.0.0/12,10.0.0.0/8"` (el formato que documenta el
propio `config.py`) **fallaba al arrancar**. Sin esa variable, el backend
no sabe qué IP es la del cliente: el rate-limit de login se comparte para
toda la sucursal y la auditoría guarda la IP del proxy.

**El arreglo**: un validador que acepta comas y JSON, aplicado a
`trusted_proxies` y `heartbeat_skip_url_prefixes`, y la variable visible
en el `docker-compose.yml`.

### 3-trigésimotrigésima. Dos suites en paralelo se rompían mutuamente (2026-10-22)

La base de Redis de la suite se elegía con `8 + (pid % 8)`: dos PIDs que
difieren en un múltiplo de 8 compartían base, y cada suite borraba los
contadores de la otra al limpiar.

Medido: las dos suites del host en paralelo (SQLite y PostgreSQL) →
**5 fallos en cada una**, todos de rate-limit ("esperaba 429, obtuve
201"). En solitario, las dos pasaban.

**El arreglo**: cada ejecución reclama su base con un lock `SET NX` (con
caducidad de una hora) y, si está ocupada, prueba la siguiente.

### 3-trigésimotrigésimoprimera. El modo PWA se quedaba pegado en el navegador (2026-10-22)

`frontend/src/pwa/mode.ts` guardaba el flag del modo PWA en `localStorage`
y lo leía **antes** que la señal real (`display-mode: standalone`): un
admin que abría la app con `?pwa=1` quedaba encerrado en las rutas de
cliente para siempre, sin forma de volver al panel de administración.

**El arreglo**: el flag se recuerda en `sessionStorage` (la pestaña) y el
flag viejo se borra. La QA visual lo vigila: con `?pwa=1` una ruta de
admin redirige a "Mis tickets", y en **otra pestaña** (donde el
`localStorage` se comparte pero el `sessionStorage` no) la ruta de admin
se respeta.

### 3-trigésimotrigésimosegunda. Las regex de nginx ganaban al prefijo `/api/` (2026-10-22)

En nginx las locations de regex se comprueban antes que las de prefijo:
una petición a `/api/v1/algo.png` se servía desde el disco en vez de ir
a la API. Hoy no afecta a ningún endpoint, pero es una trampa.

**El arreglo**: `location ^~ /api/`.

### 3-trigésimotrigésimotercera. El flag `no_rate_limit` no hacía nada, y el rate-limit estaba en seis copias (2026-10-22)

- El campo `User.no_rate_limit` prometía que las cuentas de servicio se
  saltan el rate-limit, y el mecanismo (`check(skip=True)`) existía con su
  test... pero **nadie lo pedía**: una cuenta de servicio se comía un 429
  igual que un humano.
- Y el helper del rate-limit por endpoint estaba **copiado** en cinco
  routers, con un sexto escrito en línea: seis copias del mismo código.

**El arreglo**: una única función `enforce_endpoint_rate_limit` en
`app/services/endpoint_rate_limit.py` (fail-open si Redis cae, audit
`rate_limited_endpoint`) que además consulta al actor y respeta su flag;
los seis routers delegan. La puerta `tools/verificar_rate_limit_unico.py`
vigila que no vuelva a haber copias y que el flag se lea.

### 3-trigésimotrigésimocuarta. La puerta del repo se caía en Windows (2026-10-22)

`tools/verificar_repo.py` decodificaba a ciegas la salida de los
subprocesos como UTF-8. Si el hijo escribía en cp1252 (la consola de
Windows), las tildes salían como `U+FFFD` y el `print` reventaba con
`UnicodeEncodeError`: **la puerta del repo se caía entera** en cuanto una
comprobación devolvía un resumen con acentos.

**El arreglo**: los subprocesos escriben en UTF-8, la salida se captura en
bytes y se decodifica con fallback (UTF-8 y, si no, cp1252), el `print`
pasa por `_consola()` (que ya existía y no se usaba) y el script fuerza
UTF-8 en su salida.

### 3-trigésimotrigésimoquinta. El build de producción no era reproducible (2026-10-22)

`npm ci || npm install` (en el `Dockerfile.prod` y en el job `frontend` del
CI): si el lockfile estaba desincronizado, la imagen se construía con las
**últimas versiones del registro**, sin lockfile, y el fallo quedaba
escondido. Peor: sin el `.dockerignore` de T-63, el `npm ci` de la imagen
fallaba y **el fallback era el que se usaba**.

**El arreglo**: `npm ci` a secas en los dos sitios, más
`tools/verificar_lockfile.py` (compara el `package.json` con el
`package-lock.json` y avisa antes de instalar).

### 3-trigésimotrigésimosexto. El comando del AGENTS.md para probar el frontend no funcionaba (2026-10-22)

Montar `frontend/` en un contenedor también montaba el `node_modules`
**del host** (de Windows), y `npm ci` falla al borrarlo con `EIO`. El
volumen anónimo `-v /app/node_modules` lo arregla.

### 3-trigésimotrigésimosexto. La réplica local del job `frontend` se caía en Windows (2026-10-22)

`npm ci` en el host (Windows) no puede borrar `node_modules` ("the file
was already in use"), así que la réplica local del job `frontend` se caía
siempre y ese job no se había podido verificar de principio a fin.

**El arreglo**: en la réplica local, los comandos `npm`/`npx` de ese job
corren dentro de un contenedor `node:20` (la versión del CI), con el
`node_modules` en un volumen con nombre compartido entre los pasos del
job.


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

- `AGENTS.md` — cómo se trabaja en este repo: la convención de las
  puertas, los comandos verificados y las trampas de este entorno.
- `docs/adr/0001-orquestacion-produccion.md` — Compose en el edge, K8s en el central.
- `docs/adr/0002-ocr-cpu-vs-gpu.md` — la GPU no aporta con la carga real.
- `docs/API-INTERNAL.md` — los 101 endpoints con su RBAC y la política de deprecación.
- `infra/backup/README.md` — procedimiento de backup, restauración y simulacro trimestral.
- `backend/locust/README.md` — escenarios de carga y SLO.
- `docker/vehicle-detector/README.md` — el modelo real y el bug de canales BGR/RGB.
- `frontend/README.md` — PWA, QA visual y la trampa del HMR en Docker Desktop/Windows.
