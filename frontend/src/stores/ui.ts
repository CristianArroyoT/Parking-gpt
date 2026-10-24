/**
 * Estado efímero de UI: sidebar móvil, toasts.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  type: 'info' | 'success' | 'warn' | 'error'
  message: string
}

export const useUiStore = defineStore('ui', () => {
  const sidebarOpen = ref(false)
  const toasts = ref<Toast[]>([])
  let nextId = 1

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }
  function closeSidebar(): void {
    sidebarOpen.value = false
  }
  function pushToast(type: Toast['type'], message: string, ttl = 4000): void {
    const id = nextId++
    toasts.value.push({ id, type, message })
    if (ttl > 0) setTimeout(() => dismissToast(id), ttl)
  }
  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  /**
   * T-174 (2026-10-24): al cerrar sesión, el estado de UI de la sesión
   * anterior se queda en el store (el sidebar móvil abierto, los toasts
   * que aún nadie ha cerrado) y se lo encuentra el usuario siguiente en
   * la misma pestaña. Con el logout por router (sin recargar la página)
   * el store **sobrevive**, así que hay que limpiarlo a mano.
   *
   * OJO: el toast de «Sesión cerrada» se empuja **después** de este
   * ``reset()``, que es lo que vacía los toasts.
   */
  function reset(): void {
    sidebarOpen.value = false
    toasts.value = []
  }

  return {
    sidebarOpen, toasts,
    toggleSidebar, closeSidebar, pushToast, dismissToast, reset,
  }
})