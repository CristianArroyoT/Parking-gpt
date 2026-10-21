# solidAPP — gestión de parkings en España

Sistema de gestión de parkings con OCR de matrículas, mapa visual de plazas y
control por cámara IP. Producto orientado a **España** (idioma `es-ES`,
LOPDGDD/GDPR).

> **Estado**: MVP Fase 1 (Cimientos). OCR, geocercas activas, alertas,
> reportes y PDF llegan en Fases 2/3/4. Ver `docs/maquetas/` para los
> wireframes aprobados.

## Stack

| Capa          | Tecnología                                                    |
| ------------- | ------------------------------------------------------------- |
| Backend       | FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2              |
| Frontend      | Vue 3 + Vite + Pinia + Vue Router + Tailwind + Axios          |
| Base de datos | PostgreSQL 15 + PostGIS                                       |
| Cola y cache  | Redis 7 + Celery                                              |
| OCR           | PaddleOCR (configurable a Tesseract)                          |
| Cámaras       | Pull RTSP genérico (ONVIF cuando se decida el fabricante)     |
| Despliegue    | Docker Compose local; producción Docker Swarm (futuro)        |

Más detalle en `~/.claude/projects/D--Parking/memory/`.

## Requisitos

- Docker Desktop con compose v2.
- Puertos libres: 5173 (frontend), 8000 (backend), 5432 (Postgres), 6379 (Redis).

> **No instales nada en el host Windows.** Todo se ejecuta dentro de los
> contenedores. Ni `pip install`, ni `npm install`.

## Arranque

```bash
# 1) Variables de entorno (opcional, sólo para cambiar el secreto del JWT)
cp .env.example .env

# 2) Levantar la pila
docker compose up -d --build

# 3) Aplicar migraciones y cargar datos demo
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed

# 4) Abrir
#    http://localhost:5173   → frontend
#    http://localhost:8000   → Swagger UI (OpenAPI)
```

## Cuentas demo (Fase 1)

| Rol       | Email                          | Contraseña    |
| --------- | ------------------------------ | ------------- |
| Admin     | `admin@solidapp.es`            | `admin12345`  |
| Gestor    | `gestor.madrid@solidapp.es`    | `gestor1234`  |
| Operador  | `operador.madrid@solidapp.es`  | `oper12345`   |
| Cliente   | `cliente.demo@solidapp.es`     | `cliente1234` |

> Estas contraseñas son del seed para desarrollo. **No las uses en
> producción.**

## Estructura del repo

```
D:\Parking\
├── backend/                 # FastAPI + SQLAlchemy 2.0
│   ├── app/
│   │   ├── api/v1/          # routers REST
│   │   ├── core/            # config, db, security, deps
│   │   ├── models/          # 13 modelos SQLAlchemy
│   │   ├── schemas/         # Pydantic v2
│   │   ├── services/        # audit log
│   │   ├── workers/         # instancia Celery
│   │   └── scripts/seed.py  # datos demo
│   ├── alembic/             # migraciones iniciales
│   ├── tests/               # pytest (smoke)
│   └── Dockerfile
├── frontend/                # Vue 3 + Vite
│   ├── public/              # logo + favicon
│   ├── src/
│   │   ├── api/             # cliente HTTP + refresh
│   │   ├── stores/          # Pinia (auth, ui)
│   │   ├── router/          # guard por rol
│   │   ├── layouts/         # AppLayout
│   │   └── views/           # login + admin + gestor + operador + cliente
│   └── Dockerfile
├── infra/
│   └── seed.sql             # habilita PostGIS en el contenedor db
├── docs/maquetas/           # wireframes HTML aprobados
├── docker-compose.yml       # 6 servicios MVP
├── docker/celery/Dockerfile # imagen Celery
└── .github/workflows/ci.yml # CI (backend + frontend)
```

## Endpoints relevantes (Fase 1)

| Método | Ruta                                | Rol          |
| ------ | ----------------------------------- | ------------ |
| POST   | `/api/v1/auth/login`                | público      |
| POST   | `/api/v1/auth/forgot-password`      | público      |
| POST   | `/api/v1/auth/reset-password`       | público      |
| POST   | `/api/v1/auth/refresh`              | auth         |
| POST   | `/api/v1/auth/logout`               | auth         |
| GET    | `/api/v1/users`                     | admin        |
| POST   | `/api/v1/users`                     | admin        |
| PATCH  | `/api/v1/users/{id}`                | admin        |
| GET    | `/api/v1/parkings`                  | admin/gestor |
| POST   | `/api/v1/parkings`                  | admin        |
| GET    | `/api/v1/parkings/{id}/spaces`      | gestor       |
| GET    | `/api/v1/parkings/{id}/cameras`     | gestor       |
| GET    | `/api/v1/cameras/{id}/geofences`    | gestor       |
| GET    | `/api/v1/tickets?only_active=…`     | todos        |
| POST   | `/api/v1/tickets`                   | staff        |
| GET    | `/health`                           | público      |

Documentación interactiva en `http://localhost:8000/docs`.

## Fuera del MVP

- **Reconocimiento facial: fuera del MVP.** Se deja únicamente la
  *estructura* preparada —la tabla `face_templates` y los endpoints
  `POST /api/v1/face-templates` y `DELETE /api/v1/face-templates/{id}`—
  pero **no se usa para autenticar a nadie**: el login sigue siendo
  exclusivamente usuario + contraseña y ninguna ruta de autenticación lee
  esa tabla. Los endpoints están **deshabilitados por feature flag**
  (`FACE_TEMPLATES_ENABLED`, valor por defecto `false`); con el flag
  apagado responden **404 Not Found**. No hay captura, ni extracción de
  vectores, ni comparación biométrica implementados. Cuando se active,
  habrá que revisar su base legal y su retención (LOPDGDD/GDPR).
- **Recuperación de contraseña por correo**: el enlace de restablecimiento
  apunta a `/recuperar-contrasena` del frontend, una pantalla que todavía
  no existe. Hasta que se implemente, el token se puede usar llamando
  directamente a `POST /api/v1/auth/reset-password`.

## Pruebas

```bash
docker compose exec backend pytest
docker compose exec backend ruff check app
docker compose exec backend mypy app
docker compose exec frontend npm run type-check
```

## Roadmap

- **Fase 2** — Worker OCR (PaddleOCR), pull RTSP, calibración de geocercas,
  alta/baja automática, alertas por correo.
- **Fase 3** — Auditoría completa, tabla de costos, reportes PDF/CSV,
  dashboards.
- **Fase 4** — Docker Swarm + alta disponibilidad, backups automáticos
  (pg_dump + WAL cada 5 min), pruebas de carga.

## Licencia y datos

- Datos personales: cumplen LOPDGDD (ES) y GDPR (UE).
- Retención: 1 año para tickets, alertas y audit logs.
- Las imágenes de OCR fallido se borran a los 30 días.