# AGENTS.md — solidAPP

Guía de trabajo para cualquier agente (o persona) que toque este repositorio.
Está escrita desde lo que **se ha comprobado**, no desde lo que debería ser:
cada comando de aquí se ha ejecutado y sale en verde.

## Qué es esto

Parking por cámara con reconocimiento de matrícula: backend FastAPI
(`backend/`), frontend Vue 3 + Vite (`frontend/`), orchestrated con
Docker Compose, CI en GitHub Actions (`.github/workflows/ci.yml`).

El estado del plan de trabajo (criterios verificados, qué queda, por qué)
está en **`docs/superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md`**.
El mapa de lo que se ha ido construyendo está en
**`docs/CODEMAPS/2026-10-21-cierre-del-plan.md`** (111 secciones `3-…`).

## La convención que más importa

**Toda puerta necesita una autoprueba.** Una comprobación que no puede
demostrar que detecta lo que dice detectar no es una puerta: es una
línea de texto que dice "OK". En este repo se ha encontrado **una
decena** de puertas así (el extractor de RBAC, el detector de
asimetrías, el linter del frontend, los healthchecks, el recuento de
endpoints, el linter de texto, el escáner de secretos...).

Al añadir una puerta nueva:

1. Dale una opción `--autoprueba` que la haga **fallar** ante un caso de
   mentira escrito a mano.
2. Comprueba que la autoprueba **falla** cuando reintroduces el defecto
   (no basta con que pase en verde).
3. Añádela a la lista de `tools/autopruebas.py`, que es la meta-puerta.
4. Y si el arreglo tiene un test que lo comprueba, **añade también la
   prueba inversa** a `tools/verificar_pruebas_inversas.py`: volver a poner
   el defecto y comprobar que el test **falla** (y que falla por una
   aserción, no por un error de código). Sin eso, un test reescrito
   puede dejar de detectar y el repo se queda en verde sin que nadie se
   entere (T-135).
   OJO: una puerta que **pone un defecto** no puede hacerlo en el
   repositorio: se hace sobre una **copia** en un directorio temporal. La
   primera versión lo hacía en su sitio, y al lanzar el CI en paralelo el
   job leyó el código con el defecto puesto y el árbol quedó sucio
   (T-135).

Ojo con un caso especial que ya costó un bug real: **dos comprobaciones
que comparten la fuente de verdad no se vigilan entre sí**. Si la puerta
A compara el documento contra el extractor B, y ambos salen del mismo
código, los dos pueden mentir a la vez y la puerta da el visto bueno.
Hace falta una **tercera** fuente: el caso de mentira escrito a mano.

Y el caso inverso, que también costó un bug real (T-137/T-140): **una
puerta no vigila nada si no se ejecuta después del último cambio**. El
defecto «la sesión caducada no expulsa al login» se dio por **refutado**
porque la medición se hizo **con el arreglo puesto en el árbol de
trabajo y sin commitear**; al revertirlo para hacer el commit, nadie
volvió a ejecutar la puerta, y se quedó en rojo sin que nadie lo notara.
Reglas:
- al **revertir** un cambio, vuelve a ejecutar la puerta que lo vigila;
- una puerta que mira el código lo mira **sin comentarios**: un
  comentario que menciona `router.replace({ name: 'login' })` no hace que
  el router expulse (y una puerta que lo creyera daría el visto bueno a
  un defecto);
- una «refutación por medición» se anota **cómo** se midió, o no sirve
  para cerrar nada.

Y un caso nuevo, que salió al **arrancar el CI remoto por primera vez**
(2026-10-24, al hacer el repositorio público): **una puerta que corre
en un job sin las dependencias del backend no puede importar la app**.
La puerta del compose de producción importaba `app.core.config` (que
necesita `pydantic`) para comprobar que sus variables cargan en
`Settings`: en el job de las autopruebas (que va **antes** del
`pip install`) y en el de las imágenes Docker (que no las instala) falló
con «No module named 'pydantic'», es decir, **por el entorno y no por lo
que vigila**. Reglas:
- o la puerta no depende de la app (la del aislamiento por sucursal usa
  `ast`, por eso puede ir antes del `pip install`), o el job donde corre
  la instala;
- y si de verdad no puede comprobar algo, que lo **diga** (un aviso), no
  que lo calle: un verde silencioso sobre una comprobación que no se ha
  hecho no vale.

