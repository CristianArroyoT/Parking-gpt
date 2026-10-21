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

99 endpoints en 25 grupos. La columna «Quién» es la autorización efectiva **hoy**, extraída del código (no de la intención) con `tools/extraer_api.py`.

### 3.1 Administración — auditoría — `admin` (`admin.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/admin/audit-logs` | `require_role('admin')` |

### 3.2 Alertas — `alerts` (`alerts.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/alerts` | `parking_context` |
| POST | `/parkings/{parking_id}/alerts/{alert_id}/acknowledge` | Autenticado |

### 3.3 Autenticación — `auth` (`auth.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/auth/login` | Público |
| POST | `/auth/login/oauth` | Público |
| POST | `/auth/refresh` | Público |
| POST | `/auth/logout` | Autenticado (middleware de auditoría) |

### 3.4 Cámaras, geocercas y salud — `cameras` (`cameras.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/cameras` | `parking_context` |
| POST | `/parkings/{parking_id}/cameras` | `parking_context` |
| PATCH | `/parkings/{parking_id}/cameras/{camera_id}` | `parking_context` |
| GET | `/parkings/{parking_id}/cameras/{camera_id}/geofences` | `parking_context` |
| POST | `/parkings/{parking_id}/cameras/{camera_id}/geofences` | `parking_context` |
| PATCH | `/parkings/{parking_id}/cameras/{camera_id}/geofences/{fence_id}` | `parking_context` |
| DELETE | `/parkings/{parking_id}/cameras/{camera_id}/geofences/{fence_id}` | `parking_context` |
| GET | `/parkings/{parking_id}/cameras/{camera_id}/health` | `parking_context` |
| POST | `/parkings/{parking_id}/cameras/{camera_id}/detect-vehicles` | `parking_context` |

### 3.5 Preview en vivo (MJPEG) — `cameras_live` (`cameras_live.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/cameras/{camera_id}/live` | `get_current_user_or_query_token` + `enforce_parking_membership` |

### 3.6 Cliente final (PWA) — `cliente` (`cliente.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/cliente/plazas` | Autenticado |
| GET | `/cliente/tickets` | Autenticado |

### 3.7 Costes operativos — `costs` (`costs.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/admin/costs` | `require_role('admin')` |
| POST | `/admin/costs` | `require_role('admin')` |
| GET | `/admin/costs/{cost_id}` | `require_role('admin')` |
| PATCH | `/admin/costs/{cost_id}` | `require_role('admin')` |
| DELETE | `/admin/costs/{cost_id}` | `require_role('admin')` |

### 3.8 KPIs de dirección — `dashboard` (`dashboard.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/admin/dashboard/kpis` | `require_role('admin')` |

### 3.9 Eventos (SSE) — `events` (`events.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/events` | `get_current_user_or_query_token` + `enforce_parking_membership` |

### 3.10 Plantillas faciales (fuera del MVP) — `face_templates` (`face_templates.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/face-templates` | `_exigir_feature_flag` + Autenticado + `enforce_parking_membership` |
| DELETE | `/face-templates/{template_id}` | `_exigir_feature_flag` + Autenticado |

### 3.11 Operadores de la sucursal — `gestor_operadores` (`gestor_operadores.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/operadores` | Autenticado + `enforce_parking_membership` |
| POST | `/parkings/{parking_id}/operadores` | Autenticado + `enforce_parking_membership` |

### 3.12 Incidentes y adjuntos — `incidents` (`incidents.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/incidents/parkings/{parking_id}` | `require_role('admin')` + Autenticado + `parking_context` |
| DELETE | `/incidents/attachments/{attachment_id}` | `require_role('admin')` + Autenticado |
| GET | `/incidents/attachments/{attachment_id}/download` | `_gestor_o_admin` |
| GET | `/incidents/attachments/{attachment_id}/thumbnail` | `_gestor_o_admin` |
| GET | `/incidents/attachments/{attachment_id}` | `_gestor_o_admin` |
| POST | `/incidents/{alert_id}/attachments` | `require_role('admin')` + Autenticado + `enforce_parking_membership` |
| GET | `/incidents/{alert_id}/attachments` | `require_role('admin')` + Autenticado + `enforce_parking_membership` |

### 3.13 Cierre de sesión global — `logout_all` (`logout_all.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/auth/logout/all` | Autenticado (middleware de auditoría) |

### 3.14 Sucursales — `parkings` (`parkings.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings` | Autenticado |
| POST | `/parkings` | `require_role('admin')` |
| GET | `/parkings/{parking_id}` | `parking_context` |
| PATCH | `/parkings/{parking_id}` | `parking_context` |
| DELETE | `/parkings/{parking_id}` | `require_role('admin')` |

### 3.15 Recuperación de contraseña — `password_reset` (`password_reset.py`)

| Método | Ruta | Quién |
|---|---|---|
| POST | `/auth/forgot-password` | Público |
| POST | `/auth/reset-password` | Público |

