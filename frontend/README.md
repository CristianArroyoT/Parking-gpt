# Frontend de solidAPP

SPA de Vue 3 + Vite + Pinia + Vue Router + Tailwind + Axios. Sirve para
los tres perfiles de la web (admin, gestor, operador) y para la **PWA
instalable del cliente final** (ver § PWA).

## Comandos

```bash
npm install          # sólo la primera vez (en Docker no hace falta)
npm run dev          # servidor de desarrollo en :5173 (HMR)
npm run lint         # eslint (config plano: eslint.config.js) — lo que corre el CI
npm run type-check   # vue-tsc --noEmit (lo que corre el CI)
npm run build        # type-check + build de producción en dist/
npm run preview      # sirve dist/ en :4173 (aquí se prueba la PWA)
```

### El linter (ESLint 9, configuración plana)

El linter usa `eslint.config.js` (el formato plano que exige ESLint 9) con
`js.configs.recommended` + `pluginVue.configs['flat/essential']` +
`vueTsConfigs.recommended`.

**`flat/essential` y no `flat/recommended`** a propósito: "recommended"
arrastra reglas de **formato** (una etiqueta por línea, un atributo por
línea…) que son opinión y que obligarían a reformatear el frontend entero.
Con "essential" el linter avisa de lo que está **mal**: variables sin
usar, referencias sin definir, hooks mal usados.

Hay dos reglas apagadas a propósito, con el motivo en el propio fichero:
`vue/multi-word-component-names` (la convención del proyecto usa
componentes de una palabra: `Login`, `Home`) y
`@typescript-eslint/no-empty-object-type` **sólo en `*.d.ts`** (el shim
estándar de Vue, `DefineComponent<{}, {}, any>`, dispara la regla).

El frontend siempre habla con rutas relativas `/api/v1`; el proxy de Vite
las manda al backend (por defecto `http://localhost:8000`, se puede
cambiar con la variable `VITE_PROXY_TARGET`, que **no** se inyecta en el
bundle porque su nombre no empieza por `VITE_`).

## ⚠️ En Docker Desktop (Windows) el HMR no se dispara

Al editar un fichero del frontend desde Windows, **Vite no se entera**: los
bind mount de Docker Desktop no propagan los eventos de cambio de fichero al
contenedor, así que el watcher no invalida el módulo y el navegador se
sigue viendo la versión antigua. No es un fallo del código: el fichero en
disco sí ha cambiado, y `npm run build` sí lo compila bien.

**Síntoma**: la pantalla sigue igual que antes del cambio, o una ruta nueva
devuelve "Página no encontrada" aunque la ruta esté en `src/router/index.ts`.

**Arreglo**: reiniciar el servidor de desarrollo.

```bash
docker compose restart frontend
```

Esto se detectó haciendo la QA visual del 2026-10-21 (dos veces: una ruta
nueva que salía como inexistente y un texto que no cambiaba).

## QA visual (Chromium headless)

`scripts/qa_visual.py` recorre las 26 pantallas de los tres roles con las
cuentas **demo** del seed, hace una captura de cada una y recoge los
**errores de consola** y las **peticiones fallidas**. Es lo que cubre la
parte de "la pantalla se renderiza" que los tests no pueden.

```bash
# el stack tiene que estar arriba (docker compose up -d)
python scripts/qa_visual.py --salida D:/tmp/qa-solidapp

# con el ancho del panel lateral del navegador integrado (1232 px)
python scripts/qa_visual.py --salida D:/tmp/qa-solidapp-1232 --ancho 1232

# con el ancho de un móvil
python scripts/qa_visual.py --salida D:/tmp/qa-solidapp-414 --ancho 414

# los cinco anchos en UN solo proceso (esto es lo que usa verificar_repo.py)
python scripts/qa_visual.py --salida D:/tmp/qa-solidapp \
  --anchos "414,768,1024,1232,1440"
```

> **Por qué existe `--anchos`**: `POST /auth/login` tiene un rate-limit de
> **10 intentos por IP cada 5 minutos**. La QA inicia sesión **una vez por
> rol** (3 inicios), así que recorrer 5 anchos en 5 procesos distintos
> son 15 inicios: a partir del cuarto, el login devolvía **429** y la QA
> reportaba "no se pudo iniciar sesión" sin decir por qué. Con
> `--anchos`, el proceso **inicia sesión una sola vez por rol** y cambia
> el viewport de la misma página para cada ancho: 3 inicios en total, y
> los 5 anchos salen de una tirada. Además, el motivo del fallo de login
> ahora se reporta: un 429 se distingue de un timeout.

