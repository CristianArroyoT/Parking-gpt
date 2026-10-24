# ADR 0005 — El RBAC por sucursal: el rol global es el techo, el rol de la sucursal es el poder

- **Estado**: **aceptado** (decisión del usuario el 2026-10-24)
- **Fecha**: 2026-10-24
- **Sustituye/completa**: [ADR 0003 — Aislamiento por sucursal](0003-aislamiento-por-sucursal.md)
- **Decide sobre**: la columna `parking_memberships.role_in_parking`, que desde el
  principio se escribió y no se leía.

## El problema

Hoy el alcance lo decide **el rol global** del usuario y la membresía sólo dice
**en qué sucursales** está (`docs/adr/0003-aislamiento-por-sucursal.md`).

Medido el 2026-10-24: un **gestor** que es miembro de Madrid Centro A y de
Barcelona Eixample es **gestor con los mismos permisos en las dos**. No hay
forma de que en una sucursal sea gestor y en otra operador, ni de que en una sea
un simple conductor. Con un operador de parking con varias sucursales y personal
propio, eso se queda corto.

La columna `role_in_parking` («de qué rol es **en esta** sucursal») existe en el
modelo desde el principio, se escribe al crear la membresía (y el seed la rellena
con el mismo rol global), pero **ningún código la leía** para autorizar.

## La decisión

> **El rol global es el TECHO; el rol de la sucursal es el PODER real.**

La jerarquía es `admin > gestor > operador > cliente`.

1. Un usuario con rol global `admin` conserva poder **global** (como hoy).
2. Para el resto, el **rol efectivo** en la sucursal `X` es el **más
   restrictivo** entre su rol global y `parking_memberships.role_in_parking`
   (la membresía de esa sucursal).
3. Si el rol efectivo **no es de personal** (`admin`, `gestor`, `operador`), la
   sucursal le queda **vedada** (403), aunque tenga la membresía.
4. `role_in_parking` **nunca** da más poder del que ya tiene el rol global: un
   `cliente` global con `role_in_parking = gestor` sigue siendo **cliente** en
   esa sucursal. Esto **mantiene** la defensa del T-114 (la membresía no
   convierte a un conductor en gestor).
5. Los endpoints que exigen un rol concreto («sólo gestor») deben mirar el rol
   **efectivo de esa sucursal**, no el global: un gestor global que en la
   sucursal B es `operador` **no** puede fijar tarifas en B, aunque sí en A.

### Consecuencia del techo: el poder se baja, no sube

Con las reglas 2 y 4, el rol de la sucursal **recorta** el global pero no lo
amplía:

- Un `gestor` global puede ser **operador** (o cliente) en una sucursal: ahí
  pierde poderes.
- Un `operador` global **no** puede ser gestor en ninguna sucursal: para
  eso hay que darle de alta con rol global `gestor` (o `admin`).

OJO (2026-10-24): la primera versión de este ADR decía que «un `operador`
global que es `gestor` en la sucursal A puede fijar tarifas en A». Eso
**contradecía** las reglas 2 y 4 (con el techo, ese usuario es operador en
A) y además rompía un producto ya decidido del repo (el operador que sube
un adjunto no puede volver a listarlo: `incidents.py`). Se implementó el
**techo**, que es lo que dicen **tres** reglas y su justificación («asignar
de menos, nunca de más»), y se corrigió este punto.

Si algún día se quiere el otro sentido (que el rol de la sucursal **suba**),
el cambio está en **una sola función**: `deps._rol_mas_restrictivo` (y el
test `test_el_rol_global_es_el_techo`, que es el que fija esa lectura).

### Por qué el «techo» y no «la unión»

La alternativa sería que el rol de la sucursal **sumase** poder
(`role_in_parking = admin` ⇒ admin de esa sucursal). Se descarta: convertiría
una fila de la tabla de membresías en una **escalada de privilegios**, y
`role_in_parking` se rellena desde un formulario. Con el techo, el worst case
es que un rol global se quede **por debajo** de lo que el operador quería
—asignar de menos, nunca de más— y eso se corrige asignando bien la membresía.

### Consecuencias

- `parking_memberships.role_in_parking` pasa de **decorativa** a **leída**: es la
  fuente de la autorización por sucursal.
- Un `admin` global **no** necesita membresía: su poder es global (se mantiene
  la excepción actual).
- Los listados globales (`GET /vehicles`, `GET /users`) siguen siendo de
  `admin`; el personal usa el endpoint acotado a su sucursal.

## Lo que NO cambia

- La **membresía** sigue diciendo en qué sucursales estás.
- El T-114 (la membresía no convierte a un cliente en gestor) **sigue siendo
  cierto**, y ahora con una regla más fuerte.
- El ADR 0003 (aislamiento por sucursal) sigue vigente: este ADR sólo cambia
  **de dónde sale el rol**.

## Cómo se comprueba

- Tests del backend: rol global × rol de sucursal × endpoint.
- La puerta `tools/verificar_aislamiento_sucursal.py` (con su autoprueba)
  comprueba que cada endpoint acotado a una sucursal usa el rol **de esa
  sucursal** y no el global.