## Comandos que funcionan (verificados)

```bash
# La salud del repo en un comando: 32 comprobaciones (~5 min)
python tools/verificar_repo.py
python tools/verificar_repo.py --completo      # + CI local y QA en 5 anchos (~40 min)

# Las 29 autopruebas de las puertas
python tools/autopruebas.py
python tools/autopruebas.py --estricto          # lo "no comprobado" tambien falla

# Suite (contenedor Docker)
docker exec parking-backend-1 pytest -q                                   # SQLite
docker exec -e TEST_DATABASE_URL="postgresql+psycopg://parking:parking@db:5432/parking_test_mavis" \
  parking-backend-1 pytest -q                                             # PostgreSQL

# Lint y tipos
cd backend && ruff check app tests ../tools && mypy app
cd frontend && npm run lint && npx vue-tsc --noEmit

# El CI remoto, replicado en local (lee el YAML del workflow)
python tools/ejecutar_ci_local.py --all
python tools/ejecutar_ci_local.py --list

# Puertas sueltas
python tools/verificar_api_doc.py --autoprueba
python tools/verificar_aislamiento_sucursal.py --autoprueba
python tools/verificar_cache_service_worker.py --autoprueba
python tools/verificar_sesion_caducada.py --autoprueba
python tools/verificar_volumen_adjuntos.py --autoprueba
python tools/verificar_retention_backup.py --autoprueba
python tools/verificar_pruebas_inversas.py --autoprueba
python tools/verificar_roles_frontend.py --autoprueba
python tools/verificar_contrato_frontend.py --autoprueba
python tools/verificar_cuentas_demo.py --autoprueba
python tools/verificar_cobertura_frontend.py --autoprueba
python tools/verificar_enums_frontend.py --autoprueba
python tools/verificar_tareas_celery.py --autoprueba
python tools/verificar_ajustes_muertos.py --autoprueba
python frontend/scripts/verificar_servidor_produccion.py --autoprueba
python tools/verificar_nginx_body_size.py --autoprueba
python tools/verificar_contexto_build.py --autoprueba
python tools/verificar_rate_limit_unico.py --autoprueba
python tools/verificar_lockfile.py --autoprueba
python tools/verificar_dependencias.py --autoprueba   # OSV: vulnerabilidades
python tools/verificar_compose_produccion.py --autoprueba
python tools/verificar_readme_despliegue.py --autoprueba
python tools/extraer_api.py --autoprueba
python tools/revisar_esquemas.py --autoprueba
python tools/cobertura_api.py --autoprueba
python tools/escanear_texto.py --tracked
python tools/escanear_secretos.py --historial

# El workflow, validado
docker run --rm -v "D:\Parking:/repo" -w /repo rhysd/actionlint:latest .github/workflows/ci.yml
```

## Reglas del repo

- **El texto generado se corrompe** con caracteres CJK/cirílicos/coreanos.
  **Antes de commitear**, siempre:
  `python tools/escanear_texto.py <rutas>` (informe en `tools/_informe_texto.txt`).
  El hook `.githooks/pre-commit` lo hace por ti, pero conviene activarlo:
  `git config core.hooksPath .githooks`.
- **No sobrescribir trabajo ajeno.** Nunca `git add .`: usa
  `git add <fichero>` y `git commit -- <fichero>`. En este workspace hay
  dos directorios de otra sesión (`deck-aussa/`, `graphify-out/`): no se
  tocan ni se commitean.
- **El plan no se toca sin criterio comprobable**: toda cifra documentada
  se contrasta con un comando real, y las líneas base se miden
  restaurando el commit anterior.
- **El workflow del CI no se toca sin poder validarlo**: los cambios en
  `.github/workflows/ci.yml` se validan con `tools/ejecutar_ci_local.py`.
- **Los secretos de mentira** de las autopruebas se construyen en
  runtime, nunca en el repo (el repositorio es público).
- `infra/backup/*.sh` necesitan el bit de ejecución (100755): sin él, en
  Linux el `cron` no haría backups y nadie se entera.
- **El aislamiento por sucursal se mide, no se supone**: antes de dar
  por bueno un endpoint que recibe o devuelve datos de una sucursal,
  mídelo con dos sucursales y dos usuarios (uno de cada). Cuatro
  endpoints se escaparon por no hacerlo (T-113…T-116).