Salida: un `informe.json` con el detalle y un PNG por pantalla (con
`--anchos`, en una subcarpeta por ancho). El script devuelve **1** si
alguna pantalla tiene contenido recortado o desbordado, y 0 si todo está
bien.

Las pantallas de **mapa** y de **vídeo en directo** no dejan de cargar
nunca (teselas del mapa y flujo SSE), así que la espera de "networkidle"
siempre se agota ahí. Eso se reporta como **aviso**, no como error de red:
es tráfico de fondo, no una pantalla rota.

### Detección de contenido que no cabe

Además de los errores de consola, la QA comprueba que **nada se salga de
su sitio**: si un elemento es más ancho que su caja y no hay ningún
contenedor que lo deje desplazar, se reporta como `DESBORDE`.

Esto se añadió el 2026-10-21 tras encontrar un defecto real: la tabla de
**Operadores** no cabía en su mitad de la rejilla a 1232 px de ventana y la
columna "Estado" (los badges "Activo") quedaba cortada a media. La QA
headless de siempre corría a 1440 px, donde la columna sí cabe, así que no
lo veía. El arreglo fue envolver las tablas que no caben en un contenedor
con `overflow-x-auto` y darles `min-w-max` para que conserven su ancho de
contenido y se puedan desplazar.

Vistas arregladas: Operadores, Cámaras, Planes, Usuarios y Tarifas. A 1232
px la QA pasa de **5 contenidos desbordados a 0**.

El detector **excluye a propósito** tres cosas que no son defectos:

- Los controles de formulario (`select`, `input`, `textarea`): el navegador
  los recorta de forma nativa (el texto seleccionado sale con puntos
  suspensivos y el desplegable muestra el valor completo).
- Los elementos posicionados en absoluto o fijo: menús, desplegables y
  tooltips, que desbordan a propósito.
- Los contenedores con scroll propio: su contenido es más ancho porque el
  usuario lo desplaza.

### Anchos que se revisan

| Ancho | Qué representa | Resultado |
|---|---|---|
| 1440 px | Referencia de escritorio | 0 desbordes |
| 1232 px | Panel lateral del navegador integrado | 0 desbordes (antes 5) |
| 1024 px | Tablet con el menú colapsado | 0 desbordes (antes 1) |
| 768 px | Tablet vertical | 0 desbordes |
| 414 px | Móvil (iPhone XR) | 0 desbordes (antes 26) |

A 1024 px salió el último defecto: la etiqueta **"Minutos/fracción"** de
Tarifas era un único token sin espacios (98 px) en una caja de 86 px, así
que se salía de su columna. Ahora dice "Minutos por fracción", que parte en
dos palabras como la etiqueta de al lado.

### El móvil (414 px): la página entera se desplazaba

La QA siempre se había corrido a 1440 px, así que **nunca se vio el
móvil**: a 414 px, **6 de las 21 pantallas** tenían contenido que se salía
de su caja (**26 desbordes** en total) y **3 de ellas** tenían además la
página entera desplazable de lado a lado (Movimientos, Operadores y
Tickets). En un teléfono, el usuario tenía que mover la ventana para ver
el final de una tabla.

El arreglo tiene **dos** partes, y con una sola no basta:

1. Envolver la tabla en un `div` con `overflow-x-auto`, para que la tabla
   se desplace dentro de su tarjeta en vez de salirse de ella.
2. Poner `min-w-0` **en el ítem de la rejilla** que contiene la tabla (y no
   sólo en el envoltorio). Un ítem de rejilla o de flex tiene
   `min-width: auto`, que lo ata a la anchura mínima de su contenido: sin
   `min-w-0`, la columna no baja de la anchura de la tabla y la página
   vuelve a desbordar. Esto se comprobó con `scripts/sonda_anchura.py`,
   que mide la cadena de ancestros del elemento más ancho.

`tools/envolver_tablas.py` aplica el punto 1 de forma mecánica a todas las
vistas (muda la directiva `v-else` al envoltorio y añade `min-w-max`
dentro del atributo `class` de la tabla).

### La sonda de anchuras

`scripts/sonda_anchura.py` responde a "¿de dónde sale este
desbordamiento?" midiendo, en cada escalón de la cadena de ancestros, la
anchura real, el `min-width` calculado, el `overflow-x` y el `display`. Es
lo que permite distinguir "este elemento es el culpable" de "este otro sólo
lo arrastra".

```bash
python scripts/sonda_anchura.py --ruta /gestor/operadores --ancho 414
```

## QA del PWA (instalabilidad y modo sin red)

`scripts/qa_pwa.py` comprueba lo que la QA visual no mira: que la app sea
**instalable** y que **arranque sin red**.

