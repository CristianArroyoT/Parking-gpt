<script setup lang="ts">
/**
 * Dashboard global del administrador (Sprint P1, 2026-07-06).
 *
 * Hasta Sprint Fase 4 sólo mostraba KPIs placeholder y la lista de
 * sucursales. Sprint P1 añade la sección de **costes operativos** y el
 * **reporte de margen** (con exportación CSV).
 *
 * Endpoints consumidos:
 *   - GET  /parkings                       — lista de sucursales.
 *   - GET  /admin/costs?parking_id=...     — costes de la sucursal.
 *   - POST /admin/costs                    — alta de coste.
 *   - DELETE /admin/costs/{id}             — borrado de coste.
 *   - GET  /admin/reports/margins?...      — reporte (JSON).
 *   - GET  /admin/reports/margins.csv?...  — reporte (CSV download).
 *
 * RBAC: toda la vista es admin-only (la guarda de router ya redirige
 * a otros perfiles). NO comprobamos el rol aquí — el backend rechaza
 * con 403 si alguien intenta forzar.
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import {
  http,
  type Cost,
  type CostCategory,
  type CostPeriod,
  type MarginReport,
  createCost,
  deleteCost,
  downloadMarginReportCsv,
  getMarginReport,
  listCosts,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loading = ref(true)

const costs = ref<Cost[]>([])
const showCostForm = ref(false)

const costForm = ref<{
  category: CostCategory
  amount: number
  periodicity: CostPeriod
  period_start: string
  period_end: string
  description: string
}>({
  category: 'mantenimiento',
  amount: 0,
  periodicity: 'puntual',
  period_start: new Date().toISOString().slice(0, 10),
  period_end: '',
  description: '',
})

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
const periodLabel: Record<CostPeriod, string> = {
  puntual: 'Puntual',
  mensual: 'Mensual',
  trimestral: 'Trimestral',
  anual: 'Anual',
}

function euro(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(2)} €`
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

async function loadCosts(): Promise<void> {
  if (!selectedParkingId.value) return
  try {
    costs.value = await listCosts({ parking_id: selectedParkingId.value })
  } catch {
    ui.pushToast('error', 'No se pudieron cargar los costes')
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

async function onSubmitCost(): Promise<void> {
  if (!selectedParkingId.value) return
  if (costForm.value.amount <= 0) {
    ui.pushToast('error', 'El importe debe ser positivo')
    return
  }
  const payload = {
    parking_id: selectedParkingId.value,
    category: costForm.value.category,
    amount: costForm.value.amount,
    periodicity: costForm.value.periodicity,
    period_start: new Date(`${costForm.value.period_start}T00:00:00`).toISOString(),
    period_end: costForm.value.periodicity === 'puntual' && costForm.value.period_end
      ? new Date(`${costForm.value.period_end}T23:59:59`).toISOString()
      : null,
    description: costForm.value.description || null,
  }
  try {
    await createCost(payload)
    ui.pushToast('success', 'Coste creado')
    showCostForm.value = false
    costForm.value.amount = 0
    costForm.value.description = ''
    await loadCosts()
    if (report.value) await loadReport()
  } catch (e: unknown) {
    const detail =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
      'Error al crear el coste'
    ui.pushToast('error', String(detail))
  }
}

async function onDeleteCost(c: Cost): Promise<void> {
  if (!confirm(`¿Eliminar el coste "${c.description ?? c.category}"?`)) return
  try {
    await deleteCost(c.id)
    ui.pushToast('success', 'Coste eliminado')
    await loadCosts()
    if (report.value) await loadReport()
  } catch {
    ui.pushToast('error', 'No se pudo eliminar el coste')
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

onMounted(async () => {
  await loadParkings()
  if (selectedParkingId.value) {
    await Promise.all([loadCosts(), loadReport()])
  }
})

async function onParkingChange(): Promise<void> {
  report.value = null
  await Promise.all([loadCosts(), loadReport()])
}
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Dashboard global</h1>
        <p class="text-sm text-slate-500">
          Resumen de las últimas 24 horas · {{ parkings.length }} sucursales activas
        </p>
      </div>
      <select
        v-if="parkings.length > 1"
        v-model.number="selectedParkingId"
        class="input w-auto"
        @change="onParkingChange"
      >
        <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <!-- Estado de las sucursales -->
      <div class="bg-white rounded-xl shadow-card overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200">
          <h2 class="font-semibold">Estado de las sucursales</h2>
        </div>
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-5 py-3 font-medium">Sucursal</th>
              <th class="px-5 py-3 font-medium">Código</th>
              <th class="px-5 py-3 font-medium">Ciudad</th>
              <th class="px-5 py-3 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="p in parkings" :key="p.id">
              <td class="px-5 py-3 font-medium">{{ p.name }}</td>
              <td class="px-5 py-3 font-mono text-xs">{{ p.code }}</td>
              <td class="px-5 py-3">{{ p.city }}</td>
              <td class="px-5 py-3">
                <span :class="p.is_active ? 'text-emerald-600' : 'text-slate-500'">
                  {{ p.is_active ? 'Activa' : 'Inactiva' }}
                </span>
              </td>
            </tr>
            <tr v-if="!parkings.length">
              <td colspan="4" class="px-5 py-6 text-center text-slate-500">
                No hay sucursales. Ejecuta el seed en el backend.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Sprint P1 (2026-07-06): Costes operativos por sucursal -->
      <section class="mt-8 bg-white rounded-xl shadow-card overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            <h2 class="font-semibold">Costes operativos</h2>
            <p class="text-xs text-slate-500 mt-0.5">
              {{ selectedParking?.name ?? '—' }} · {{ costs.length }} registrados
            </p>
          </div>
          <div class="flex gap-2">
            <button class="btn-secondary text-sm" @click="loadCosts">Refrescar</button>
            <button class="btn-primary text-sm" @click="showCostForm = !showCostForm">
              {{ showCostForm ? 'Cancelar' : 'Nuevo coste' }}
            </button>
          </div>
        </div>

        <div v-if="showCostForm" class="px-5 py-4 bg-slate-50 border-b border-slate-200">
          <form class="grid grid-cols-1 md:grid-cols-3 gap-3" @submit.prevent="onSubmitCost">
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Categoría</span>
              <select v-model="costForm.category" class="input w-full">
                <option value="mantenimiento">Mantenimiento</option>
                <option value="camaras">Cámaras</option>
                <option value="operacion">Operación</option>
                <option value="otros">Otros</option>
              </select>
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Periodicidad</span>
              <select v-model="costForm.periodicity" class="input w-full">
                <option value="puntual">Puntual</option>
                <option value="mensual">Mensual</option>
                <option value="trimestral">Trimestral</option>
                <option value="anual">Anual</option>
              </select>
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Importe (€)</span>
              <input
                v-model.number="costForm.amount"
                type="number" step="0.01" min="0"
                class="input w-full" required
              />
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Inicio</span>
              <input v-model="costForm.period_start" type="date" class="input w-full" required />
            </label>
            <label class="text-sm" v-if="costForm.periodicity === 'puntual'">
              <span class="block text-slate-700 mb-1">Fin</span>
              <input v-model="costForm.period_end" type="date" class="input w-full" required />
            </label>
            <label class="text-sm md:col-span-2">
              <span class="block text-slate-700 mb-1">Descripción</span>
              <input
                v-model="costForm.description"
                type="text" maxlength="255"
                placeholder="Ej. Alquiler cámara 3"
                class="input w-full"
              />
            </label>
            <div class="md:col-span-3 flex justify-end">
              <button type="submit" class="btn-primary text-sm">Guardar coste</button>
            </div>
          </form>
        </div>

        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-5 py-3 font-medium">Categoría</th>
              <th class="px-5 py-3 font-medium">Importe</th>
              <th class="px-5 py-3 font-medium">Periodicidad</th>
              <th class="px-5 py-3 font-medium">Desde</th>
              <th class="px-5 py-3 font-medium">Hasta</th>
              <th class="px-5 py-3 font-medium">Descripción</th>
              <th class="px-5 py-3 font-medium text-right">Acciones</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="c in costs" :key="c.id">
              <td class="px-5 py-3">{{ categoryLabel[c.category] }}</td>
              <td class="px-5 py-3">{{ euro(c.amount) }}</td>
              <td class="px-5 py-3">{{ periodLabel[c.periodicity] }}</td>
              <td class="px-5 py-3 text-xs">
                {{ new Date(c.period_start).toLocaleDateString('es-ES') }}
              </td>
              <td class="px-5 py-3 text-xs">
                {{ c.period_end ? new Date(c.period_end).toLocaleDateString('es-ES') : '—' }}
              </td>
              <td class="px-5 py-3 text-slate-600">{{ c.description ?? '—' }}</td>
              <td class="px-5 py-3 text-right">
                <button
                  class="text-rose-600 hover:underline text-xs"
                  @click="onDeleteCost(c)"
                >Eliminar</button>
              </td>
            </tr>
            <tr v-if="!costs.length">
              <td colspan="7" class="px-5 py-6 text-center text-slate-500">
                No hay costes para esta sucursal.
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Sprint P1: Reporte de margen -->
      <section class="mt-8 bg-white rounded-xl shadow-card overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="font-semibold">Reporte de margen</h2>
            <p class="text-xs text-slate-500 mt-0.5">
              Ingresos de tickets cerrados − costes aplicados al rango.
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

          <table v-if="report.cost_breakdown.length" class="mt-5 w-full text-sm">
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
        <div v-else class="px-5 py-6 text-sm text-slate-500">
          Selecciona un rango y pulsa "Generar".
        </div>
      </section>
    </template>
  </AppLayout>
</template>