### 3.16 Planes y suscripciones — `plans` (`plans.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/plans` | Público |
| POST | `/plans` | Público |
| GET | `/plans/me` | Público |
| GET | `/plans/subscriptions` | Público |
| POST | `/plans/subscriptions` | Público |
| DELETE | `/plans/subscriptions/{subscription_id}` | Público |
| GET | `/plans/{plan_id}` | Público |
| PATCH | `/plans/{plan_id}` | Público |
| DELETE | `/plans/{plan_id}` | Público |

### 3.17 Placas (OCR) — `plates` (`plates.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/plates-detected` | `parking_context` |
| POST | `/parkings/{parking_id}/cameras/{camera_id}/plates` | `parking_context` |

### 3.18 Informes — `reports` (`reports.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/admin/reports/margins` | Autenticado |
| GET | `/admin/reports/margins.csv` | Autenticado |
| GET | `/admin/reports/ingresos.csv` | Autenticado |
| GET | `/admin/reports/ingresos.pdf` | Autenticado |
| GET | `/admin/reports/ocupacion.csv` | Autenticado |
| GET | `/admin/reports/ocupacion.pdf` | Autenticado |
| GET | `/admin/reports/tickets.csv` | Autenticado |
| GET | `/admin/reports/tickets.pdf` | Autenticado |
| GET | `/admin/reports/alertas.csv` | Autenticado |
| GET | `/admin/reports/alertas.pdf` | Autenticado |
| GET | `/admin/reports/margins.pdf` | Autenticado |

### 3.19 Plazas — `spaces` (`spaces.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/spaces` | `parking_context` |
| POST | `/parkings/{parking_id}/spaces` | `parking_context` |
| PATCH | `/parkings/{parking_id}/spaces/{space_id}` | `parking_context` |

### 3.20 Tarifas — `tariffs` (`tariffs.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/tariffs` | Autenticado |
| POST | `/parkings/{parking_id}/tariffs` | `parking_context` |
| PATCH | `/parkings/{parking_id}/tariffs/{tariff_id}` | `parking_context` |
| DELETE | `/parkings/{parking_id}/tariffs/{tariff_id}` | `require_role('admin')` |

### 3.21 Resumen de tickets — `ticket_summary` (`ticket_summary.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/parkings/{parking_id}/tickets/summary` | `parking_context` + Autenticado |

### 3.22 Tickets — `tickets` (`tickets.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/tickets` | Autenticado |
| POST | `/tickets` | Autenticado |
| POST | `/tickets/manual` | `require_role('admin')` + Autenticado + `parking_context` |
| GET | `/tickets/{ticket_id}` | Autenticado |
| POST | `/tickets/{ticket_id}/close` | Autenticado |

### 3.23 Usuarios y membresías — `users` (`users.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/users/me` | Autenticado |
| PATCH | `/users/me/password` | Autenticado |
| PATCH | `/users/me/profile` | Autenticado |
| GET | `/users/me/vehicles` | Autenticado |
| POST | `/users/me/vehicles` | Autenticado |
| PATCH | `/users/me/vehicles/{vehicle_id}` | Autenticado |
| POST | `/users/me/vehicles/{vehicle_id}/links` | Autenticado |
| DELETE | `/users/me/vehicles/{vehicle_id}/links/{user_id}` | Autenticado |
| GET | `/users/me/tickets` | Autenticado |
| GET | `/users` | `require_role('admin')` |
| POST | `/users` | `require_role('admin')` |
| GET | `/users/{user_id}` | `require_role('admin')` |
| PATCH | `/users/{user_id}` | `require_role('admin')` |
| DELETE | `/users/{user_id}` | `require_role('admin')` |
| POST | `/users/{user_id}/memberships` | `require_role('admin')` |

### 3.24 Vehículos — `vehicles` (`vehicles.py`)

| Método | Ruta | Quién |
|---|---|---|
| GET | `/vehicles` | `require_role('admin', 'gestor', 'operador')` |
| POST | `/vehicles` | `require_role('admin', 'gestor', 'operador')` |
| PATCH | `/vehicles/{vehicle_id}` | `require_role('admin', 'gestor', 'operador')` |
| POST | `/vehicles/{vehicle_id}/users` | `require_role('admin', 'gestor', 'operador')` |

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

El inventario sale del código, no de la memoria. La sección 3 se
**genera**:

```bash
# Ver las rutas y su RBAC (sale de los routers y del OpenAPI real)
python tools/extraer_api.py

# Regenerar la sección 3 de este documento
python tools/generar_seccion_api.py --escribir
```

`tools/extraer_api.py` lee los routers con `ast` (no con el
introspection de FastAPI, que cambia entre versiones) y **comprueba
contra el OpenAPI real** que no se le escape ninguna ruta: si el
extractor y la aplicación no coinciden, el script sale con código 1.

La columna «Quién» sale de las dependencias que declara cada endpoint,
incluidos los dos patrones que no son un `Depends` en la firma:

- La **llamada manual** a la dependencia dentro del cuerpo (el patrón
  «opt-in por endpoint» del preview y del SSE).
- La lectura de `request.state.audit`, que el `AuditMiddleware` rellena
  **después** de validar el token Bearer (lo usan `logout` y
  `logout/all`).

Si el listado no coincide con la sección 3, el documento está
desfasado: **se actualiza el documento, no al revés**.
