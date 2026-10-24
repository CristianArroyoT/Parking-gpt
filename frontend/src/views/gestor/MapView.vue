<script setup lang="ts">
/**
 * Mapa de plazas con refresco en vivo (SSE + fallback polling).
 *
 * Sprint O2 (2026-07-06): la versión previa hacía ``setInterval(5s)``.
 * Ahora consume el stream SSE ``GET /api/v1/parkings/{id}/events``
 * (latencia <1 s para cambios de plaza) y mantiene un polling de 30 s
 * como red de seguridad para entornos donde el SSE no conecta.
 *
 * También arregla un bug latente: las plazas con ``is_broken=true``
 * se mostraban como 'libre' aunque el backend ya las marcaba como
 * averiadas. Ahora ``stateFor()`` devuelve 'alerta' antes que
 * 'ocupada' y el chip rosa ``plaza-alerta`` se renderiza.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'
import { useParkingEvents } from '@/composables/useParkingEvents'

interface Parking { id: number; code: string; name: string; address: string; city: string }
interface ParkingSpace {
  id: number
  parking_id: number
  lane: string
  number: string
  is_active: boolean
  is_broken: boolean
}
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

// Sprint O2: suscripción SSE reactiva al parking actual. El composable
// (T-17) se encarga de re-suscribir cuando el gestor cambia de sucursal
// en el <select> y de cerrar el stream al desmontar la vista.
const { connected: liveConnected } = useParkingEvents(selectedId, (ev) => {
  // Cualquier cambio relevante → refetch completo. El servidor es la
  // fuente de verdad y MapView es pequeño (≈N plazas, M tickets
  // activos), así que un GET entero es más simple que mantener
  // estado derivado.
  if (
    ev.type === 'ticket_created'
    || ev.type === 'ticket_closed'
    || ev.type === 'ticket_cancelled'
    || ev.type === 'space_broken_changed'
  ) {
    tick()
  }
  // camera_health_changed → no afecta al mapa visual de plazas.
})

//: T-162 (2026-10-24): se pone a ``true`` al desmontar la vista. El
//: polling se crea despues de unos ``await``, asi que sin este flag un
//: intervalo podia crearse DESPUES del desmontaje y no borrarse nunca.
let desmontado = false

onMounted(async () => {
  try {
    await loadParkings()
    if (selectedId.value) {
      await loadSnapshot(selectedId.value)
    }
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
  // Fallback defensivo: si el SSE no conecta (firewall corporativo),
  // seguimos refrescando cada 30 s. La latencia real es <1 s cuando SSE
  // funciona; 30 s es el suelo en caso de fallback.
  // T-162 (2026-10-24): el intervalo se crea DESPUES de los `await`. Si
  // el gestor sale de la vista mientras carga, `onBeforeUnmount` ve
  // `pollHandle === null` (todavia no existe) y el intervalo se crea
  // DESPUES del desmontaje: nunca se borra y sigue pidiendo datos a una
  // vista que ya no esta. Con este flag, si nos desmontan mientras
  // esperamos, no se crea.
  if (desmontado) return
  pollHandle = window.setInterval(tick, 30000)
})

onBeforeUnmount(() => {
  desmontado = true
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
  // Sprint O2 (bug-fix): el orden importa. Averiada gana sobre libre/
  // ocupada porque el operador debe ver claramente que NO se asignan
  // tickets a esa plaza aunque esté libre o tenga un ticket residual.
  if (!space.is_active) return 'inactiva'
  if (space.is_broken) return 'alerta'
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

function labelFor(state: ReturnType<typeof stateFor>): string {
  switch (state) {
    case 'libre':    return 'Libre'
    case 'ocupada':  return 'Ocupada'
    case 'alerta':   return 'Averiada'
    case 'inactiva': return 'Inactiva'
  }
}
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Mapa de sucursal</h1>
        <p class="mt-1 text-sm text-slate-500 flex items-center gap-3">
          <span :class="['pulse-dot', liveConnected ? 'text-emerald-700' : 'text-slate-500']">
            {{ liveConnected ? 'En vivo' : 'Sin conexión SSE' }}
          </span>
          <span>· Refresco automático (SSE · fallback 30 s)</span>
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
              <div class="flex justify-between">
                <span class="text-slate-500">Estado</span>
                <span>{{ labelFor(stateFor(selected)) }}</span>
              </div>
              <div class="flex justify-between"><span class="text-slate-500">Calle</span><span>{{ selected.lane }}</span></div>
            </div>
            <p
              v-if="stateFor(selected) === 'alerta'"
              class="mt-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2"
            >
              Plaza averiada: no se asignan tickets hasta rehabilitarla.
            </p>
          </div>
          <p v-else class="mt-2 text-sm text-slate-500">Selecciona una plaza para ver detalle.</p>
        </div>
      </aside>
    </div>
  </AppLayout>
</template>