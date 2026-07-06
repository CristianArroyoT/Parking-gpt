<script setup lang="ts">
/**
 * Dashboard del gestor de parking (Sprint Fase 4, 2026-07-01).
 *
 * Antes el gestor sólo tenía acceso al mapa y a las cámaras. Ahora
 * tiene una vista agregada con:
 *   - KPIs de su parking (parkings con memberships del gestor).
 *   - Estado de las cámaras (último heartbeat).
 *   - Tickets en las últimas 24 h.
 *
 * Endpoints consumidos:
 *   - GET /parkings                              (lista de sucursales).
 *   - GET /parkings/{id}/cameras                 (cámaras del parking).
 *   - GET /parkings/{id}/tickets/summary         (KPIs 24 h — Fase 4-parte-2).
 *
 * Patrón idéntico al ``admin/DashboardView.vue``: AppLayout + http +
 * useUiStore, sin estado global de Pinia.
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http, getTicketSummary, type TicketSummary } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string; code: string; is_active: boolean }
type CameraKind = 'surveillance' | 'gate'
interface Camera {
  id: number; parking_id: number; code: string; name: string
  is_active: boolean; kind: CameraKind
  last_heartbeat_at: string | null
  last_heartbeat_ok: boolean | null
}

const ui = useUiStore()

const parkings = ref<Parking[]>([])
const cameras = ref<Camera[]>([])
const summary = ref<TicketSummary | null>(null)
const loading = ref(true)

const selectedParkingId = ref<number | null>(null)
const camerasByParking = computed(() =>
  cameras.value.filter((c) => c.parking_id === selectedParkingId.value),
)

const camerasOnline = computed(
  () => camerasByParking.value.filter((c) => c.last_heartbeat_ok === true).length,
)
const camerasOffline = computed(
  () => camerasByParking.value.filter((c) => c.last_heartbeat_ok === false).length,
)
const camerasNeverProbed = computed(
  () => camerasByParking.value.filter(
    (c) => c.last_heartbeat_at === null && c.last_heartbeat_ok === null,
  ).length,
)

async function load(): Promise<void> {
  loading.value = true
  try {
    const { data: ps } = await http.get<Parking[]>('/parkings')
    parkings.value = ps
    if (!selectedParkingId.value && ps.length) {
      selectedParkingId.value = ps[0].id
    }
    if (selectedParkingId.value) {
      const [{ data: cs }, sum] = await Promise.all([
        http.get<Camera[]>(`/parkings/${selectedParkingId.value}/cameras`),
        getTicketSummary(selectedParkingId.value).catch(() => null),
      ])
      cameras.value = cs
      summary.value = sum
    }
  } catch {
    ui.pushToast('error', 'No se pudo cargar el dashboard')
  } finally {
    loading.value = false
  }
}

onMounted(load)

function kindLabel(k: CameraKind): string {
  return k === 'gate' ? 'Portería' : 'Fiscalización'
}
function healthLabel(c: Camera): string {
  if (c.last_heartbeat_at === null && c.last_heartbeat_ok === null) {
    return 'Sin probar'
  }
  if (c.last_heartbeat_ok === false) return 'Caída'
  if (c.last_heartbeat_ok === true) return 'En línea'
  return '—'
}
function healthClass(c: Camera): string {
  if (c.last_heartbeat_at === null && c.last_heartbeat_ok === null) {
    return 'bg-slate-100 text-slate-700'
  }
  if (c.last_heartbeat_ok === false) return 'bg-rose-100 text-rose-700'
  return 'bg-emerald-100 text-emerald-700'
}
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Dashboard del parking</h1>
        <p class="text-sm text-slate-500">
          Resumen operativo de las últimas 24 horas
        </p>
      </div>
      <select
        v-if="parkings.length > 1"
        v-model.number="selectedParkingId"
        class="input w-auto"
        @change="load"
      >
        <option v-for="p in parkings" :key="p.id" :value="p.id">
          {{ p.name }}
        </option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <!-- KPIs del parking seleccionado -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-white rounded-xl p-5 shadow-card">
          <div class="text-xs uppercase tracking-wide text-slate-500">Cámaras</div>
          <div class="mt-2 text-3xl font-semibold text-slate-900">
            {{ camerasByParking.length }}
          </div>
          <div class="text-xs mt-1 text-slate-500">
            en {{ parkings.find((p) => p.id === selectedParkingId)?.name ?? '—' }}
          </div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-card">
          <div class="text-xs uppercase tracking-wide text-slate-500">En línea</div>
          <div class="mt-2 text-3xl font-semibold text-emerald-600">
            {{ camerasOnline }}
          </div>
          <div class="text-xs mt-1 text-slate-500">
            reportando heartbeat OK
          </div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-card">
          <div class="text-xs uppercase tracking-wide text-slate-500">Caídas</div>
          <div class="mt-2 text-3xl font-semibold text-rose-600">
            {{ camerasOffline }}
          </div>
          <div class="text-xs mt-1 text-slate-500">
            último probe fallido
          </div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-card">
          <div class="text-xs uppercase tracking-wide text-slate-500">Sin probar</div>
          <div class="mt-2 text-3xl font-semibold text-slate-500">
            {{ camerasNeverProbed }}
          </div>
          <div class="text-xs mt-1 text-slate-500">
            sin historial
          </div>
        </div>
      </div>

      <!-- Listado de cámaras con salud -->
      <div class="mt-8 bg-white rounded-xl shadow-card overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200">
          <h2 class="font-semibold">Cámaras</h2>
        </div>
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-5 py-3 font-medium">Código</th>
              <th class="px-5 py-3 font-medium">Nombre</th>
              <th class="px-5 py-3 font-medium">Tipo</th>
              <th class="px-5 py-3 font-medium">Último heartbeat</th>
              <th class="px-5 py-3 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="c in camerasByParking" :key="c.id">
              <td class="px-5 py-3 font-mono text-xs">{{ c.code }}</td>
              <td class="px-5 py-3">{{ c.name }}</td>
              <td class="px-5 py-3">
                <span
                  :class="['text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded',
                           c.kind === 'gate' ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-700']"
                >{{ kindLabel(c.kind) }}</span>
              </td>
              <td class="px-5 py-3 text-xs text-slate-500">
                {{ c.last_heartbeat_at
                  ? new Date(c.last_heartbeat_at).toLocaleString('es-ES')
                  : 'Nunca' }}
              </td>
              <td class="px-5 py-3">
                <span :class="['text-xs font-semibold px-2 py-0.5 rounded', healthClass(c)]">
                  {{ healthLabel(c) }}
                </span>
              </td>
            </tr>
            <tr v-if="!camerasByParking.length">
              <td colspan="5" class="px-5 py-6 text-center text-slate-500">
                Esta sucursal no tiene cámaras dadas de alta.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Sprint Fase 4-parte-2 (2026-07-06): KPIs de tickets en 24 h.
      Fuente: GET /parkings/{parking_id}/tickets/summary. -->
      <section class="mt-8 grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Tickets totales (24 h)
          </div>
          <div class="mt-2 text-3xl font-semibold text-slate-900">
            {{ summary?.total_tickets_24h ?? '—' }}
          </div>
        </div>
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Activos ahora
          </div>
          <div class="mt-2 text-3xl font-semibold text-emerald-700">
            {{ summary?.active_tickets_now ?? '—' }}
          </div>
        </div>
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Cerrados (24 h)
          </div>
          <div class="mt-2 text-3xl font-semibold text-slate-700">
            {{ summary?.closed_tickets_24h ?? '—' }}
          </div>
        </div>
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Anulados (24 h)
          </div>
          <div class="mt-2 text-3xl font-semibold text-rose-700">
            {{ summary?.cancelled_tickets_24h ?? '—' }}
          </div>
        </div>
      </section>
      <section class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Ingresos (24 h)
          </div>
          <div class="mt-2 text-2xl font-semibold text-slate-900">
            {{
              summary?.total_revenue_24h === null || summary === null
                ? '—'
                : `${summary.total_revenue_24h.toFixed(2)} €`
            }}
          </div>
        </div>
        <div class="bg-white rounded-xl shadow-card p-5">
          <div class="text-xs uppercase tracking-wide text-slate-500">
            Duración media
          </div>
          <div class="mt-2 text-2xl font-semibold text-slate-900">
            {{
              summary?.average_duration_minutes === null || summary === null
                ? '—'
                : `${summary.average_duration_minutes.toFixed(1)} min`
            }}
          </div>
        </div>
      </section>
    </template>
  </AppLayout>
</template>