## El aislamiento por sucursal (T-113…T-116)

El modelo **no tiene `client_id`**: el aislamiento entre sucursales se
hace con `parking_memberships` (quién pertenece a qué sucursal) y con los
roles (`admin`, `gestor`, `operador`, `cliente`). Cuatro reglas, y cada
una costó un bug real:

1. **El alcance lo decide el ROL GLOBAL, no la membresía.**
   `enforce_parking_membership` (`backend/app/core/deps.py`) rechaza a
   quien no sea de personal **aunque** tenga la fila de membresía. Antes
   un conductor (`role=cliente`) con una membresía se convertía en gestor
   de la sucursal: creaba plazas, creaba cámaras y **fijaba el precio**.
   Los roles de personal viven en `ROLES_STAFF` (deps.py): una sola
   definición.
2. **Un endpoint que acepta `parking_id` en el cuerpo tiene que validar
   la membresía**: `parking_context(payload.parking_id, current=user,
   db=db)`. El patrón estaba en `POST /tickets/manual` y faltaba en
   `POST /tickets`: un gestor escribía en la contabilidad de otra
   sucursal, y el ticket creado no lo podía ni ver (404).
3. **Un endpoint que carga un recurso por id tiene que cruzarlo con el
   `parking_id` del path.** `GET`/`PATCH` de geocercas no comprobaban que
   la cámara fuera de esa sucursal: un gestor leía y **modificaba** las
   geocercas de otra, y el OCR de aquella dejaba de detectar entradas
   (y de facturar). El helper único es `_camara_de_sucursal`.
4. **Los listados globales son de admin; el personal usa el endpoint
   acotado.** `GET /vehicles` (la flota entera) es de admin; con `plate`
   sigue siendo una búsqueda dirigida del personal. Para los vehículos de
   una sucursal: `GET /parkings/{id}/vehicles`.

## El RBAC por sucursal (T-178, decisión del usuario del 2026-10-24)

`role_in_parking` (la columna «de qué rol es en **esta** sucursal») **ya se
lee**: es la fuente de la autorización por sucursal. El modelo (decidido por
el usuario y documentado en
[`docs/adr/0005-rbac-por-sucursal.md`](docs/adr/0005-rbac-por-sucursal.md)):

> **El rol global es el TECHO; el rol de la sucursal es el PODER real.**
> Jerarquía: `admin > gestor > operador > cliente`.

1. `admin` global ⇒ poder **global** (sin membresía), como antes.
2. Para el resto, el **rol efectivo** en la sucursal X es el **más
   restrictivo** entre su rol global y `role_in_parking` de esa sucursal.
3. Si el rol efectivo no es de personal ⇒ esa sucursal queda **vedada**
   (403), aunque tenga la membresía (sigue siendo cierto lo del T-114).
4. `role_in_parking` **nunca** da más poder que el rol global: un `cliente`
   global con `role_in_parking='gestor'` sigue siendo cliente.

El helper único es `effective_parking_role(user, parking_id, db)`
(`backend/app/core/deps.py`): `enforce_parking_membership` y
`require_parking_role(...)` lo usan. **Un endpoint acotado a una sucursal
tiene que mirar el rol de ESA sucursal, no el global**: un `operador`
global que es `gestor` en la sucursal A puede hacer lo de gestor en A y no
en B.

OJO: `admin` **no** es un rol por sucursal: mandarlo en `role_in_parking` es
**422** (el admin es global). Y las membresías se gestionan desde la
interfaz del admin (T-179).

La decisión anterior (el aislamiento por sucursal) está en
[`docs/adr/0003-aislamiento-por-sucursal.md`](docs/adr/0003-aislamiento-por-sucursal.md).

La puerta que vigila el patrón está en
`tools/verificar_aislamiento_sucursal.py` (con su autoprueba: reintroduce
los cuatro defectos y comprueba que los detecta).

## El cobro de los tickets (T-120...T-126)

Cuatro reglas, y cada una costó un agujero de cobro (medidos contra el
sistema en marcha, no leyendo codigo):

1. **Cerrar un ticket es del personal.**
   `POST /tickets/{id}/close` exige `require_role(*ROLES_STAFF)`: un
   conductor no cierra su propia estancia, ni se fija la hora de salida,
   ni por tanto el importe. Los tickets los cierra la camara de salida o
   el personal, a mano.
