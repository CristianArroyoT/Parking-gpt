# API interna de solidAPP

> **Estado**: documentada y versionada, **no expuesta públicamente**.
> Este documento es el inventario de la API que la aplicación usa hoy, con su
> RBAC, para que cuando se decida abrirla a terceros (movilidad, autoridades)
> no haya que reconstruir el mapa desde cero.

- **Ítem del plan**: T-25 (Bloque 3)
- **Prefijo**: `/api/v1` (ya presente desde el inicio)
- **OpenAPI**: `/openapi.json` y `/docs` (Swagger UI) en modo desarrollo

---

## 1. Modelo de autenticación

| Mecanismo | Dónde se usa | Notas |
|---|---|---|
| `Authorization: Bearer <jwt>` | **Todos** los endpoints salvo `login`/`oauth`/`health` | Único mecanismo para la API REST |
| `?token=<jwt>` | **Sólo** dos endpoints: `/cameras/{id}/live` y `/events` | El navegador no puede mandar headers en un `<img>` ni en un `EventSource`. La ampliación es **opt-in por endpoint**, nunca global (decisión tomada en la revisión de seguridad del 2026-07-07) |
| Cookie de sesión | **No** | No se usa |

El JWT lleva `jti`. El `logout` lo mete en una **blacklist** en Redis, de modo
que un token reutilizado tras el cierre devuelve **401**. `POST /auth/logout/all`
invalida todos los tokens activos del usuario.

## 2. Roles

| Rol | Alcance |
|---|---|
| `admin` | Global. Ve todas las sucursales, usuarios, costes y auditoría |
| `gestor` | Una o varias sucursales concretas, por **membresía** (`ParkingMembership`) |
| `operador` | Una sucursal, por membresía |
| `cliente` | Sus propios vehículos y tickets |

Dependencias de autorización (en `backend/app/core/deps.py`):

| Dep | Qué exige | 403 cuando |
|---|---|---|
| `get_current_user` | Token válido y usuario activo | Token inválido/expirado → **401** |
| `require_role(*roles)` | El rol del usuario está en la lista | Rol insuficiente → **403** |
| `parking_context` | Membresía en la sucursal del path (el `admin` pasa siempre) | Sin membresía → **403** |

## 3. Mapa de recursos y RBAC

61 endpoints en 18 grupos. La columna «Quién» es la autorización efectiva
**hoy**, extraída del código (no de la intención).

### 3.1 Autenticación — `auth`

| Método | Ruta | Quién |
|---|---|---|
| POST | `/auth/login` | Público (rate-limit por IP y por email) |
| POST | `/auth/login/oauth` | Público |
| POST | `/auth/refresh` | Público (refresh token) |
| POST | `/auth/logout` | Autenticado (blacklistea el `jti`) |
| POST | `/auth/logout/all` | Autenticado (invalida todos los tokens) |

### 3.2 Sucursales — `sucursales` (`parkings.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings` | Autenticado (las de su ámbito) |
| POST | `/parkings` | `admin` |
| GET | `/parkings/{id}` | `parking_context` |
| PATCH | `/parkings/{id}` | `parking_context` |
| DELETE | `/parkings/{id}` | `admin` |

### 3.3 Plazas — `plazas` (`spaces.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET, POST | `/parkings/{id}/spaces` | `parking_context` |
| PATCH | `/parkings/{id}/spaces/{space_id}` | `parking_context` |

### 3.4 Tarifas — `tarifas` (`tariffs.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{id}/tariffs` | Autenticado |
| POST | `/parkings/{id}/tariffs` | `parking_context` |
| PATCH | `/parkings/{id}/tariffs/{tariff_id}` | `parking_context` |
| DELETE | `/parkings/{id}/tariffs/{tariff_id}` | `admin` |

### 3.5 Cámaras, geocercas y salud — `cámaras` (`cameras.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET, POST | `/parkings/{id}/cameras` | `parking_context` |
| PATCH | `/parkings/{id}/cameras/{camera_id}` | `parking_context` |
| GET, POST | `/parkings/{id}/cameras/{camera_id}/geofences` | `parking_context` |
| PATCH, DELETE | `…/geofences/{fence_id}` | `parking_context` |
| GET | `…/cameras/{camera_id}/health` | `parking_context` |
| POST | `…/cameras/{camera_id}/detect-vehicles` | `parking_context` |

### 3.6 Preview en vivo — `cámaras-live` (`cameras_live.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{id}/cameras/{camera_id}/live` | `get_current_user_or_query_token` + `enforce_parking_membership` |

Devuelve `multipart/x-mixed-replace`. **409** si ya hay un stream vivo para esa
cámara. Es el único endpoint que acepta `?token=`.

### 3.7 Placas (OCR) — `placas` (`plates.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/parkings/{id}/cameras/{camera_id}/plates` | `parking_context` |
| GET | `/parkings/{id}/plates-detected` | `parking_context` |

