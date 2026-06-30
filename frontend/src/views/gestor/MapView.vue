<script setup lang="ts">
/**
 * Mapa de plazas con polling cada 5 s.
 * El estado ocupado/libre se calcula cruzando plazas activas con tickets
 * activos. En Fase 2 el worker OCR actualizará plazas en tiempo real.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; code: string; name: string; address: string; city: string }
interface ParkingSpace { id: number; parking_id: number; lane: string; number: string; is_active: boolean }
interface Ticket { id: number; parking_id: number; parking_space_id: number | null; status: string }

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const selectedId = ref<number | null>(null)
const spaces = ref<ParkingSpace[]>([])
const tickets = ref<Ticket[]>([])
const loading = ref(true)
const selected = ref<ParkingSpace | null>(null)

let pollHandle: number | null = null

async function loadParkings(): Promise<void> {
  const { data } = await http.get<Parking[]>('/parkings')
  parkings.value = data
  if (!selectedId.value && data.length) selectedId.value = data[0].id
}

async function loadSnapshot(parkingId: number): Promise<void> {
  const [s, t] = await Promise.all([
    http.get<ParkingSpace[]>(`/parkings/${parkingId}/spaces`),
    http.get<Ticket[]>('/tickets', { params: { parking_id: parkingId, only_active: true } }),
  ])
  spaces.value = s.data
  tickets.value = t.data
}

async function tick(): Promise<void> {
  if (!selectedId.value) return
  try {
    await loadSnapshot(selectedId.value)
  } catch {
    ui.pushToast('error', 'Error al refrescar el mapa')
  }
}

onMounted(async () => {
  try {
    await loadParkings()
    if (selectedId.value) await loadSnapshot(selectedId.value)
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
  pollHandle = window.setInterval(tick, 5000)
})

onBeforeUnmount(() => {
  if (pollHandle !== null) window.clearInterval(pollHandle)
})

const LANES = ['A', 'B', 'C', 'D'] as const

const grouped = computed(() => {
  const map = new Map<string, ParkingSpace[]>()
  for (const lane of LANES) map.set(lane, [])
  for (const s of spaces.value) {
    if (!s.is_active) continue
    const arr = map.get(s.lane)
    if (arr) arr.push(s)
  }
  return map
})

const occupied = computed(() => new Set(tickets.value
  .filter((t) => t.status === 'activo' && t.parking_space_id !== null)
  .map((t) => t.parking_space_id as number),
))

function stateFor(space: ParkingSpace): 'libre' | 'ocupada' | 'alerta' | 'inactiva' {
  if (!space.is_active) return 'inactiva'
  if (occupied.value.has(space.id)) return 'ocupada'
  return 'libre'
}

function classFor(space: ParkingSpace): string {
  switch (stateFor(space)) {
    case 'libre':    return 'plaza-libre'
    case 'ocupada':  return 'plaza-ocupada'
    case 'alerta':   return 'plaza-alerta'
    default:         return 'plaza-inactiva'
  }
}
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Mapa de sucursal</h1>
        <p class="mt-1 text-sm text-slate-500 flex items-center gap-3">
          <span class="pulse-dot text-emerald-700">En vivo</span>
          <span>· Actualización cada 5 s</span>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <select v-model.number="selectedId" class="input w-auto" @change="tick">
          <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button class="btn-secondary" @click="tick">Refrescar</button>
      </div>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando mapa…</div>

    <div v-else class="grid grid-cols-1 xl:grid-cols-4 gap-6">
      <div class="xl:col-span-3 bg-white rounded-xl shadow-card p-5">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div v-for="lane in LANES" :key="lane"
            class="border border-slate-200 rounded-lg p-4 bg-slate-50">
            <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Calle {{ lane }}
            </div>
            <div class="grid grid-cols-4 gap-2">
              <button v-for="space in grouped.get(lane)" :key="space.id"
                type="button"
                :class="[classFor(space), selected?.id === space.id && 'selected']"
                @click="selected = space"
              >{{ space.number }}</button>
            </div>
          </div>
        </div>
      </div>

      <aside class="space-y-4">
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">Plaza seleccionada</div>
          <div v-if="selected" class="mt-2">
            <div class="text-3xl font-semibold tracking-tight">{{ selected.number }}</div>
            <div class="mt-2 text-sm space-y-1">
              <div class="flex justify-between"><span class="text-slate-500">Estado</span><span>{{ stateFor(selected) }}</span></div>
              <div class="flex justify-between"><span class="text-slate-500">Calle</span><span>{{ selected.lane }}</span></div>
            </div>
          </div>
          <p v-else class="mt-2 text-sm text-slate-500">Selecciona una plaza para ver detalle.</p>
        </div>
      </aside>
    </div>
  </AppLayout>
</template>