2. **El cierre es condicional.** Se hace con un
   `UPDATE ... WHERE status = 'activo'`, de modo que la comprobacion y
   la escritura son la misma sentencia. Sin eso, un cierre de la camara
   y uno manual a la vez **los dos tienen exito** y el ultimo que
   commite manda sobre el importe.
3. **La matricula se normaliza antes de buscar el vehiculo.** Con el
   texto crudo del OCR, la entrada "1234abc" y la salida "1234ABC" son
   dos coches: la salida no encuentra el ticket (no cobra) y el de la
   entrada se queda activo para siempre.
4. **Los errores se dicen.** Un fallo inesperado es `skipped_error`, no
   `skipped_no_geofence` ("no hay geocerca"): una explicacion falsa
   esconde la causa.
5. **El importe de un ticket cuadra** (T-131). Se redondea **una sola
   vez y en este orden**: importe, luego descuento (calculado sobre el
   importe ya redondeado) y por ultimo el total, que es la diferencia de
   los dos valores redondeados. Redondear el total antes (o redondear
   cada parte por separado) hacia que el PDF enseñase "2,67 - 1,34 =
   1,34".
6. **Las fotos se guardan sin metadatos** (T-129). El original se
   re-codifica sin EXIF (se conservan los pixeles y la orientacion): una
   foto de movil lleva la GPS de donde se hizo, y eso sale del sistema
   con cada descarga.
7. **Los vehiculos «fantasma» se purgan a diario** (T-125). La ingesta
   crea el vehiculo de una matricula desconocida *antes* de saber si
   habra ticket: si la plaza esta ocupada o averiada, el intento se queda
   a medias y el vehiculo se queda sin dueno y sin ticket. La tarea
   `solidapp.purge_ghost_vehicles` (beat, 4:23 AM) borra los que cumplen
   **las tres** condiciones: sin dueno, sin tickets y antiguo (> 24 h).
   Ojo: al anadir una tarea hay que **reiniciar el worker**
   (`docker compose restart celery-worker`), si no sigue con el codigo
   viejo en memoria y la tarea no existe.
8. **Un usuario tiene como mucho una suscripción vigente** (T-133), y
   "vigente" quiere decir **sin solape de periodos**: dos suscripciones
   que se pisan dan el descuento mayor y una de las dos se queda sin
   ver en `/plans/me`.

Y lo que **no** hay que inventar: si un hallazgo es una decision de
producto (que hacer con un coche que no sale; si se cobra lo que se
cobra), se documenta medido y se decide con el usuario, no se arregla
por las buenas. Ver T-124 y T-125 en el plan.

## Trampas de este entorno (Windows + Docker Desktop)

- `localhost` en Windows resuelve primero a IPv6 (`::1`) y `psycopg`
  tarda 8,4 s. Usa `127.0.0.1` (el CI local lo convierte solo).
  **Ojo (2026-10-24, T-148)**: esto no es sólo un problema de `psycopg`.
  El dev-server de Vite (en el contenedor, con `--host 0.0.0.0`) **no
  escucha en IPv6**, así que una QA de navegador que apunte a
  `localhost:5173` se queda **30 s en timeout** en `Page.goto` y parece
  que la app está rota cuando el backend y el frontend están
  perfectamente bien. Medido: por `127.0.0.1` responde en 0 ms; por
  `::1`, timeout. Las QAS usan `127.0.0.1` por eso.
- En Docker Desktop el bind mount **sí** sincroniza contenido; lo único
  que falla es el HMR de Vite. Tras tocar el frontend:
  `docker compose restart frontend`.
- `docker exec` con `sh -lc` reinicia el PATH y pierde el venv: usa
  `sh -c` o `python -m uvicorn`.
- Locust tiene que correr **dentro** de la red Docker
  (`--network parking_default`).
- `task_stop` **no** mata a los hijos: hubo tres ejecuciones del CI local
  peleándose por las mismas bases de datos. Y **no lances la suite del host
  y la del contenedor a la vez**: la del host se queda **colgada con 0 %
  de CPU** (no es un test lento, es un bloqueo) y hay que matarla. Lanza
  una, espera, y luego la otra.
