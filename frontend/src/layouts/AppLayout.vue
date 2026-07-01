<script setup lang="ts">
/**
 * Layout con sidebar reactivo al rol + toast container.
 * En móvil el sidebar se colapsa por defecto y se abre con el botón hamburguesa.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

interface NavItem { name: string; label: string; to: string }

const NAV_BY_ROLE: Record<string, NavItem[]> = {
  admin: [
    { name: 'dashboard', label: 'Dashboard', to: '/dashboard' },
    { name: 'admin-parkings', label: 'Sucursales', to: '/admin/parkings' },
    { name: 'admin-users', label: 'Usuarios', to: '/admin/users' },
    { name: 'admin-tariffs', label: 'Tarifas', to: '/admin/tariffs' },
    { name: 'gestor-map', label: 'Mapa', to: '/mapa' },
    { name: 'gestor-cameras', label: 'Cámaras', to: '/cameras' },
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
  ],
  gestor: [
    { name: 'gestor-map', label: 'Mapa', to: '/mapa' },
    { name: 'gestor-cameras', label: 'Cámaras', to: '/cameras' },
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
  ],
  operador: [
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
  ],
  cliente: [
    { name: 'cliente-tickets', label: 'Mis tickets', to: '/mis-tickets' },
  ],
}

const nav = computed<NavItem[]>(() => (auth.role ? NAV_BY_ROLE[auth.role] ?? [] : []))

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrador',
  gestor: 'Gestor de parking',
  operador: 'Operador',
  cliente: 'Cliente',
}

async function onLogout(): Promise<void> {
  await auth.logout()
  ui.pushToast('success', 'Sesión cerrada')
  location.assign('/login')
}
</script>

<template>
  <div class="min-h-screen flex bg-slate-100">
    <div
      v-if="ui.sidebarOpen"
      class="fixed inset-0 bg-slate-900/40 z-30 lg:hidden"
      @click="ui.closeSidebar()"
    />

    <aside
      :class="[
        'fixed lg:static inset-y-0 left-0 z-40 w-60 bg-slate-900 text-slate-200 flex flex-col transform transition-transform duration-200',
        ui.sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      ]"
    >
      <div class="px-4 py-4 flex items-center justify-center border-b border-slate-800">
        <img
          src="/logo-solidapp.png?v=2"
          alt="solidAPP"
          class="max-h-14 max-w-full bg-white rounded"
        />
      </div>

      <nav class="flex-1 px-3 py-4 space-y-1 text-sm overflow-y-auto">
        <RouterLink
          v-for="item in nav"
          :key="item.name"
          :to="item.to"
          @click="ui.closeSidebar()"
          class="block px-3 py-2 rounded-md hover:bg-slate-800 transition-colors"
          active-class="bg-slate-800 text-white"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="px-5 py-4 border-t border-slate-800 text-xs text-slate-400">
        <div class="font-medium text-slate-200">{{ auth.user?.full_name ?? auth.email ?? 'Sin sesión' }}</div>
        <div>{{ auth.role ? ROLE_LABEL[auth.role] : '' }}</div>
        <button
          type="button"
          class="block mt-2 text-blue-400 hover:underline"
          @click="onLogout"
        >
          Cerrar sesión
        </button>
      </div>
    </aside>

    <div class="flex-1 flex flex-col min-w-0">
      <header class="lg:hidden bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
        <button
          type="button"
          class="text-slate-700 hover:text-slate-900"
          @click="ui.toggleSidebar()"
          aria-label="Abrir menú"
        >
          <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span class="w-6" />
        <span class="w-6" />
      </header>

      <main class="flex-1 p-6 lg:p-8">
        <slot />
      </main>
    </div>

    <div class="fixed top-4 right-4 z-50 space-y-2">
      <div
        v-for="t in ui.toasts"
        :key="t.id"
        :class="[
          'rounded-lg shadow-card px-4 py-3 text-sm max-w-sm bg-white border cursor-pointer',
          t.type === 'success' && 'border-emerald-300 text-emerald-800',
          t.type === 'warn' && 'border-amber-300 text-amber-800',
          t.type === 'error' && 'border-rose-300 text-rose-800',
          t.type === 'info' && 'border-slate-300 text-slate-800',
        ]"
        @click="ui.dismissToast(t.id)"
      >
        {{ t.message }}
      </div>
    </div>
  </div>
</template>