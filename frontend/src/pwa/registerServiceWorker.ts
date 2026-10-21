/**
 * Registro del service worker de la PWA (T-24 · app del cliente).
 *
 * Sólo se registra en **producción** (`import.meta.env.PROD`):
 *
 * - En desarrollo el SW estorba: cachea el bundle viejo mientras se
 *   escribe código y hace que los cambios no se vean hasta recargar
 *   dos veces.
 * - Vite ya sirve los módulos con su propio grafo de dependencias; en
 *   desarrollo no hace falta un service worker para nada.
 *
 * El service worker vive en `frontend/public/sw.js` (fichero estático,
 * se copia tal cual a `dist/`). Su estrategia de caché está documentada
 * en la cabecera de ese fichero: cachea el shell de la app y **nunca**
 * las peticiones a `/api/`.
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((reg) => {
        // Aviso (por consola) cuando hay una versión nueva esperando:
        // el SW nuevo toma el control en la siguiente carga completa.
        reg.addEventListener('updatefound', () => {
          const instalando = reg.installing
          if (!instalando) return
          instalando.addEventListener('statechange', () => {
            if (instalando.state === 'installed' && navigator.serviceWorker.controller) {
              console.info(
                '[solidAPP] Hay una versión nueva de la app: recarga la página para verla.',
              )
            }
          })
        })
      })
      .catch((err: unknown) => {
        // Sin SW la app sigue funcionando (sólo se pierde el modo
        // offline y la instalación). No se rompe nada por esto.
        console.warn('[solidAPP] No se pudo registrar el service worker:', err)
      })
  })
}
