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

  return { sidebarOpen, toasts, toggleSidebar, closeSidebar, pushToast, dismissToast }
})