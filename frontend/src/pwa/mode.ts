/**
 * Detección del modo PWA (T-24; corregido en T-66).
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
 * OJO (2026-10-22, T-66): la tercera señal se recuerda en
 * `sessionStorage` (la PESTAÑA), **no** en `localStorage` (el navegador
 * entero). Antes se guardaba en `localStorage` y nunca se limpiaba: un
 * admin que abría la app con `?pwa=1` (o que instalaba la PWA de
 * cliente) quedaba **encerrado** en las rutas de cliente para siempre,
 * sin forma de volver al panel de administración salvo borrar el
 * almacenamiento a mano. Y la señal "recordada" tenía prioridad sobre
 * la real, así que tampoco servía abrir la app en otra pestaña.
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

  // 0. Limpieza del flag antiguo (T-66): estaba en `localStorage` y
  //    encerraba a quien lo activaba. Se borra, no se lee: así, quien
  //    quedó encerrado sale solo al abrir la app.
  try {
    window.localStorage.removeItem(CLAVE)
  } catch {
    /* localStorage puede estar bloqueado: no es motivo para fallar */
  }

  // 1. Instalada como app (Chromium / Edge / Android).
  const standalone =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(display-mode: standalone)').matches

  // 2. Instalada como app (iOS Safari).
  const iosStandalone =
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true

  if (standalone || iosStandalone) return true

  // 3. Forzado por la URL (`start_url` del manifest o depuración).
  const porUrl =
    new URLSearchParams(window.location.search).get('pwa') === '1'
  if (porUrl) {
    // Se recuerda en la PESTAÑA, no para siempre (T-66).
    try {
      window.sessionStorage.setItem(CLAVE, '1')
    } catch {
      /* sin sessionStorage seguimos funcionando */
    }
    return true
  }

  // 4. Forzado antes en ESTA pestaña.
  try {
    if (window.sessionStorage.getItem(CLAVE) === '1') return true
  } catch {
    /* idem: sin sessionStorage seguimos funcionando */
  }
  return false
}
