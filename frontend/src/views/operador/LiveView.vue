<script setup lang="ts">
/**
 * Vista de operador en vivo. Muestra los tickets activos y permite
 * registrar entradas manuales cuando la cámara cae o el OCR falla.
 */
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string }
interface Ticket { id: number; status: string; entry_at: string; parking_id: number }

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const selectedId = ref<number | null>(null)
const tickets = ref<Ticket[]>([])
const loading = ref(true)

const manual = reactive({
  parking_id: 0,
  vehicle_id: 0,
  parking_space_id: null as number | null,
  entry_at: new Date().toISOString().slice(0, 16),
})

let pollHandle: number | null = null

async function load(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (!selectedId.value && data.length) {
      selectedId.value = data[0].id
      manual.parking_id = data[0].id
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

async function submitManual(): Promise<void> {
  try {
    await http.post('/tickets', {
      ...manual,
      entry_at: new Date(manual.entry_at).toISOString(),
    })
    ui.pushToast('success', 'Entrada manual registrada')
    await refreshTickets()
  } catch {
    ui.pushToast('error', 'No se pudo registrar la entrada')
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
        @change="manual.parking_id = selectedId!; refreshTickets()">
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
              <th class="px-3 py-2 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="t in tickets" :key="t.id">
              <td class="px-3 py-2 font-mono text-xs">#{{ t.id }}</td>
              <td class="px-3 py-2">{{ t.parking_id }}</td>
              <td class="px-3 py-2">{{ t.parking_space_id ?? '—' }}</td>
              <td class="px-3 py-2">{{ new Date(t.entry_at).toLocaleString('es-ES') }}</td>
              <td class="px-3 py-2">{{ t.status }}</td>
            </tr>
            <tr v-if="!tickets.length">
              <td colspan="5" class="px-3 py-6 text-center text-slate-500">Sin tickets activos.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Alta manual</h2>
        <form class="space-y-3" @submit.prevent="submitManual">
          <div>
            <label class="block text-xs font-medium text-slate-700">Vehículo (ID)</label>
            <input v-model.number="manual.vehicle_id" type="number" required min="1" class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Plaza (ID, opcional)</label>
            <input v-model.number="manual.parking_space_id" type="number" min="1" class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Hora de entrada</label>
            <input v-model="manual.entry_at" type="datetime-local" required class="input" />
          </div>
          <p class="text-xs text-slate-500">
            Motivo: cámara caída / OCR fallido / otro. El audit log del backend
            registra la acción con motivo en el payload.
          </p>
          <button type="submit" class="btn-primary w-full">Registrar entrada</button>
        </form>
      </div>
    </div>
  </AppLayout>
</template>