```bash
npm run build          # el PWA sólo se registra en producción
python scripts/qa_pwa.py
```

Comprueba:

1. El manifiesto se descarga y se parsea, con los campos que Chrome exige
   para ofrecer "Instalar app" (`name`, `start_url`, `display`, `icons`) y
   los tamaños de icono obligatorios (192 y 512).
2. **Cada icono del manifiesto se sirve con 200** y no está vacío: un icono
   que devuelve 404 sólo se detecta cuando el usuario intenta instalar.
3. El *service worker* se registra, queda activo y **toma el control** de la
   página.
4. La **app arranca sin red**: se corta la red, se recarga y la pantalla
   tiene que salir desde la caché del SW.

Resultado de la última ejecución (2026-10-21, sobre `dist/`):

```
manifiesto OK: solidAPP · Cliente | 4 iconos | display=standalone
service worker OK: activo, controlando, 44 entradas precacheadas en 1 cache(s)
sin red: la app arranca desde la cache del service worker
```

> **Por qué no está en el CI**: el job de frontend corre en una imagen de
> Node sin Python ni navegadores. Añadirlo exigiría instalar Playwright y
> Chromium en la imagen del CI (+~500 MB y minutos de descarga), y ahora
> mismo no se puede validar un cambio del workflow porque la
> facturación de la cuenta impide que los jobs arranquen. Está
> documentado como propuesta (T-24+1) para cuando el CI vuelva a estar
> en marcha.

Resultado de la última ejecución (2026-10-22, con el stack completo):
**26 pantallas × 5 anchos (414, 768, 1024, 1232 y 1440 px) = 130 capturas,
0 desbordes, 0 errores de consola y 0 errores de login**. Quedan 10 avisos
que **no son fallos** (2 por ancho): `/mapa` y `/vivo` agotan el
tiempo de espera de `networkidle` porque mantienen una conexión abierta (el
SSE del mapa y el preview MJPEG), así que la red nunca queda en reposo. Es
inherente a esas dos pantallas; el resto se captura bien.

> Si el script falla con `ERR_CONNECTION_RESET` en la pantalla de login,
> casi siempre es que hay otra cosa comiéndose la CPU (un build de Docker,
> por ejemplo): el servidor de desarrollo tarda y el navegador aborta la
> petición. Repitiendo la ejecución en reposo, sale limpio.

## PWA — app instalable del cliente

**Decisión D4 del plan maestro (2026-10-21): PWA, no app nativa.** Un
solo codebase, instalable desde el navegador, sin tiendas de apps. La
app es **sólo para el rol `cliente`**.

### Ficheros

| Fichero | Para qué sirve |
|---|---|
| `public/manifest.webmanifest` | Nombre, iconos, `start_url`, `display: standalone`, color de tema y accesos directos. |
| `public/sw.js` | Service worker: precachea el *shell* y **no** cachea `/api/`. La política está documentada en la cabecera del fichero. |
| `public/icons/` | Iconos PNG (192, 512, maskable, apple-touch) y `icon.svg`, que es la fuente de verdad del diseño. |
| `scripts/generar-iconos-pwa.py` | Regenera los PNG a partir de la geometría del SVG (`python scripts/generar-iconos-pwa.py`). |
| `src/pwa/registerServiceWorker.ts` | Registra el service worker **sólo en producción** (`import.meta.env.PROD`). |
| `src/pwa/mode.ts` | `isPwaMode()`: detecta si la app está corriendo como PWA instalada. |
| `vite.config.ts` | Sirve `sw.js` y el manifest sin caché, e inyecta en `dist/sw.js` la lista de assets del build para que el SW los precachee. |

### Cómo instalarla

**Chrome o Edge (escritorio, Windows/macOS/Linux)**

1. Abre la app en modo `https://` (o `http://localhost`).
2. En la barra de direcciones aparece un icono de instalación (⊕) a la
   derecha de la URL, o en el menú ⋮ → *Instalar solidAPP*.
3. Se instala como una aplicación de escritorio (ventana propia, sin
   barra de direcciones).

**Android (Chrome)**

1. Abre la web de la app.
2. Menú ⋮ → *Instalar app* / *Añadir a pantalla de inicio*.
3. Aparece un icono en el cajón de aplicaciones.

**iOS (Safari)**

1. Abre la web de la app en **Safari** (no en Chrome: iOS no ofrece
   instalación desde otros navegadores).
2. Botón *Compartir* (⊞) → *Añadir a pantalla de inicio*.
3. Le pone el icono `apple-touch-icon` y abre a pantalla completa
   (`apple-mobile-web-app-capable`).

### Qué funciona sin conexión y qué no