- **Un test de tiempos es frágil si la máquina está saturada**: medido el
  2026-10-23, la suite del contenedor dio **12 fallos** (los que dependen
  de Redis agotando el tiempo de espera) mientras el CI replicado corría
  en paralelo en el host; con la máquina idle los mismos tests pasan. Por
  eso el test de latencia del login (T-86) compara de forma **relativa**
  al coste del bcrypt (un ratio) y no con un umbral en segundos: así da el
  mismo veredicto en un portátil lento y en un servidor, y la mutación
  (quitar el hash señuelo) sigue detectándose (el ratio pasa de ~1 a ~0,07).
- **No edites el frontend mientras corre la QA visual**: el dev-server de
  Vite recarga al cambiar un fichero y **resetea las conexiones abiertas**
  (`ERR_CONNECTION_RESET` en el WebSocket del HMR y en los módulos que
  Vite estaba sirviendo). Medido el 2026-10-23: 20 peticiones fallidas
  y 18 errores de consola que no eran de la app, sino del servidor de
  desarrollo reiniciándose. Repetida sin tocar nada: 0 y 0.
- **Reiniciar el frontend justo antes de la QA visual tambien la arruina**
  (2026-10-23): al arrancar, Vite **reoptimiza las dependencias**
  (escribe en `node_modules/.vite`), esa escritura se sincroniza por el
  bind mount y el dev-server se reinicia otra vez. Medido: con
  `docker compose restart frontend` + 20 s de margen, la QA salio con 5
  peticiones fallidas y 8 errores de consola, **todas** `ERR_CONNECTION_RESET`
  (módulos `/src/...`, `node_modules/vite/dist/client/env.mjs` y el
  WebSocket del HMR); **sin** reiniciar (frontend ya caliente + 30 s),
  130 capturas y **0 y 0**. Ojo: el `informe.json` se escribe al final, y
  hasta entonces es el de la ejecución anterior.
- **El dev-server de Vite puede dejar de responder SIN reiniciarse**
  (2026-10-23): con la máquina saturada (otras sesiones), el contenedor
  del frontend sigue `healthy` y sus logs muestran **un único arranque**,
  pero Vite deja de aceptar conexiones: la QA visual falla con
  `ERR_CONNECTION_RESET` en **todas** las peticiones y `Page.goto` a 30
  s, y no llega ni una sola petición al backend. No es un fallo de la
  app, y se distingue así: **ninguna** petición llega al backend y el
  contenedor no se reinició (logs con un solo arranque). La solución es
  dejar que la máquina se calme y reintentar; con la máquina libre, la
  misma QA da 130 capturas y 0 y 0.
- **Dos suites del host sí pueden ir en paralelo** (SQLite y PostgreSQL a
  la vez): la base de Redis de cada una se **toma con un lock** (`SET NX`).
  Pero **dos suites de PostgreSQL no**: la segunda hace `DROP DATABASE` de
  la que está usando la primera. Medido el 2026-10-23: **491 errores** (no
  fallos del código, sino la base de datos disappearing debajo). Se
  reconoce por el patron: todos los tests de un fichero fallan con
  «no such table».
  Antes se elegía con `8 + (pid % 8)`, y dos PIDs que difieren en un
  múltiplo de 8 compartían base: las dos suites se rompían mutuamente los
  tests de rate-limit (medido el 2026-10-22: 5 fallos en cada una).
- La salida por tubería en subprocesos puede colgarse esperando EOF:
  manda la salida a un fichero temporal.
- La consola de Windows es cp1252: fuerza `encoding="utf-8",
  errors="replace"` y escribe los informes a fichero UTF-8.
- `rm` está bloqueado: para borrar usa
  `& "C:\Users\catvi\.minimax\bin\mavis-trash.cmd" -- "<ruta>"` (un
  objetivo por invocación).
- PowerShell 5.1 no soporta `&&` ni `||`. No uses `tail` fuera de un
  `docker exec`: es un binario de Unix.
