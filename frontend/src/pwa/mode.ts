/**
 * Detección del modo PWA (T-24).
 *
 * La PWA instalable es **sólo para el rol `cliente`**: el menú de
 * gestor, de operador y de admin no debe aparecer en la app instalada.
 * Para poder filtrarlo hace falta una señal fiable de "estamos dentro
 * de la PWA", y ésa es la que da este módulo.
 *
 * Tres señales, de la más fuerte a la más débil:
 *
 *  1. `display-mode: standalone` → la app está abierta como app
 *     instalada (Chrome, Edge, Android). Es la señal de referencia.
 *  2. `navigator.standalone` → el equivalente en iOS (Safari instalado
 *     en la pantalla de inicio).
 *  3. `?pwa=1` en la URL → lo pone el `start_url` del manifest, así que
 *     funciona también en navegadores sin `display-mode` y sirve para
 *     depurar ("abre la PWA en modo navegador con `?pwa=1`").
 *
 * El resultado se recuerda en `localStorage` porque, dentro de una SPA,
 * la query de la URL se pierde al navegar (Vue Router sustituye la
 * URL); la señal de `display-mode`, en cambio, sigue siendo cierta
 * durante toda la sesión de la app instalada.
 *
 * Uso previsto (el layout y el router son de otro subagente):
 *
 *     import { isPwaMode } from '@/pwa/mode'
 *
 *     // en AppLayout.vue: filtrar el menú por rol
 *     const nav = computed(() => {
 *       const items = auth.role ? NAV_BY_ROLE[auth.role] ?? [] : []
 *       return isPwaMode() ? items.filter((i) => i.name.startsWith('cliente-')) : items
 *     })
 *
 *     // en router/index.ts: impedir las rutas de gestor en la PWA
 *     if (isPwaMode() && !to.path.startsWith('/mis-') && !to.path.startsWith('/mi-')
 *         && to.path !== '/pagos' && to.path !== '/login') {
 *       return { name: 'cliente-tickets' }
 *     }
 */
const CLAVE = 'solidapp.modo-pwa'

/** ¿La app se está usando como PWA instalada (sólo cliente)? */
export function isPwaMode(): boolean {
  if (typeof window === 'undefined') return false

  // 1. Recordado de una detección anterior en esta misma instalación.
  try {
    if (window.localStorage.getItem(CLAVE) === '1') return true
  } catch {
    /* localStorage puede estar bloqueado: no es motivo para fallar */
  }

  // 2. Instalada como app (Chromium / Edge / Android).
  const standalone =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(display-mode: standalone)').matches

  // 3. Instalada como app (iOS Safari).
  const iosStandalone =
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true

  // 4. Forzado por la URL (`start_url` del manifest o depuración).
  const porUrl =
    new URLSearchParams(window.location.search).get('pwa') === '1'

  if (standalone || iosStandalone || porUrl) {
    try {
      window.localStorage.setItem(CLAVE, '1')
    } catch {
      /* idem: sin localStorage seguimos funcionando */
    }
    return true
  }
  return false
}
