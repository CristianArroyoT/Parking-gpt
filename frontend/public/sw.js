/*
 * Service worker de la PWA de solidAPP (T-24 · app del cliente).
 *
 * ═══════════════════════════════════════════════════════════════════════
 * QUÉ SE CACHEA Y QUÉ NO (decisión del plan maestro, 2026-10-21)
 * ═══════════════════════════════════════════════════════════════════════
 *
 * SÍ se cachea:
 *   - El *shell* de la app: el HTML de la SPA, el manifest y los iconos.
 *     Con esto la PWA **abre sin conexión** y muestra la interfaz.
 *   - Los ficheros estáticos (JS, CSS, fuentes, imágenes) que pide el
 *     navegador: se sirven de caché primero y se revalidan en segundo
 *     plano, así que la app abre al instante incluso sin red.
 *
 * NO se cachea — y esto es deliberado:
 *   - **Nada de lo que llegue por `/api/`.** Los datos en vivo (tu plaza,
 *     tus tickets, el importe pendiente) SIEMPRE van a la red. La razón
 *     es de producto: una plaza averiada o un ticket ya cobrado que
 *     siguen apareciendo desde la caché son PEORES que no tener app
 *     offline. "No funciona sin conexión" es un límite aceptable;
 *     "miente sobre el estado de tu coche" no lo es.
 *   - Las peticiones a otros orígenes (CDN de fuentes, etc.): van
 *     directas a la red, sin intermediario.
 *
 * ═══════════════════════════════════════════════════════════════════════
 */

const VERSION = 'v1';
const CACHE_SHELL = 'solidapp-shell-' + VERSION;
const CACHE_ESTATICOS = 'solidapp-estaticos-' + VERSION;

/** Ficheros que forman el shell mínimo de la app. */
const SHELL = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/logo-solidapp.png',
  '/favicon-solidapp.png',
];

/** Extensiones que se sirven de caché (todo lo demás va a la red). */
const EXT_ESTATICAS = [
  '.js', '.mjs', '.css', '.map', '.woff', '.woff2', '.ttf', '.otf',
  '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico',
];

/**
 * `ignoreVary: true` al buscar en la caché.
 *
 * El servidor de estáticos responde con `Vary: Origin`, y los módulos ES
 * se piden en modo CORS (llevan cabecera `Origin`), mientras que la
 * petición que hace el service worker al precachear no la lleva. Sin
 * ignorar `Vary`, la caché nunca "casa" y la app no abre sin conexión.
 */
const MATCH_OPCIONES = { ignoreVary: true };

function esEstatico(url) {
  if (url.pathname.startsWith('/assets/')) return true;
  return EXT_ESTATICAS.some((ext) => url.pathname.toLowerCase().endsWith(ext));
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_SHELL);
      // addAll() falla entero si un solo recurso falla; aquí cada uno va
      // por separado para que un icono ausente no rompa la instalación.
      await Promise.all(
        SHELL.map(async (ruta) => {
          try {
            await cache.add(new Request(ruta, { cache: 'reload' }));
          } catch (err) {
            console.warn('[solidAPP] SW: no se pudo precachear', ruta, err);
          }
        })
      );
      await precachearAssetsDeVite(cache);
      await self.skipWaiting();
    })()
  );
});

/**
 * Lista de assets del build.
 *
 * La inyecta el plugin `pwaPrecacheDeAssets` de `vite.config.ts` al
 * generar `dist/sw.js` (sustituye el comentario de abajo). En
 * desarrollo queda vacía: el service worker no se registra fuera de
 * producción.
 */
/* __ASSETS_BUILD__ */
const ASSETS_BUILD = self.__ASSETS_BUILD__ || [];

/**
 * Precachea los assets con hash que genera el build de Vite.
 *
 * Los nombres de los ficheros (``/assets/index-<hash>.js``) no se conocen
 * de antemano, así que se descubren leyendo el ``index.html`` del build
 * o, mejor, usando la lista que inyecta el plugin de Vite.
 *
 * Sin esto, la PRIMERA visita sin conexión se quedaría sin JavaScript:
 * el service worker se registra después de que el navegador ya ha
 * descargado los assets, y en esa primera carga no los ve pasar por él.
 */