- **Sí**: la app abre y muestra su interfaz (el *shell* — HTML, CSS,
  JavaScript y todos los trozos de las rutas — está precacheado).
- **No**: los datos. Las peticiones a `/api/` **nunca** se cachean: tu
  plaza, tus tickets y el importe pendiente se piden siempre a la red.
  Es una decisión deliberada — una plaza averiada o un ticket ya cobrado
  que siguen apareciendo desde la caché son peores que no tener app
  offline. Sin conexión, la app lo dice con un error honesto en vez de
  enseñar datos viejos.

### Limitaciones

- **Sin notificaciones push**: no hay Web Push ni *background sync*.
- **Sin cobro dentro de la app**: el cobro es contable (decisión D2 del
  plan maestro). No hay pasarela, ni TPV, ni datos de tarjeta: la app
  informa del importe pendiente y el pago lo registra el personal de la
  sucursal.
- **Sin App Store ni Play Store**: no se actualiza desde la tienda; las
  actualizaciones llegan con el `sw.js` nuevo (el navegador lo descarga
  al abrir la app).
- **Sin iOS "background fetch"**: en iOS la app sólo refresca datos
  cuando se abre; no hay sincronización en segundo plano.
- **Sólo HTTPS** (o `localhost`): los navegadores no registran service
  workers en HTTP sin cifrar.
- La instalación en iOS no muestra el prompt automático: hay que usar
  *Compartir → Añadir a pantalla de inicio* a mano.

### Requisitos del servidor (producción)

El servidor estático que sirva `dist/` tiene que cumplir tres cosas:

1. `Content-Type: application/manifest+json` para `*.webmanifest`
   (nginx: `types { application/manifest+json webmanifest; }`).
2. `Cache-Control: no-cache` (o `no-store`) para `/sw.js`: si el
   navegador cachea el service worker, sigue ejecutando la versión vieja.
3. `index.html` **sin** cache (o con revalidación), para que un despliegue
   nuevo se vea al abrir la app.

El servicio de `dist/` en `npm run preview` ya cumple las tres.

### Modo "sólo cliente" (pendiente en layout y router)

`src/pwa/mode.ts` exporta `isPwaMode()`, que avisa de que la app está
corriendo como PWA instalada (o con `?pwa=1`, que es lo que pone el
`start_url` del manifest). Para que en la PWA **no** aparezcan las
pantallas de gestor, operador ni admin hacen falta dos cambios en
ficheros que son de otro subagente:

**`src/layouts/AppLayout.vue`** — filtrar el menú por rol:

```ts
import { isPwaMode } from '@/pwa/mode'

const nav = computed<NavItem[]>(() => {
  const items = auth.role ? NAV_BY_ROLE[auth.role] ?? [] : []
  // En la PWA sólo el cliente: nada de gestor ni de operador.
  return isPwaMode() ? items.filter((i) => i.name.startsWith('cliente-')) : items
})
```

**`src/router/index.ts`** — forbidding las rutas que no son del cliente
en modo PWA (en `beforeEach`, antes del chequeo de `meta.roles`):

```ts
import { isPwaMode } from '@/pwa/mode'

// Rutas del cliente en la PWA: /mis-tickets, /mis-vehiculos, /mi-plaza,
// /mi-plan, /mi-perfil, /pagos, …
const esRutaDeCliente = (path: string) =>
  path === '/login' || path.startsWith('/mis-') || path.startsWith('/mi-') || path.startsWith('/pagos')

if (isPwaMode() && !to.meta.public && !esRutaDeCliente(to.path)) {
  return { name: 'cliente-tickets' }
}
```

## Pantallas del cliente y de qué endpoints dependen

| Pantalla | Vista | Endpoints |
|---|---|---|
| Mis tickets | `src/views/cliente/TicketsView.vue` | `GET /tickets` |
| Mis vehículos | `src/views/cliente/VehiclesView.vue` | `GET /users/me/vehicles` (T-19) |
| Mi plan | `src/views/cliente/MyPlanView.vue` | `GET /plans/me` (T-18) |
| **Mi plaza** | `src/views/cliente/MySpotView.vue` | `GET /cliente/plazas` + `GET /users/me/vehicles` |
| **Pago** | `src/views/cliente/PaymentsView.vue` | `GET /cliente/tickets` + `GET /plans/me` |

`GET /cliente/*` (`backend/app/api/v1/cliente.py`) es el único router
nuevo de T-24: devuelve los datos **enriquecidos** que el cliente no
puede obtener por su cuenta (la etiqueta de la plaza, el nombre de la
sucursal y el flag de "pendiente de pago"), porque un cliente sin
membresía de sucursal recibe 403 al pedir espacios o sucursales.
