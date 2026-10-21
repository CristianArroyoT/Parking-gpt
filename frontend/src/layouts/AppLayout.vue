<script setup lang="ts">
/**
 * Layout con sidebar reactivo al rol + toast container.
 * En móvil el sidebar se colapsa por defecto y se abre con el botón hamburguesa.
 *
 * Sprint R5-sidebar (2026-07-06): el bloque inferior del sidebar expone
 * un dropdown clickable en el nombre del usuario. Al hacer click se
 * despliega un menú con "Cambiar contraseña" (abre modal) y "Cerrar
 * sesión". El modal usa Teleport a ``body`` para evitar quedar
 * atrapado dentro del ``overflow-y-auto`` del sidebar.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { isPwaMode } from '@/pwa/mode'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

interface NavItem { name: string; label: string; to: string }

const NAV_BY_ROLE: Record<string, NavItem[]> = {
  // Sprint R5-sidebar (2026-07-06): orden unificado para todos los
  // perfiles. El usuario dictó esta secuencia canónica:
  //   dashboard → en vivo → alta manual → cámaras → sucursales → mapa
  //   → tarifas → costes → usuarios
  // Cada rol ve sólo los items que le corresponden, pero respetando
  // siempre este orden relativo.
  //
  // Nota: ``Reportería`` no aparece en la lista canónica. Se mantiene
  // al final para no perder acceso desde el sidebar (sprint UI
  // Costes + Reportería, 2026-07-06). Si el producto decide ocultarla,
  // mover a /admin/costes o /dashboard es trivial.
  admin: [
    { name: 'dashboard', label: 'Dashboard', to: '/dashboard' },
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
    { name: 'gestor-cameras', label: 'Cámaras', to: '/cameras' },
    { name: 'admin-parkings', label: 'Sucursales', to: '/admin/parkings' },
    { name: 'gestor-map', label: 'Mapa', to: '/mapa' },
    { name: 'admin-tariffs', label: 'Tarifas', to: '/admin/tariffs' },
    // T-18 (2026-10-21): catálogo de planes y suscripciones. Va junto a
    // "Tarifas" porque ambos son los precios del producto.
    { name: 'admin-planes', label: 'Planes', to: '/admin/planes' },
    { name: 'admin-costs', label: 'Costes', to: '/admin/costs' },
    { name: 'admin-users', label: 'Usuarios', to: '/admin/users' },
    { name: 'admin-reports', label: 'Reportería', to: '/admin/reports' },
  ],
  gestor: [
    { name: 'gestor-dashboard', label: 'Dashboard', to: '/dashboard/gestor' },
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
    { name: 'gestor-cameras', label: 'Cámaras', to: '/cameras' },
    { name: 'gestor-map', label: 'Mapa', to: '/mapa' },
    // T-20 (2026-10-21): log de entradas/salidas, alertas activas y
    // operadores. Van detrás de "Mapa" porque no forman parte de la
    // secuencia canónica que dictó el usuario (dashboard → en vivo → alta
    // manual → cámaras → sucursales → mapa → tarifas → costes → usuarios).
    { name: 'gestor-movimientos', label: 'Entradas/Salidas', to: '/gestor/movimientos' },
    { name: 'gestor-alertas', label: 'Alertas', to: '/gestor/alertas' },
    { name: 'gestor-operadores', label: 'Operadores', to: '/gestor/operadores' },
  ],
  operador: [
    { name: 'operador-live', label: 'En vivo', to: '/vivo' },
    { name: 'operador-manual', label: 'Alta manual', to: '/operador/alta-manual' },
  ],
  cliente: [
    // Cliente no aparece en la lista canónica del usuario: conserva
    // su única entrada propia.
    { name: 'cliente-tickets', label: 'Mis tickets', to: '/mis-tickets' },
    // T-19 (2026-10-21): gestión de vehículos y perfil. "Mi perfil" va
    // al final porque es una acción secundaria frente a las operativas.
    { name: 'cliente-vehiculos', label: 'Mis vehículos', to: '/mis-vehiculos' },
    // T-18 (2026-10-21): plan, alta/vencimiento, % de descuento y
    // próximo cobro (contable: decisión D2, sin pasarela de pago).
    { name: 'cliente-plan', label: 'Mi plan', to: '/mi-plan' },
    // T-24 (2026-10-21): plaza asignada y pagos pendientes de la PWA
    // instalable del cliente.
    { name: 'cliente-plazas', label: 'Mi plaza', to: '/mi-plaza' },
    { name: 'cliente-pagos', label: 'Pagos', to: '/pagos' },
    { name: 'cliente-perfil', label: 'Mi perfil', to: '/mi-perfil' },
  ],
}

const nav = computed<NavItem[]>(() => {
  const items = auth.role ? NAV_BY_ROLE[auth.role] ?? [] : []
  // T-24 (2026-10-21): la PWA instalada es **sólo para el cliente**
  // (decisión D4), así que dentro de ella el menú se reduce a las
  // entradas de cliente aunque el usuario tenga otro rol.
  return isPwaMode() ? items.filter((i) => i.name.startsWith('cliente-')) : items
})

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrador',
  gestor: 'Gestor de parking',
  operador: 'Operador',
  cliente: 'Cliente',
}

// ── Dropdown + modal cambio de contraseña (Sprint R5-sidebar) ─────────

const menuOpen = ref(false)
const pwdModalOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)

// Form de cambio de clave. ``current`` siempre requerida; ``next`` y
// ``confirm`` deben coincidir y tener >= 8 chars (validación backend).
const pwdForm = ref({ current: '', next: '', confirm: '' })
const pwdLoading = ref(false)
const pwdError = ref<string | null>(null)

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value
}

async function onLogout(): Promise<void> {
  menuOpen.value = false
  pwdModalOpen.value = false
  await auth.logout()
  ui.pushToast('success', 'Sesión cerrada')
  location.assign('/login')
}

function openChangePassword(): void {
  menuOpen.value = false
  pwdForm.value = { current: '', next: '', confirm: '' }
  pwdError.value = null
  pwdModalOpen.value = true
}

function closePwdModal(): void {
  if (pwdLoading.value) return
  pwdModalOpen.value = false
}

async function onSubmitPassword(): Promise<void> {
  pwdError.value = null
  if (!pwdForm.value.current || !pwdForm.value.next || !pwdForm.value.confirm) {
    pwdError.value = 'Rellena todos los campos.'
    return
  }
  if (pwdForm.value.next !== pwdForm.value.confirm) {
    pwdError.value = 'La nueva contraseña no coincide.'
    return
  }
  if (pwdForm.value.next.length < 8) {
    pwdError.value = 'La nueva contraseña debe tener al menos 8 caracteres.'
    return
  }
  pwdLoading.value = true
  try {
    await auth.changeMyPassword(pwdForm.value.current, pwdForm.value.next)
    pwdModalOpen.value = false
    ui.pushToast('success', 'Contraseña actualizada')
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'No se pudo cambiar la contraseña'
    pwdError.value = msg
  } finally {
    pwdLoading.value = false
  }
}

// Click-outside para cerrar el menú. Usamos ``pointerdown`` para que se
// cierre también si el usuario hace click en cualquier sitio fuera (no
// sólo ``click``), y así evitar el flash del menú cerrando tras haber
// abierto otro elemento.
function handleDocPointerDown(ev: PointerEvent): void {
  if (!menuOpen.value) return
  const target = ev.target as Node | null
  if (menuRef.value && target && !menuRef.value.contains(target)) {
    menuOpen.value = false
  }
}

onMounted(() => document.addEventListener('pointerdown', handleDocPointerDown))
onBeforeUnmount(() => document.removeEventListener('pointerdown', handleDocPointerDown))
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

      <!-- Sprint R5-sidebar: bloque usuario con dropdown -->
      <div ref="menuRef" class="px-5 py-4 border-t border-slate-800 text-xs text-slate-400 relative">
        <button
          type="button"
          class="w-full text-left flex items-center justify-between gap-2 hover:text-slate-100"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click="toggleMenu"
        >
          <span class="min-w-0">
            <span class="block font-medium text-slate-200 truncate">
              {{ auth.user?.full_name ?? auth.email ?? 'Sin sesión' }}
            </span>
            <span class="block">{{ auth.role ? ROLE_LABEL[auth.role] : '' }}</span>
          </span>
          <svg
            :class="['h-4 w-4 transition-transform', menuOpen && 'rotate-180']"
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
          </svg>
        </button>

        <div
          v-if="menuOpen"
          role="menu"
          class="absolute left-3 right-3 bottom-[calc(100%-0.5rem)] z-50 bg-white text-slate-800 rounded-md shadow-lg ring-1 ring-slate-200 py-1 text-sm"
        >
          <button
            type="button"
            role="menuitem"
            class="w-full text-left px-4 py-2 hover:bg-slate-100 flex items-center gap-2"
            @click="openChangePassword"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 11c2.21 0 4-1.79 4-4S14.21 3 12 3 8 4.79 8 7s1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v3h16v-3c0-2.66-5.33-4-8-4z" />
            </svg>
            Cambiar contraseña
          </button>
          <button
            type="button"
            role="menuitem"
            class="w-full text-left px-4 py-2 hover:bg-slate-100 text-rose-600 flex items-center gap-2"
            @click="onLogout"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Cerrar sesión
          </button>
        </div>
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

    <!-- Modal de cambio de contraseña. Teleport a body para escapar el
         overflow del sidebar. -->
    <Teleport to="body">
      <div
        v-if="pwdModalOpen"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/50"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pwd-modal-title"
        @keydown.esc="closePwdModal"
        @click.self="closePwdModal"
      >
        <div class="w-full max-w-md bg-white rounded-lg shadow-xl">
          <div class="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
            <h2 id="pwd-modal-title" class="text-base font-semibold text-slate-900">
              Cambiar contraseña
            </h2>
            <button
              type="button"
              class="text-slate-400 hover:text-slate-700"
              aria-label="Cerrar"
              @click="closePwdModal"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <form class="px-6 py-5 space-y-4" @submit.prevent="onSubmitPassword">
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="pwd-current">
                Contraseña actual
              </label>
              <input
                id="pwd-current"
                v-model="pwdForm.current"
                type="password"
                autocomplete="current-password"
                required
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="pwd-next">
                Nueva contraseña
              </label>
              <input
                id="pwd-next"
                v-model="pwdForm.next"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
              <p class="mt-1 text-xs text-slate-500">Mínimo 8 caracteres.</p>
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="pwd-confirm">
                Confirmar nueva contraseña
              </label>
              <input
                id="pwd-confirm"
                v-model="pwdForm.confirm"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
            </div>

            <p
              v-if="pwdError"
              class="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
              role="alert"
            >
              {{ pwdError }}
            </p>

            <div class="flex justify-end gap-2 pt-2">
              <button
                type="button"
                class="px-3 py-2 text-sm rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="pwdLoading"
                @click="closePwdModal"
              >
                Cancelar
              </button>
              <button
                type="submit"
                class="px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                :disabled="pwdLoading"
              >
                {{ pwdLoading ? 'Guardando…' : 'Guardar' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </div>
</template>