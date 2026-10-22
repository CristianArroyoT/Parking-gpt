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
**`docs/CODEMAPS/2026-10-21-cierre-del-plan.md`**.

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

Ojo con un caso especial que ya costó un bug real: **dos comprobaciones
que comparten la fuente de verdad no se vigilan entre sí**. Si la puerta
A compara el documento contra el extractor B, y ambos salen del mismo
código, los dos pueden mentir a la vez y la puerta da el visto bueno.
Hace falta una **tercera** fuente: el caso de mentira escrito a mano.

## Comandos que funcionan (verificados)

```bash
# La salud del repo en un comando: 23 comprobaciones (~2 min)
python tools/verificar_repo.py
python tools/verificar_repo.py --completo      # + CI local y QA en 5 anchos (~40 min)

# Las 22 autopruebas de las puertas
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
python tools/verificar_compose_produccion.py --autoprueba
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

## Trampas de este entorno (Windows + Docker Desktop)

- `localhost` en Windows resuelve primero a IPv6 (`::1`) y `psycopg`
  tarda 8,4 s. Usa `127.0.0.1` (el CI local lo convierte solo).
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
- **Dos suites del host sí pueden ir en paralelo** (SQLite y PostgreSQL a
  la vez): la base de Redis de cada una se **toma con un lock** (`SET NX`).
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
- **`POST /auth/login` tiene rate-limit: 10 intentos por IP cada 5
  minutos**, y cuenta también los exitosos. La QA visual inicia sesión
  una vez por rol, así que **no la lances 5 veces seguidas** (15 inicios →
  429): usa `python frontend/scripts/qa_visual.py --anchos
  "414,768,1024,1232,1440"`, que recorre los 5 anchos con 3 inicios.
- La suite da **604 passed, 9 skipped** en SQLite y **613 passed** en PostgreSQL
  en el host (lo que ve el CI), y **603 passed, 10 skipped** / **612 passed, 1 skipped** en el
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

## El bloqueo conocido

El **CI remoto no puede correr**: la cuenta de GitHub tiene el pago
pendiente y GitHub rechaza los jobs antes de asignarles un runner. El
último run que llegó a ejecutar un paso fue el del **2026-07-07**; desde
entonces ningún run ha arrancado un job, y **87 commits** de `main`
pasaron sin esa red.

Esto es lo **único** que queda del plan (el último criterio depende del
CI) y **sólo lo puede resolver quien tiene la cuenta**: arreglando la
facturación (*Billing & plans*) o abriendo el repositorio a público.

Mientras tanto, la réplica local (`tools/ejecutar_ci_local.py --all`) **es**
el CI completo de facto, y `tools/verificar_repo.py` da el veredicto.
Para ver el estado del CI remoto: `python tools/estado_ci.py`.

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