### 3.8 Tickets — `tickets` (`tickets.py`, `ticket_summary.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/tickets` | Autenticado (filtrado por rol en el servicio) |
| POST | `/tickets` | Autenticado |
| POST | `/tickets/manual` | `require_role(...)` de personal |
| GET | `/tickets/{ticket_id}` | Autenticado + dueño/ámbito |
| POST | `/tickets/{ticket_id}/close` | Autenticado + dueño/ámbito |
| GET | `/parkings/{id}/tickets/summary` | `parking_context` |

### 3.9 Incidentes — `incidentes` (`incidents.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/incidents/parkings/{parking_id}` | `require_role(...)` de personal |

### 3.10 Alertas — `alertas` (`alerts.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{id}/alerts` | `parking_context` |
| POST | `/parkings/{id}/alerts/{alert_id}/acknowledge` | `parking_context` |

### 3.11 Eventos (SSE) — `events` (`events.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{id}/events` | `get_current_user_or_query_token` + `parking_context` |

Server-Sent Events. Acepta `?token=` (mismo motivo que el preview).

### 3.12 Usuarios — `usuarios` (`users.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/users/me` | Autenticado |
| PATCH | `/users/me/password` | Autenticado |
| GET, POST | `/users` | `admin` |
| GET, PATCH, DELETE | `/users/{user_id}` | `admin` |
| POST | `/users/{user_id}/memberships` | `admin` |

### 3.13 Vehículos — `vehículos` (`vehicles.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET, POST | `/vehicles` | Personal (`admin`/`gestor`/`operador`) |
| PATCH | `/vehicles/{vehicle_id}` | Personal |
| POST | `/vehicles/{vehicle_id}/users` | Personal |

### 3.14 Administración — `admin*`

| Método | Ruta | Quién |
|---|---|---|
| GET | `/admin/audit-logs` | `admin` |
| GET | `/admin/dashboard/kpis` | `admin` |
| GET, POST | `/admin/costs` · PATCH, DELETE `/admin/costs/{id}` | `admin` |
| GET | `/admin/reports/margins` · `/admin/reports/margins.csv` | `get_current_user` + filtro por rol |

### 3.15 Salud — `meta`

| Método | Ruta | Quién |
|---|---|---|
| GET | `/health` | Público |

## 4. Versionado y política de deprecación

- **Prefijo fijo `/api/v1`**. El versionado es por ruta, no por cabecera.
- **Regla de compatibility dentro de `v1`**: se puede
  - añadir un endpoint,
  - añadir un campo **opcional** a una respuesta,
  - añadir un parámetro opcional.
- **Rompe `v1` (y obliga a `v2`)**: quitar un endpoint, renombrar un campo,
  cambiar el tipo de un campo, cambiar el código de error o el significado de
  un parámetro.
- **Deprecación**: cuando un endpoint vaya a desaparecer,
  1. se marca `deprecated: true` en el OpenAPI,
  2. la respuesta incluye `Deprecation: true` y `Sunset: <fecha HTTP>`,
  3. se avisa en el changelog **con un mínimo de 90 días** antes de quitarlo.
- Los cambios de contrato (API, modelos, rutas) se documentan en el mensaje
  del commit y en `docs/CODEMAPS/`.

## 5. Qué falta para exponerla públicamente

Hoy **no** se expone: la memoria del proyecto lo fija así para el MVP («en
MVP no se expone API pública; se deja documentada la estructura interna»).
Antes de abrirla habría que cerrar, como mínimo:

1. **Modelo de datos firmado**: qué entidades se exponen y con qué campos.
   Hoy hay datos personales (usuarios, vehículos, matrículas, fotos de
   incidencias) → LOPDGDD.
2. **Términos y condiciones** y responsable del tratamiento.
3. **Límite de tasa** por consumidor (hoy el rate-limit es por IP/email de
   usuario interno, no por `client_id`).
4. **Autenticación de terceros**: hoy es un JWT de sesión de la app. Haría
   falta OAuth2 client credentials con scopes por recurso.
5. **Versionado del contrato** y política de deprecación aplicada de verdad
   (headers `Deprecation`/`Sunset`).
6. **Auditoría de acceso**: registrar quién de fuera ha llamado a qué.

Mientras no se cumplan, la API es **interna**: no se documenta fuera del
equipo y no se soporta como contrato público.

## 6. Comprobación de que este documento está al día

El inventario sale del OpenAPI real, no de la memoria. Para regenerarlo:

```bash
docker exec parking-backend-1 python -c "
import json, urllib.request
spec = json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))
for path, ops in sorted(spec['paths'].items()):
    for method in ops:
        print(method.upper(), path)
"
```

Si ese listado no coincide con la sección 3, el documento está desfasado:
se actualiza el documento, no al revés.