- **La IP que ve el backend decide a quién bloquea el rate-limit de
  login** (2026-10-25, T-183): en una sucursal el tráfico es
  `navegador -> terminador de TLS -> nginx -> backend`, y nginx ve al
  **terminador**, no al visitante. Sin el módulo `realip` (que la
  plantilla de producción ya trae) todos los clientes de la sucursal
  comparten un único bucket: medido, dos clientes distintos dejaban
  `rl:login:ip:172.17.0.1 = 2`, y con el límite de producción (10 por
  IP cada 5 min) el login 11 recibía un 429 para todos. La puerta
  `tools/verificar_ip_real_nginx.py` lo vigila (y que los rangos de nginx
  cubran los de `TRUSTED_PROXIES`).
- **`POST /auth/login` tiene rate-limit: 10 intentos por IP cada 5
  minutos**, y cuenta también los exitosos. En **desarrollo** el compose
  lo sube a **50** (`LOGIN_RATE_LIMIT_MAX_ATTEMPTS`, T-176): las puertas
  de QA hacen varios inicios de sesión seguidos desde la misma IP (el
  proxy de Vite) y, con 10, se pisaban entre ellas y fallaban con un 429
  que no tenía nada que ver con lo que vigilaban. **En producción sigue
  siendo 10** (`docker-compose.prod.yml` no lo toca). Aun así la ventana
  es fija: la QA visual inicia sesión una vez por rol, así que **no la
  lances 5 veces seguidas**: usa `python frontend/scripts/qa_visual.py
  --anchos "414,768,1024,1232,1440"`, que recorre los 5 anchos con 3
  inicios.
- La suite da **774 passed, 9 skipped** en SQLite y **783 passed** en PostgreSQL
  en el host (lo que ve el CI), y **773 passed, 10 skipped** / **782 passed, 1 skipped** en el
  contenedor de desarrollo: allí sólo se monta `backend/`, así que el test
  que comprueba la nota del README sobre el reconocimiento facial se salta
  (el contenedor no tiene el README). No es una deriva.
- **Ojo con qué ejecución se parece al CI**: el CI corre en **Linux con
  Python 3.11**, y el host es **Windows con 3.13**. El contenedor
  (`python:3.11-slim`, el mismo Python que el `Dockerfile`) es Linux y
  3.11: la ejecución del contenedor es la que más se parece al CI, y
  la del host la que menos. `docker exec parking-backend-1 pytest -q`
  (3.11 + Linux) es la referencia; `ejecutar_ci_local.py` replica los
  pasos del workflow **en el host**, así que no cubre ni la versión de
  Python ni el sistema operativo.
- **La réplica local no reproduce un runner limpio**: el host ya tiene
  instaladas muchas cosas que un runner de GitHub no tiene. Pasó: la
  autoprueba de la QA visual pedía `playwright`, que no es dependencia
  del backend, y en el CI el job `backend` habría muerto con
  `ModuleNotFoundError` (T-44). Para comprobar el arranque en frío de
  un paso, usa un venv vacío.
- **El host tampoco es la versión de Node ni de Python del CI** (Node
  24 vs 20, Python 3.13 vs 3.11). Para probar de verdad el job
  `frontend` o el `backend`, míralos en un contenedor limpio:
  `docker run --rm -v "D:\Parking\frontend:/app" -v /app/node_modules
  -w /app node:20 sh -c "npm ci && npm run lint && npx vue-tsc --noEmit
  && npm run build"`.
  OJO (2026-10-22, T-72): el `-v /app/node_modules` (volumen anónimo)
  **no es opcional en Windows**: sin él se monta el `node_modules` del
  host (que es de Windows) y `npm ci` falla al borrarlo con `EIO: i/o
  error, unlink '/app/node_modules/...'`. El comando sin ese volumen
  estaba documentado y **no funcionaba**.
- **Las acciones del workflow se fijan en la versión que corre en
  node24** (`checkout@v5`, `setup-python@v6`, `setup-node@v5`). Las
  versiones `@v4`/`@v5` corren en **node20**, que la plataforma ya
  desuscribió, y obligaban a usar
  `ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` (autorizar Node *inseguro*).
  Esa variable ya no está en el workflow: no la vuelvas a poner.

- **Un `datetime` que viene de la base de datos vuelve *naive* en SQLite**
  (PostgreSQL sí devuelve la zona). Compararlo con un `datetime.now(timezone.utc)`
  peta con `TypeError`, y en un test sale como un 500 raro. Hay que
  normalizar antes: `if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)`
  (el patrón ya está en `app/api/v1/cliente.py`, `app/services/cost.py`,
  `app/api/v1/password_reset.py`, `app/services/pricing.py`,
  `app/services/reports.py` y `app/services/plans.py`).
