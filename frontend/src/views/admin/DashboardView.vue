<script setup lang="ts">
/**
 * Dashboard global del administrador (Sprint UI Costes + Reportería
 * + Dashboard KPIs, 2026-07-06).
 *
 * Sólo lectura. Costes operativos y reporte de margen viven en sus
 * propias páginas (CostsView, ReportsView), accesibles desde el sidebar.
 *
 * Endpoints consumidos:
 *   - GET /parkings                  — lista de sucursales.
 *   - GET /admin/dashboard/kpis?...  — KPIs agregados (admin-only).
 *
 * RBAC: admin-only (la guarda de router ya redirige a otros perfiles).
 * El gestor usa ``DashboardGestor.vue`` con sus propias sucursales.
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import {
  type DashboardKpis,
  getDashboardKpis,
  http,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loadingParkings = ref(true)
const selectedParkingId = ref<number | null>(null)
const kpis = ref<DashboardKpis | null>(null)
const loadingKpis = ref(false)

function euro(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(2).replace('.', ',')} €`
}

function labelFor(n: number | null, windowHours: number): string {
  // windowHours=24 → "24h", 168 → "7d", 720 → "30d"
  if (windowHours < 48) return `${windowHours}h`
  return `${Math.round(windowHours / 24)}d`
}

async function loadParkings(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loadingParkings.value = false
  }
}

async function loadKpis(): Promise<void> {
  loadingKpis.value = true
  try {
    kpis.value = await getDashboardKpis(
      selectedParkingId.value === null ? undefined : selectedParkingId.value,
    )
  } catch {
    ui.pushToast('error', 'No se pudieron cargar los KPIs')
    kpis.value = null
  } finally {
    loadingKpis.value = false
  }
}

async function onParkingChange(): Promise<void> {
  await loadKpis()
}

const selectedParking = computed(() =>
  parkings.value.find((p) => p.id === selectedParkingId.value) ?? null,
)

const scopeLabel = computed(() => {
  if (!kpis.value) return ''
  if (kpis.value.parking_id === null) return 'Todas las sucursales'
  return selectedParking.value?.name ?? `Sucursal #${kpis.value.parking_id}`
})

onMounted(async () => {
  await loadParkings()
  await loadKpis()
})
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Dashboard global</h1>
        <p class="text-sm text-slate-500">
          Indicadores agregados · {{ scopeLabel || '—' }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <select
          v-if="parkings.length > 1"
          v-model.number="selectedParkingId"
          class="input w-auto"
          @change="onParkingChange"
        >
          <option :value="null">Todas las sucursales</option>
          <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button class="btn-secondary text-sm" :disabled="loadingKpis" @click="loadKpis">
          {{ loadingKpis ? 'Cargando…' : 'Refrescar' }}
        </button>
      </div>
    </div>

    <div v-if="loadingParkings" class="text-sm text-slate-500">Cargando…</div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Card Plazas -->
      <div class="bg-white rounded-xl shadow-card p-5">
        <div class="text-xs uppercase tracking-wide text-slate-500">Plazas</div>
        <div class="mt-2 grid grid-cols-2 gap-2">
          <div>
            <div class="text-xs text-slate-500">Totales</div>
            <div class="text-2xl font-semibold text-slate-800">
              {{ kpis?.spaces.total ?? '—' }}
            </div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Ocupadas</div>
            <div class="text-2xl font-semibold text-amber-600">
              {{ kpis?.spaces.occupied ?? '—' }}
            </div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Libres</div>
            <div class="text-2xl font-semibold text-emerald-600">
              {{ kpis?.spaces.free ?? '—' }}
            </div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Rotas</div>
            <div class="text-2xl font-semibold text-rose-600">
              {{ kpis?.spaces.broken ?? '—' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Card Cámaras -->
      <div class="bg-white rounded-xl shadow-card p-5">
        <div class="text-xs uppercase tracking-wide text-slate-500">Cámaras</div>
        <div class="mt-2 grid grid-cols-2 gap-2">
          <div>
            <div class="text-xs text-slate-500">Totales</div>
            <div class="text-2xl font-semibold text-slate-800">
              {{ kpis?.cameras.total ?? '—' }}
            </div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Operativas</div>
            <div class="text-2xl font-semibold text-emerald-600">
              {{ kpis?.cameras.operational ?? '—' }}
            </div>
          </div>
          <div class="col-span-2">
            <div class="text-xs text-slate-500">En alerta</div>
            <div class="text-2xl font-semibold text-rose-600">
              {{ kpis?.cameras.alert ?? '—' }}
            </div>
          </div>
          <div class="col-span-2">
            <div class="text-xs text-slate-500">Sin probar</div>
            <div class="text-2xl font-semibold text-slate-500">
              {{ kpis?.cameras.never_probed ?? '—' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Card Ingresos -->
      <div class="bg-white rounded-xl shadow-card p-5">
        <div class="text-xs uppercase tracking-wide text-slate-500">Ingresos</div>
        <div class="mt-2 space-y-2">
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Día</div>
            <div class="text-lg font-semibold text-emerald-700">
              {{ euro(kpis?.revenue.day) }}
            </div>
          </div>
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Semana</div>
            <div class="text-lg font-semibold text-emerald-700">
              {{ euro(kpis?.revenue.week) }}
            </div>
          </div>
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Mes</div>
            <div class="text-lg font-semibold text-emerald-700">
              {{ euro(kpis?.revenue.month) }}
            </div>
          </div>
        </div>
        <div v-if="kpis" class="mt-3 text-[10px] text-slate-400">
          Ventanas {{ labelFor(kpis.revenue.day, kpis.window_hours_day) }} /
          {{ labelFor(kpis.revenue.week, kpis.window_hours_week) }} /
          {{ labelFor(kpis.revenue.month, kpis.window_hours_month) }}
        </div>
      </div>

      <!-- Card Costes -->
      <div class="bg-white rounded-xl shadow-card p-5">
        <div class="text-xs uppercase tracking-wide text-slate-500">Costes</div>
        <div class="mt-2 space-y-2">
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Día</div>
            <div class="text-lg font-semibold text-rose-700">
              {{ euro(kpis?.costs.day) }}
            </div>
          </div>
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Semana</div>
            <div class="text-lg font-semibold text-rose-700">
              {{ euro(kpis?.costs.week) }}
            </div>
          </div>
          <div class="flex items-baseline justify-between">
            <div class="text-xs text-slate-500">Mes</div>
            <div class="text-lg font-semibold text-rose-700">
              {{ euro(kpis?.costs.month) }}
            </div>
          </div>
        </div>
        <div v-if="kpis" class="mt-3 text-[10px] text-slate-400">
          Costes recurrentes prorrateados al rango
        </div>
      </div>
    </div>
  </AppLayout>
</template>