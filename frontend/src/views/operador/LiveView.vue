<script setup lang="ts">
/**
 * Vista de operador en vivo: lista de tickets activos de la sucursal
 * seleccionada (polling 5 s). El alta manual vive en su vista dedicada
 * ``/operador/alta-manual`` (sprint Alta Manual del Operador 2026-06-30).
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string }
interface Ticket {
  id: number
  status: string
  entry_at: string
  parking_id: number
  parking_space_id: number | null
  origin: string
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const selectedId = ref<number | null>(null)
const tickets = ref<Ticket[]>([])
const loading = ref(true)

let pollHandle: number | null = null

async function load(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (!selectedId.value && data.length) {
      selectedId.value = data[0].id
    }
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
}

async function refreshTickets(): Promise<void> {
  if (!selectedId.value) return
  try {
    const { data } = await http.get<Ticket[]>('/tickets', {
      params: { parking_id: selectedId.value, only_active: true },
    })
    tickets.value = data
  } catch {
    /* silencioso: el polling reintentará */
  }
}

onMounted(async () => {
  await load()
  await refreshTickets()
  pollHandle = window.setInterval(refreshTickets, 5000)
})

onBeforeUnmount(() => {
  if (pollHandle !== null) window.clearInterval(pollHandle)
})
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Operador · En vivo</h1>
        <p class="mt-1 text-sm text-slate-500 flex items-center gap-3">
          <span class="pulse-dot text-emerald-700">En vivo</span>
          <span>· Refresco automático cada 5 s</span>
        </p>
      </div>
      <select v-model.number="selectedId" class="input w-auto"
        @change="refreshTickets">
        <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Tickets activos en esta sucursal</h2>
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-3 py-2 font-medium">#</th>
              <th class="px-3 py-2 font-medium">Sucursal</th>
              <th class="px-3 py-2 font-medium">Plaza</th>
              <th class="px-3 py-2 font-medium">Entrada</th>
              <th class="px-3 py-2 font-medium">Origen</th>
              <th class="px-3 py-2 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="t in tickets" :key="t.id">
              <td class="px-3 py-2 font-mono text-xs">#{{ t.id }}</td>
              <td class="px-3 py-2">{{ t.parking_id }}</td>
              <td class="px-3 py-2">{{ t.parking_space_id ?? '—' }}</td>
              <td class="px-3 py-2">{{ new Date(t.entry_at).toLocaleString('es-ES') }}</td>
              <td class="px-3 py-2">
                <span
                  class="inline-block px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="t.origin === 'automatic'
                    ? 'bg-slate-100 text-slate-600'
                    : 'bg-amber-100 text-amber-800'"
                >
                  {{ t.origin === 'manual_entry' ? 'manual entrada'
                    : t.origin === 'manual_exit' ? 'manual salida'
                    : 'automático' }}
                </span>
              </td>
              <td class="px-3 py-2">{{ t.status }}</td>
            </tr>
            <tr v-if="!tickets.length">
              <td colspan="6" class="px-3 py-6 text-center text-slate-500">
                Sin tickets activos.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="bg-white rounded-xl shadow-card p-5 flex flex-col">
        <h2 class="font-semibold mb-2">¿Cámara caída u OCR fallido?</h2>
        <p class="text-sm text-slate-500 mb-4">
          Registra la entrada o salida a mano desde el formulario dedicado.
          El sistema auditará quién, cuándo y por qué.
        </p>
        <RouterLink
          to="/operador/alta-manual"
          class="btn-primary text-center mt-auto"
        >
          Ir a Alta manual
        </RouterLink>
      </div>
    </div>
  </AppLayout>
</template>