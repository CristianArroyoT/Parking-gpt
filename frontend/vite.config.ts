import { fileURLToPath, URL } from 'node:url'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

// Proxy de /api al backend en :8000. Lee VITE_PROXY_TARGET por si la
// pila expone el backend en otro host (Docker compose, k8s, etc.).
// Ojo: la variable se llama así (no VITE_API_BASE) precisamente para
// que Vite NO la inyecte en el bundle del frontend. El bundle debe
// usar SIEMPRE rutas relativas '/api/v1' para pasar por este proxy.
export default defineConfig({
  plugins: [vue(), pwaSinCache(), pwaPrecacheDeAssets()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    host: true,
    // El preview sirve el build de producción: es donde se puede probar
    // la PWA (el service worker sólo se registra en producción). Proxy
    // igual que en desarrollo para poder hablar con la API.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

/**
 * T-24 (PWA): `sw.js` y `manifest.webmanifest` se sirven **sin cache**.
 *
 * Si el navegador cachea el service worker, sigue ejecutando la versión
 * vieja aunque se haya desplegado otra: el usuario se queda con un bundle
 * obsoleto (y el service worker antiguo puede cachear assets viejos).
 * Es la razón por la que los Service Workers se sirven con
 * `Cache-Control: no-cache`.
 *
 * En producción el servidor estático (nginx) tiene que hacer lo mismo:
 * ver `frontend/README.md` (§ PWA).
 */
function pwaSinCache(): Plugin {
  const middleware = (
    req: IncomingMessage,
    res: ServerResponse,
    next: () => void,
  ): void => {
    const ruta = (req.url || '').split('?')[0]
    if (ruta === '/sw.js' || ruta === '/manifest.webmanifest') {
      res.setHeader('Cache-Control', 'no-store')
    }
    next()
  }
  return {
    name: 'solidapp-pwa-sin-cache',
    configureServer(server) {
      server.middlewares.use(middleware)
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware)
    },
  }
}

/**
 * T-24 (PWA): inyecta en `dist/sw.js` la lista de assets del build.
 *
 * Los ficheros del build llevan hash en el nombre (`index-<hash>.js`),
 * así que el service worker no puede conocerlos de antemano. Este plugin
 * los lista al terminar el build y los deja en `self.__ASSETS_BUILD__`,
 * que es lo que el SW precachea al instalarse.
 *
 * Sin esto, la app abre sin conexión pero se queda en blanco: el bundle
 * principal sí está (viene en el `index.html`), pero los trozos de las
 * rutas (`LoginView-*.js`, `TicketsView-*.js`, …) se piden al navegar y
 * fallan sin red.
 */
function pwaPrecacheDeAssets(): Plugin {
  return {
    name: 'solidapp-pwa-precache',
    apply: 'build',
    enforce: 'post',
    closeBundle() {
      const dist = resolve(process.cwd(), 'dist')
      const swPath = join(dist, 'sw.js')
      if (!existsSync(swPath)) return

      const assets: string[] = []
      const recorrer = (dir: string): void => {
        for (const entrada of readdirSync(dir)) {
          const ruta = join(dir, entrada)
          if (statSync(ruta).isDirectory()) {
            recorrer(ruta)
          } else if (!entrada.endsWith('.map')) {
            const rutaRel = relative(dist, ruta).split(/[\\/]/).join('/')
            assets.push('/' + rutaRel)
          }
        }
      }
      const assetsDir = join(dist, 'assets')
      if (existsSync(assetsDir)) recorrer(assetsDir)

      const sw = readFileSync(swPath, 'utf8')
      const inyeccion = `self.__ASSETS_BUILD__ = ${JSON.stringify(assets)};`
      writeFileSync(swPath, sw.replace('/* __ASSETS_BUILD__ */', inyeccion), 'utf8')
      console.log(`[solidAPP] SW: ${assets.length} assets para precachear`)
    },
  }
}
