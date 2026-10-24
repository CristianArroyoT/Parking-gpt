<script setup lang="ts">
/**
 * Costes operativos — vista admin dedicada (Sprint UI Costes + Reportería
 * + Dashboard KPIs, 2026-07-06).
 *
 * Extraído de `DashboardView.vue` (Sprint P1) para liberar al dashboard
 * de cargas pesadas y darle al admin un espacio propio para CRUD de
 * costes con foco visual.
 *
 * Endpoints consumidos:
 *   - GET  /parkings                       — lista de sucursales.
 *   - GET  /admin/costs?parking_id=...     — costes de la sucursal.
 *   - POST /admin/costs                    — alta de coste.
 *   - DELETE /admin/costs/{id}             — borrado de coste.
 *
 * RBAC: admin-only (la guarda de router ya redirige a otros perfiles).
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import {
  type Cost,
  type CostCategory,
  type CostPeriod,
  createCost,
  deleteCost,
  http,
  listCosts,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loading = ref(true)
const selectedParkingId = ref<number | null>(null)

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
  } catch {
    ui.pushToast('error', 'No se pudo eliminar el coste')
  }
}

const selectedParking = computed(() =>
  parkings.value.find((p) => p.id === selectedParkingId.value) ?? null,
)

async function onParkingChange(): Promise<void> {
  await loadCosts()
}

onMounted(async () => {
  await loadParkings()
  if (selectedParkingId.value) await loadCosts()
})
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Costes operativos</h1>
        <p class="text-sm text-slate-500">
          Alta, listado y eliminación de costes por sucursal
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
      <div class="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
        <div>
          <h2 class="font-semibold">Listado de costes</h2>
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

      <div class="overflow-x-auto min-w-0">
        <table class="w-full text-sm min-w-max">
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
      </div>
    </section>
  </AppLayout>
</template>