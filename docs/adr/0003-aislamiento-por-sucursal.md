# ADR-0003 · El aislamiento entre sucursales lo decide el rol global

- **Estado**: Aceptada
- **Fecha**: 2026-10-23
- **Ítem del plan**: T-113…T-116 (los cuatro bugs que obligaron a escribirla) y T-118 (la puerta que la vigila)
- **Contexto**: [`2026-10-21-plan-pendientes-solidapp-design.md`](../../superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md)

---

## Contexto

El modelo de datos **no tiene `client_id`**: no hay multi-tenancy de
empresas. El aislamiento entre sucursales se hace con dos cosas:

| Pieza | Qué dice | Dónde vive |
|---|---|---|
| `parking_memberships` | «este usuario pertenece a esta sucursal» | tabla |
| `User.role` | «este usuario es admin / gestor / operador / cliente» | columna (rol **global**) |

Y hay una tercera columna, `parking_memberships.role_in_parking`, que
debería decir «de qué rol es **en esta** sucursal»… y que **no se leía en
ningún sitio** (se escribía y no se leía: un ajuste que parece
configurable y no lo es).

El reparto de responsabilidades estaba escrito en el código pero no en
ningún documento, y el código lo aplicaba **a mano, endpoint a
endpoint**. Cuatro endpoints se lo saltaron, todos medidos contra el
sistema en marcha (no leyendo código):

| # | Endpoint | Qué pasaba | Medición |
|---|---|---|---|
| T-113 | `POST /tickets` | aceptaba el `parking_id` del cuerpo sin mirar la membresía | un gestor de la 11 creó el ticket 617 en la 12 (**201**) y no lo podía ni ver (404) |
| T-114 | `enforce_parking_membership` | miraba la membresía pero **no el rol** | un cliente con una membresía creó plazas, creó cámaras y **fijó el precio** de la sucursal (los tres, **201**) |
| T-115 | `GET`/`PATCH` de geocercas | no cruzaban la cámara con la sucursal del path | un gestor de la 11 leyó (**200**) y **modificó** la geocerca de la 12 (la movió a una esquina: el OCR de la 12 dejó de detectar entradas) |
| T-116 | `GET /vehicles` | la flota entera a cualquier gestor | el gestor de la 11 recibió las 6 matrículas del sistema, 3 de las cuales no aparecen en sus propios movimientos |

Dos de esos cuatro eran **escaladas de privilegios**: un conductor
(cliente) que gestionaba la sucursal, y un gestor que escribía en la
contabilidad de otra.

## Decisión

**El alcance sobre una sucursal lo decide el ROL GLOBAL del usuario. La
membresía sólo dice «pertenece a esta sucursal»; no concede ningún
poder por sí misma.**

En concreto:

1. `enforce_parking_membership` (el único helper de pertenencia) exige
   **dos** cosas: que el usuario sea de personal (`ROLES_STAFF`:
   admin, gestor, operador) **y** que tenga membresía en esa sucursal. El
   admin global pasa siempre. Un rol que no es de personal recibe 403
   **aunque tenga la membresía**.
2. Los roles de personal tienen **una sola definición**
   (`ROLES_STAFF` en `app/core/deps.py`). Antes la tupla estaba
   duplicada en `vehicles.py` y se podía desincronizar.
3. Un endpoint que acepta un `parking_id` **en el cuerpo** valida la
   membresía (`parking_context(payload.parking_id, ...)`).
4. Un endpoint que carga un recurso por id lo **cruza** con el
   `parking_id` del path (que el recurso sea de esa sucursal). El helper
   único es `_camara_de_sucursal`.
5. Los **listados globales** (la flota de vehículos) son de admin; el
   personal usa un endpoint **acotado por sucursal**
   (`GET /parkings/{id}/vehicles`).

`role_in_parking` **deja de ser la fuente de verdad** y por eso se
documenta aquí su estado: se sigue escribiendo (el admin puede elegirlo
al dar de alta una membresía) pero **no autoriza nada**.

## Alternativas

### A. RBAC por sucursal (`role_in_parking` manda) — **NO, todavía**

- **A favor**: un mismo usuario puede ser gestor de la sucursal A y
  operador de la B. Es el modelo que la columna ya insinúa.
- **En contra**: obliga a que **cada** comprobación de permisos mire
  dos cosas (rol global + rol en la sucursal), y el fallo silencioso es
  exactamente el que se acaba de arreglar: si un endpoint olvida mirar
  `role_in_parking`, concede **más** de lo que debería, sin que nada se
  entere. Con el rol global, un endpoint que olvida la comprobación
  concede **menos** (el cliente no entra) — el fallo por defecto es el
  seguro.
- **Por qué no ahora**: es una decisión de producto (¿un operador de
  empresa con varias sucursales necesita roles distintos por sucursal?),
  y no hace falta para lo que el producto hace hoy.

### B. `client_id` (multi-tenancy de empresas)

- **A favor**: el modelo real de un SaaS con empresas clientes.
- **En contra**: el producto de hoy es un **operador** con varias
  sucursales; añadir `client_id` toca todos los modelos, todas las
  consultas y todas las migraciones, para un requisito que aún no
  existe. Si llega, la decisión de este ADR se mantiene: `client_id`
  sería **una** capa más de acotado, por encima del rol global.

### C. Dejar el alcance en la membresía (lo que había)

Descartada: es la causa de T-114. Una fila en `parking_memberships` no
puede convertir a un conductor en gestor.

## Consecuencias

**A favor**

- El fallo por defecto es el seguro: un endpoint que olvida la
  comprobación concede menos, no más.
- Una sola definición de «quién es personal» (`ROLES_STAFF`).
- El aislamiento es comprobable: `tools/verificar_aislamiento_sucursal.py`
  verifica estáticamente las tres reglas (body con `parking_id`,
  router con `{parking_id}`, recurso con sucursal) y tiene autoprueba
  con casos de mentira escritos a mano.

**En contra**

- Un usuario con rol global `gestor` **no** puede estar en una sucursal
  como simple operador: hay que darle un rol global menor. Es una
  limitación conocida, no un descuido.
- `role_in_parking` es un campo que no autoriza nada: mientras no se
  implemente el RBAC por sucursal, es ruido. Se deja escrito (y
  documentado aquí) para no perder la información de a qué rol quería
  pertenecer el usuario en cada sucursal.

## Qué queda pendiente

- **Decisión de producto**: ¿hace falta el RBAC por sucursal (alternativa
  A)? Si la respuesta es sí, es un cambio de contrato en todas las
  comprobaciones, y hay que hacerlo con su propia puerta.
- **`role_in_parking`**: mientras no autorice nada, decidir si se sigue
  escribiendo o se retira (con su migración).