- **Un `+00:00` en una query string llega como un espacio.** Al pasar
  fechas ISO por la URL (los informes, por ejemplo), `isoformat()` da
  `2026-09-23T02:38:47.709521+00:00` y el `+` se convierte en un
  espacio: el 422 que sale ("unexpected extra characters at the end of
  the input") no dice nada del `+`. Usa el sufijo `Z` (`isoformat()
  .replace("+00:00", "Z")`).
- **Los informes tienen topes (T-100)**: ventana de 366 días como máximo
  (422) y 20.000 filas (413, sin recortar en silencio). Si añades un
  informe nuevo, que herede esos topes: el patrón es
  `MAX_FILAS_INFORME` en `app/services/reports.py` y `MAX_DIAS_VENTANA` en
  `app/api/v1/reports.py`.
- **Una entrada de parking vacía NO es un «fallo de OCR» (T-181,
  2026-10-24)**: el OCR responde `[]` (HTTP 200) a un frame sin vehículos
  (medido contra el servicio real), y eso es el caso normal. Si se cuenta
  como fallo, con el ping cada 10 min **cada cámara sana da una falsa
  alarma por hora** (medido: alarma id=401). Lo que **sí** es un fallo de
  la lectura es que el OCR **no dé una respuesta utilizable**; el mensaje
  de la alarma lo dice (blames al servicio, no a la cámara).
- **`ping_camera` se despacha cada 10 minutos por cámara (T-177,
  decisión del usuario)**: el beat encola un `solidapp.ping_camera` por
  **cámara activa** (`PING_CAMERA_INTERVAL_SECONDS`, 600 s por defecto) y
  un **lock con TTL** evita que se acumulen pings de la misma cámara. OJO:
  el **heartbeat** (`probe_heartbeats`, cada 60 s) ya cubre la liveness de
  la cámara (alerta `CAMERA_OFFLINE`); lo que aporta el ping es el **viaje
  al OCR** (despierta la alarma `OCR_FAILED`, que llevaba dormida) y una
  segunda fuente de matrículas. El TTL de esa alarma se deriva del
  intervalo real (T-167). Al añadir o cambiar una tarea de Celery hay que
  **reiniciar el worker**: `docker compose restart celery-worker`.
- **El healthcheck del beat mira su fichero de schedule** (T-186,
  2026-10-25): `find ... -mmin -10`. El sync de Celery va **detrás** de
  dormir y se duerme hasta `beat_max_loop_interval` (300 s por defecto):
  con un margen de 2 minutos el beat pasaba *unhealthy* 180 s de cada
  300 (parpadeo) y en Swarm/K8s lo reemplazarían en bucle. Ahora
  `beat_max_loop_interval = 60` ⇒ las tareas salen con ≤60 s de retraso.
  OJO: ese healthcheck mide al **escritor**, no al que **despacha**.
- **Para medir, no cuentes líneas del log de Docker** (2026-10-25): van
  **partidas** y PowerShell mete prefijos de error, así que contar
  «Sending due task» da cero y parece que el beat está mudo cuando
  está bien. `docker inspect` (estado y salud) y `stat` (mtime) sí
  mienten bien.
- **Las tareas periódicas toman un lock (T-102)**: `probe_heartbeats` se
  omite si ya hay una ronda en curso (`celery:lock:probe_heartbeats`).
  Sin ese lock, dos rondas a la vez contaban los fallos por duplicado y
  la alerta de cámara caída saltaba antes de tiempo.
- **Todos los servicios del compose tienen `restart: unless-stopped`**
  (T-101), y `tools/verificar_compose_produccion.py` lo vigila. Sin eso,
  un servicio que se cae se queda caído hasta que alguien lo levanta a
  mano (y en el worker, las tareas en curso no se reintentan).
- **El correo tiene una sola forma canónica (T-99)**: se guarda en
  minúsculas (`app/core/emails.py`) y se compara en minúsculas (login,
  reset, altas). El índice único de la migración `0015` lo prohíbe en la
  base de datos.
- **La puerta de dependencias necesita red.** `tools/verificar_dependencias.py`
  consulta **OSV** (la base que alimenta `pip-audit` y `npm audit`). Si OSV no
  responde devuelve el **código 3** ("no comprobado"), que **no** es verde: en
  el CI eso es un paso rojo, a propósito (un verde sin mirar no vale). Las
  excepciones están en `tools/dependencias_aceptadas.json` y cada una
  necesita un **motivo** y una **prueba**; una excepción sin motivo hace
  fallar la puerta.
- **El backend tiene 26 dependencias directas y el frontend 55 paquetes de
  producción**: la puerta mira esas, y **informa** del resto (el árbol
  transitivo y las dependencias de desarrollo). Mirar *todo* lo instalado
  daba 260 avisos de los que sólo 68 eran reales (el resto, paquetes del
  host ajenos al proyecto): una puerta que grita de más es una puerta que
  nadie mira.
- **`python-jose` tiene un aviso sin versión arreglada** (GHSA-3qf3-8w2g-rqmx)
  y está en la lista de excepciones: no es alcanzable porque el despliegue es
  de clave compartida (HS256), `decode_token` restringe los algoritmos y la
  configuración **rechaza** cualquier `JWT_ALGORITHM` que no sea HS256. La
  prueba son los tests de `backend/tests/test_jwt_algoritmos.py`.
- **Pillow 13 exige Python >= 3.11** (el CI y el contenedor ya lo son) y trae
  tipos más estrictos: `Image.open` devuelve `ImageFile` y `convert`
  devuelve `Image`, así que reasignar la misma variable con las dos cosas ya
  no compila con `mypy --strict`.
- **Añadir una tarea de Celery exige reiniciar el worker**: los workers no
  recargan el código, y una tarea nueva sale como *"unregistered task"*. En
  producción no pasa (la imagen se reconstruye), pero en el stack de QA:
  `docker compose restart celery-worker`.
- **Todo el compose se publica en `127.0.0.1`** (T-92): la API ya no es
  alcanzable desde la red de la sucursal. Dentro de la red de Docker se sigue
  hablando por el nombre del servicio (`backend:8000`).
- **El access log no guarda la query string** (T-91): nginx usa un
  `log_format` con `$uri` y el backend filtra el logger `uvicorn.access`. El
  frontend manda el JWT en la query string para las miniaturas y el stream
  MJPEG (un `<img>` no puede mandar cabeceras), así que **cualquier log de
  peticiones** es un sitio donde puede aparecer una credencial.
- **El CI remoto vuelve a correr** (desde el 2026-10-24, y en verde)

  Hasta entonces estaba bloqueado: la cuenta de GitHub tenía el pago
  pendiente y GitHub **rechazaba los jobs antes de asignarles un
  runner** (los 4 jobs terminaban en `failure` **sin ejecutar un solo
  paso**). Entre el 2026-07-07 y el 2026-10-24, **87 commits** de `main`
  pasaron sin esa red.

  **Cómo se desbloqueó**: el repositorio, que era **privado**, pasó a
  **público** (`gh repo edit --visibility public --accept-visibility-change-consequences`).
  Con un repositorio privado y la cuenta sin método de pago válido,
  GitHub bloquea el uso; en un repositorio público los runners estándar
  son gratuitos. Antes de hacerlo se comprobó que el historial **no tenía
  secretos** (`python tools/escanear_secretos.py --historial`).

  Lo que el CI enseñó al arrancar, y que nadie podía ver antes: **dos
  fallos latentes de las puertas** (la del compose importaba `Settings`
  sin tener `pydantic`; y la de pruebas inversas ejecuta `pytest` y se
  lanzaba **antes** del `pip install`). Los dos corregidos (T-147).

  Para ver el estado: `python tools/estado_ci.py`. La réplica local
  (`tools/ejecutar_ci_local.py --all`) replica el workflow en local.

`estado_ci.py` devuelve un código por estado, y **ninguno de ellos es
"verde" por defecto**:

| Código | Estado |
|---|---|
| 0 | en verde |
| 1 | rojo de verdad (un job ejecutó pasos y falló): es el código |
| 2 | rechazado por la cuenta (jobs en `failure` **sin** un solo paso) |
| 3 | el run sigue en curso: no se puede afirmar nada |
| 4 | al run le falta algún job del workflow: el criterio exige todos |

Mira **siempre** la rama `main` (es lo que pide el criterio del plan);
la herramienta tiene `--rama` para mirar otra.
