# Frontend de solidAPP

SPA de Vue 3 + Vite + Pinia + Vue Router + Tailwind + Axios. Sirve para
los tres perfiles de la web (admin, gestor, operador) y para la **PWA
instalable del cliente final** (ver § PWA).

## Comandos

```bash
npm install          # sólo la primera vez (en Docker no hace falta)
npm run dev          # servidor de desarrollo en :5173 (HMR)
npm run type-check   # vue-tsc --noEmit (lo que corre el CI)
npm run build        # type-check + build de producción en dist/
npm run preview      # sirve dist/ en :4173 (aquí se prueba la PWA)
```

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

`scripts/qa_visual.py` recorre las 18 pantallas de los tres roles con las
cuentas **demo** del seed, hace una captura de cada una y recoge los
**errores de consola** y las **peticiones fallidas**. Es lo que cubre la
parte de "la pantalla se renderiza" que los tests no pueden.

```bash
# el stack tiene que estar arriba (docker compose up -d)
python scripts/qa_visual.py --salida D:/tmp/qa-solidapp
```

Salida: un `informe.json` con el detalle y un PNG por pantalla.

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
