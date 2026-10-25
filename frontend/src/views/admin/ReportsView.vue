<script setup lang="ts">
/**
 * Reportería — vista admin dedicada (Sprint UI Costes + Reportería
 * + Dashboard KPIs, 2026-07-06).
 *
 * Extraído de `DashboardView.vue` (Sprint P1) para separar el flujo de
 * carga de costes del flujo de consulta + exportación de reportes.
 *
 * Endpoints consumidos:
 *   - GET  /parkings                       — lista de sucursales.
 *   - GET  /admin/reports/margins?...      — reporte (JSON).
 *   - GET  /admin/reports/margins.csv?...  — reporte (CSV download).
 *
 * RBAC: admin-only (la guarda de router ya redirige a otros perfiles).
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import {
  type CostCategory,
  type MarginReport,
  downloadMarginReportCsv,
  getMarginReport,
  http,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loading = ref(true)

const selectedParkingId = ref<number | null>(null)
const report = ref<MarginReport | null>(null)
const reportFrom = ref<string>('')
const reportTo = ref<string>('')
const reportLoading = ref(false)

const categoryLabel: Record<CostCategory, string> = {
  mantenimiento: 'Mantenimiento',
  camaras: 'Cámaras',
  operacion: 'Operación',
  otros: 'Otros',
}

function euro(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(2).replace('.', ',')} €`
}

async function loadParkings(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (!selectedParkingId.value && data.length) {
      selectedParkingId.value = data[0].id
      const today = new Date()
      const monthAgo = new Date(today)
      monthAgo.setMonth(monthAgo.getMonth() - 1)
      reportTo.value = today.toISOString().slice(0, 10)
      reportFrom.value = monthAgo.toISOString().slice(0, 10)
    }
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
}

async function loadReport(): Promise<void> {
  if (!selectedParkingId.value || !reportFrom.value || !reportTo.value) return
  reportLoading.value = true
  try {
    report.value = await getMarginReport({
      parking_id: selectedParkingId.value,
      from: new Date(reportFrom.value).toISOString(),
      to: new Date(`${reportTo.value}T23:59:59`).toISOString(),
    })
  } catch {
    ui.pushToast('error', 'No se pudo generar el reporte')
    report.value = null
  } finally {
    reportLoading.value = false
  }
}

function onExportCsv(): void {
  if (!selectedParkingId.value) return
  // Descarga directa: axios con responseType='blob' envía el Authorization
  // header (interceptor client.ts) y forzamos la descarga con anchor.
  http
    .get(downloadMarginReportCsv({
      parking_id: selectedParkingId.value,
      from: new Date(reportFrom.value).toISOString(),
      to: new Date(`${reportTo.value}T23:59:59`).toISOString(),
    }), { responseType: 'blob' })
    .then((r) => {
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `margin-${selectedParkingId.value}-${reportFrom.value}-${reportTo.value}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    })
    .catch(() => ui.pushToast('error', 'No se pudo descargar el CSV'))
}

const selectedParking = computed(() =>
  parkings.value.find((p) => p.id === selectedParkingId.value) ?? null,
)

async function onParkingChange(): Promise<void> {
  report.value = null
}

onMounted(async () => {
  await loadParkings()
  if (selectedParkingId.value) await loadReport()
})
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Reportería</h1>
        <p class="text-sm text-slate-500">
          Reporte de margen por sucursal y rango de fechas
        </p>
      </div>
      <select
        v-if="parkings.length > 1"
        aria-label="Sucursal"
        v-model.number="selectedParkingId"
        class="input w-auto"
        @change="onParkingChange"
      >
        <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <section v-else class="bg-white rounded-xl shadow-card overflow-hidden">
      <div class="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="font-semibold">Reporte de margen</h2>
          <p class="text-xs text-slate-500 mt-0.5">
            {{ selectedParking?.name ?? '—' }} · ingresos de tickets cerrados
            − costes aplicados al rango
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label class="text-sm">
            <span class="block text-slate-700 mb-1">Desde</span>
            <input v-model="reportFrom" type="date" class="input" />
          </label>
          <label class="text-sm">
            <span class="block text-slate-700 mb-1">Hasta</span>
            <input v-model="reportTo" type="date" class="input" />
          </label>
          <button class="btn-secondary text-sm" :disabled="reportLoading" @click="loadReport">
            {{ reportLoading ? 'Calculando…' : 'Generar' }}
          </button>
          <button class="btn-primary text-sm" :disabled="!report" @click="onExportCsv">
            Exportar CSV
          </button>
        </div>
      </div>

      <div v-if="report" class="p-5">
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div class="bg-slate-50 rounded-lg p-4">
            <div class="text-xs uppercase tracking-wide text-slate-500">Ingresos</div>
            <div class="mt-1 text-xl font-semibold text-emerald-700">
              {{ euro(report.total_revenue) }}
            </div>
            <div class="text-xs text-slate-500">{{ report.closed_tickets }} tickets cerrados</div>
          </div>
          <div class="bg-slate-50 rounded-lg p-4">
            <div class="text-xs uppercase tracking-wide text-slate-500">Costes</div>
            <div class="mt-1 text-xl font-semibold text-rose-700">
              {{ euro(report.total_costs) }}
            </div>
          </div>
          <div class="bg-slate-50 rounded-lg p-4">
            <div class="text-xs uppercase tracking-wide text-slate-500">Margen</div>
            <div
              class="mt-1 text-xl font-semibold"
              :class="report.margin >= 0 ? 'text-emerald-700' : 'text-rose-700'"
            >
              {{ euro(report.margin) }}
            </div>
          </div>
          <div class="bg-slate-50 rounded-lg p-4">
            <div class="text-xs uppercase tracking-wide text-slate-500">Categorías</div>
            <div class="mt-1 text-xl font-semibold text-slate-700">
              {{ report.cost_breakdown.length }}
            </div>
          </div>
        </div>

        <div v-if="report.cost_breakdown.length" class="overflow-x-auto min-w-0">
          <table class="mt-5 w-full text-sm min-w-max">
            <thead class="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th class="py-2 font-medium">Categoría</th>
                <th class="py-2 font-medium text-right">Importe aplicado</th>
                <th class="py-2 font-medium text-right">Costes</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="row in report.cost_breakdown" :key="row.category">
                <td class="py-2">{{ categoryLabel[row.category] }}</td>
                <td class="py-2 text-right">{{ euro(row.amount) }}</td>
                <td class="py-2 text-right">{{ row.cost_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else class="px-5 py-6 text-sm text-slate-500">
        Selecciona un rango y pulsa "Generar".
      </div>
    </section>
  </AppLayout>
</template>