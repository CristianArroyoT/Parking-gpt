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

Resultado medido: **0 desbordes** en las 21 pantallas a los **cinco**
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
| QA visual en 414 / 768 / 1024 / 1232 / 1440 px | 5 × 21 pantallas, 0 desbordes |
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

Y con el IPv4 arreglado, la réplica local pasó a poder ejecutar **el CI
completo**, incluidos los dos pasos de test que antes se saltaban
porque el host no resolvía los nombres de servicio de Docker:

| Paso del CI | En el host |
|---|---|
| Tests (pytest, SQLite) | **563 passed**, 9 skipped |
| Tests contra PostgreSQL (pytest) | **572 passed** |
| Test de funciones sólo de SQLite | **13 passed** |
| Type-check (vue-tsc) y build del frontend | exit 0 |
| Los cuatro jobs | **VERDE** |

O sea: mientras la facturación de GitHub siga pendiente, la réplica local
es el **CI completo** de facto. Lo que falta para cerrar el criterio es
sólo que GitHub deje de rechazar los jobs.


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
- `docs/API-INTERNAL.md` — los 101 endpoints con su RBAC y la política de deprecación.
- `infra/backup/README.md` — procedimiento de backup, restauración y simulacro trimestral.
- `backend/locust/README.md` — escenarios de carga y SLO.
- `docker/vehicle-detector/README.md` — el modelo real y el bug de canales BGR/RGB.
- `frontend/README.md` — PWA, QA visual y la trampa del HMR en Docker Desktop/Windows.