async function precachearAssetsDeVite(cache) {
  const urls = new Set(ASSETS_BUILD);
  try {
    const res = await fetch('/index.html', { cache: 'reload' });
    const html = await res.text();
    const re = /(?:src|href)="(\/assets\/[^"]+)"/g;
    let m;
    while ((m = re.exec(html)) !== null) urls.add(m[1]);
  } catch (err) {
    console.warn('[solidAPP] SW: no se pudo leer el index.html', err);
  }
  await Promise.all(
    Array.from(urls).map(async (url) => {
      try {
        await cache.add(new Request(url, { cache: 'reload' }));
      } catch (err) {
        console.warn('[solidAPP] SW: no se pudo precachear', url, err);
      }
    })
  );
}

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const claves = await caches.keys();
      await Promise.all(
        claves
          .filter((c) => c !== CACHE_SHELL && c !== CACHE_ESTATICOS)
          .map((c) => caches.delete(c))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Sólo GET: las mutaciones van siempre a la red.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // ── LA API NO SE CACHEA NUNCA ──────────────────────────────────────
  // Los datos en vivo (plaza, tickets, pago) se piden siempre a la red.
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) {
    return;
  }

  // Otros orígenes (CDN de fuentes, etc.): directo a la red.
  if (url.origin !== self.location.origin) return;

  // ── Navegaciones: red primero, shell como respaldo ────────────────
  // Así la app abre al instante y, si no hay red, muestra la última
  // versión del shell (la vista luego pide sus datos a la API, que
  // fallará con honestidad: mejor un error de red que datos falsos).
  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const fresca = await fetch(req);
          if (fresca && fresca.ok) {
            const cache = await caches.open(CACHE_SHELL);
            cache.put('/index.html', fresca.clone());
          }
          return fresca;
        } catch (err) {
          const cache = await caches.open(CACHE_SHELL);
          const guardada =
            (await cache.match('/index.html', MATCH_OPCIONES)) ||
            (await cache.match('/', MATCH_OPCIONES));
          if (guardada) return guardada;
          return new Response(
            '<!doctype html><meta charset="utf-8">' +
              '<title>solidAPP sin conexión</title>' +
              '<body style="font-family:system-ui;padding:2rem">' +
              '<h1>Sin conexión</h1>' +
              '<p>Abre la app con red para ver tu plaza y tus tickets.</p>',
            { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          );
        }
      })()
    );
    return;
  }

  // ── Estáticos: caché primero + revalidación en segundo plano ──────
  if (esEstatico(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_ESTATICOS);
        // Los assets del build se precachean en el cache del shell (ver
        // `precachearAssetsDeVite`), así que se buscan en los dos.
        let guardada = await cache.match(req, MATCH_OPCIONES);
        if (!guardada) {
          const shell = await caches.open(CACHE_SHELL);
          guardada =
            (await shell.match(req, MATCH_OPCIONES)) ||
            // Respaldo sin query string: el logo se pide como
            // `/logo-solidapp.png?v=2` y la versión cacheada no la lleva.
            (await shell.match(url.pathname, MATCH_OPCIONES));
        }

        const desdeRed = fetch(req)
          .then(async (r) => {
            if (r && r.ok && r.type === 'basic') {
              try {
                await cache.put(req, r.clone());
              } catch (err) {
                /* cuota llena: no es crítico */
              }
            }
            return r;
          })
          .catch(() => undefined);

        if (guardada) {
          void desdeRed; // se revalida en segundo plano
          return guardada;
        }
        const r = await desdeRed;
        if (r) return r;
        return new Response('', { status: 504, statusText: 'Sin conexión' });
      })()
    );
  }
  // El resto de peticiones (mismo origen, no estáticas): red directa.
});
