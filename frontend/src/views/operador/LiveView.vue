<script setup lang="ts">
/**
 * Vista de operador en vivo: lista de tickets activos + acciones
 * rápidas (alta manual, marcar plaza, reportar robo, rehabilitar).
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import IncidentModal from '@/views/operador/IncidentModal.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'
import { useParkingEvents } from '@/composables/useParkingEvents'

interface Parking { id: number; name: string }
interface Space { id: number; parking_id: number; lane: string; number: string; is_active?: boolean; is_broken?: boolean }
interface Ticket {
  id: number
  status: string
  entry_at: string
  parking_id: number
  parking_space_id: number | null
  origin: string
}
interface AlertItem {
  id: number
  type: string
  severity: string
  message: string
  context?: Record<string, unknown> | null
  created_at: string
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const spaces = ref<Space[]>([])
const selectedId = ref<number | null>(null)
const tickets = ref<Ticket[]>([])
const recentAlerts = ref<AlertItem[]>([])
const loading = ref(true)
const incidentOpen = ref(false)
const incidentTab = ref<'broken' | 'robery' | 'unbroken'>('broken')

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

async function loadContext(parkingId: number): Promise<void> {
  try {
    const { data } = await http.get<Space[]>(`/parkings/${parkingId}/spaces`)
    spaces.value = data
  } catch {
    // T-111: un fallo de la API se ve IGUAL que "no hay plazas". Con la
    // tabla vacia y sin aviso, el operador no puede distinguir un fallo
    // del backend de un parking sin datos.
    spaces.value = []
    ui.pushToast('error', 'No se han podido cargar las plazas')
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
    // T-111: idem: un 401/500 aqui era indistinguible de "no hay
    // tickets activos".
    ui.pushToast('error', 'No se han podido cargar los tickets')
  }
}

async function refreshRecentAlerts(): Promise<void> {
  if (!selectedId.value) return
  try {
    const { data } = await http.get<AlertItem[]>(
      `/parkings/${selectedId.value}/alerts?type=space_broken&limit=10`,
    )
    const spaceAlerts = data ?? []
    try {
      const r = await http.get<AlertItem[]>(
        `/parkings/${selectedId.value}/alerts?type=robery_reported&limit=10`,
      )
      const roberyAlerts = r.data ?? []
      const merged = [...spaceAlerts, ...roberyAlerts]
      merged.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      recentAlerts.value = merged.slice(0, 5)
    } catch {
      recentAlerts.value = spaceAlerts.slice(0, 5)
    }
  } catch {
    recentAlerts.value = []
    // T-111: se avisa del fallo (antes era una lista vacia sin más).
    ui.pushToast('error', 'No se han podido cargar las alertas')
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([refreshTickets(), refreshRecentAlerts()])
}

// ── Eventos en vivo (SSE) ────────────────────────────────────────────
// T-17: la vista en vivo del operador se suscribe al bus de eventos de
// la sucursal. El operador ya no necesita recargar (F5) para ver un
// ticket nuevo, un cierre de ticket o una plaza averiada.
//
// Qué reacciona a cada tipo de evento:
//   ticket_created / ticket_closed / ticket_cancelled → recargar la tabla
//     de tickets activos.
//   space_broken_changed → recargar tickets, alertas (incidentes) y la
//     lista de plazas que usa el modal de incidentes.
//
// Qué NO reacciona (y por qué):
//   camera_health_changed → esta vista no muestra cámaras ni su salud.
//   Cualquier otro tipo futuro → se ignora sin romper la suscripción.
const { connected: liveConnected, reconnecting: liveReconnecting } = useParkingEvents(
  selectedId,
  (ev) => {
    switch (ev.type) {
      case 'ticket_created':
      case 'ticket_closed':
      case 'ticket_cancelled':
        void refreshTickets()
        break
      case 'space_broken_changed':
        void refreshTickets()
        void refreshRecentAlerts()
        if (selectedId.value) void loadContext(selectedId.value)
        break
      default:
        break
    }
  },
)

function openIncident(tab: 'broken' | 'robery' | 'unbroken'): void {
  incidentTab.value = tab
  incidentOpen.value = true
}

async function onIncidentSuccess(): Promise<void> {
  await refreshAll()
}

onMounted(async () => {
  await load()
  if (selectedId.value) await loadContext(selectedId.value)
  await refreshAll()
  // Red de seguridad: si el SSE no conecta (firewall corporativo o el
  // navegador no puede mantener el stream), seguimos refrescando cada
  // 30 s. Con SSE activo la latencia real es <1 s.
  pollHandle = window.setInterval(refreshAll, 30000)
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
          <span :class="['pulse-dot', liveConnected ? 'text-emerald-700' : 'text-slate-500']">
            {{ liveConnected ? 'En vivo'
              : liveReconnecting ? 'Reconectando…' : 'Sin conexión SSE' }}
          </span>
          <span>· Actualización en vivo por SSE (fallback 30 s)</span>
        </p>
      </div>
      <select v-model.number="selectedId" class="input w-auto"
        @change="selectedId && (loadContext(selectedId), refreshAll())">
        <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 space-y-6">
        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Tickets activos en esta sucursal</h2>
          <div class="overflow-x-auto min-w-0">
            <table class="w-full text-sm min-w-max">
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
        </div>

        <div v-if="recentAlerts.length" class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Mis últimos incidentes</h2>
          <ul class="divide-y divide-slate-100">
            <li
              v-for="a in recentAlerts"
              :key="a.id"
              class="py-2 flex items-start gap-3 text-sm"
            >
              <span
                class="inline-block mt-0.5 w-2 h-2 rounded-full flex-shrink-0"
                :class="a.severity === 'critical' ? 'bg-rose-600'
                  : a.severity === 'warn' ? 'bg-amber-500'
                  : 'bg-slate-400'"
              />
              <div class="flex-1">
                <div class="font-medium text-slate-900">
                  {{ a.type === 'space_broken'
                    ? (a.context?.kind === 'space_unbroken'
                      ? 'Plaza rehabilitada'
                      : 'Plaza averiada')
                    : 'Reporte de robo' }}
                  · <span class="text-xs text-slate-500">#{{ a.id }}</span>
                </div>
                <div class="text-xs text-slate-500">
                  {{ new Date(a.created_at).toLocaleString('es-ES') }}
                </div>
              </div>
            </li>
          </ul>
        </div>
      </div>

      <div class="space-y-3">
        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Acciones rápidas</h2>
          <div class="space-y-2">
            <RouterLink
              to="/operador/alta-manual"
              class="btn-primary block text-center"
            >
              📝 Alta manual
            </RouterLink>
            <button
              type="button"
              class="w-full text-left px-3 py-2 rounded-md border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 text-sm font-medium"
              @click="openIncident('broken')"
            >
              🛠 Marcar plaza como averiada
            </button>
            <button
              type="button"
              class="w-full text-left px-3 py-2 rounded-md border border-rose-300 bg-rose-50 text-rose-900 hover:bg-rose-100 text-sm font-medium"
              @click="openIncident('robery')"
            >
              🚨 Reportar robo / incidente
            </button>
            <button
              type="button"
              class="w-full text-left px-3 py-2 rounded-md border border-emerald-300 bg-emerald-50 text-emerald-900 hover:bg-emerald-100 text-sm font-medium"
              @click="openIncident('unbroken')"
            >
              ✅ Rehabilitar plaza
            </button>
          </div>
        </div>
      </div>
    </div>

    <IncidentModal
      :open="incidentOpen"
      :parking-id="selectedId ?? 0"
      :spaces="spaces"
      @close="incidentOpen = false"
      @success="onIncidentSuccess"
    />
  </AppLayout>
</template>