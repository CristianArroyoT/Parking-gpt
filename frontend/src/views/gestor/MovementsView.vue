<script setup lang="ts">
/**
 * T-20 (2026-10-21): "Entradas / Salidas" — log de movimientos del gestor.
 *
 * Fuente de datos: ``GET /api/v1/tickets?parking_id=<sucursal>``. El
 * backend acota los tickets a las sucursales donde el gestor tiene
 * membresía (``ParkingMembership``), así que el log nunca muestra
 * movimiento de otra sucursal.
 *
 * Límite conocido del backend: ``GET /tickets`` sólo acepta ``parking_id``
 * y ``only_active`` (y devuelve como máximo 200 registros). Los filtros de
 * fecha, plaza, vehículo y origen se aplican **en el navegador** sobre lo
 * descargado, con la función pura ``filterMovements``.
 */
import { computed, onMounted, ref, watch } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { useUiStore } from '@/stores/ui'
import {
  filterMovements,
  listMovements,
  listParkings,
  listSpaces,
  listVehicles,
  movementLabel,
  type MovementFilters,
  type MovementOrigin,
  type MovementTicket,
  type Parking,
  type ParkingSpace,
  type VehiclePlate,
} from '@/api/gestorOps'

const ui = useUiStore()

const parkings = ref<Parking[]>([])
/** Id de sucursal como texto: los ``<select>`` trabajan con strings. */
const parkingId = ref('')
const movements = ref<MovementTicket[]>([])
const spaces = ref<ParkingSpace[]>([])
const vehicles = ref<VehiclePlate[]>([])

const loading = ref(true)
const error = ref<string | null>(null)

/** Filtros en texto (los ids viajan como string en los ``<select>``). */
const filters = ref({
  desde: '',
  hasta: '',
  plaza: '',
  vehiculo: '',
  origen: '',
})

const appliedFilters = computed<MovementFilters>(() => ({
  desde: filters.value.desde,
  hasta: filters.value.hasta,
  plazaId: filters.value.plaza === '' ? null : Number(filters.value.plaza),
  vehicleId: filters.value.vehiculo === '' ? null : Number(filters.value.vehiculo),
  origin: filters.value.origen as MovementOrigin | '',
}))

const labels = computed(() => ({
  plateByVehicleId: Object.fromEntries(vehicles.value.map((v) => [v.id, v.plate])),
  spaceLabelById: Object.fromEntries(
    spaces.value.map((s) => [s.id, s.number.startsWith(`${s.lane}-`) ? s.number : `${s.lane}-${s.number}`]),
  ),
}))

const filtered = computed(() =>
  filterMovements(movements.value, appliedFilters.value, labels.value),
)

async function loadParkings(): Promise<void> {
  try {
    parkings.value = await listParkings()
    if (parkings.value.length && parkingId.value === '') {
      parkingId.value = String(parkings.value[0].id)
    }
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudieron cargar las sucursales')
  }
}

async function loadBranch(): Promise<void> {
  if (parkingId.value === '') {
    movements.value = []
    spaces.value = []
    return
  }
  const id = Number(parkingId.value)
  loading.value = true
  error.value = null
  try {
    movements.value = await listMovements(id)
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo cargar el log de movimientos')
    movements.value = []
  }
  // Plazas y vehículos son de apoyo: si fallan, el log sigue siendo útil.
  try {
    spaces.value = await listSpaces(id)
  } catch {
    spaces.value = []
  }
  try {
    vehicles.value = await listVehicles()
  } catch {
    vehicles.value = []
  }
  filters.value.plaza = ''
  filters.value.vehiculo = ''
  loading.value = false
}

watch(parkingId, () => {
  void loadBranch()
})

function fmt(d: string | null): string {
  return d ? new Date(d).toLocaleString('es-ES') : '—'
}

function eur(n: number | null): string {
  if (n === null || n === undefined) return '—'
  return n.toFixed(2).replace('.', ',') + ' €'
}

function originLabel(o: string): string {
  if (o === 'automatic') return 'Automático (OCR)'
  if (o === 'manual_entry') return 'Alta manual (entrada)'
  if (o === 'manual_exit') return 'Alta manual (salida)'
  return o
}

function statusBadge(status: string): { label: string; cls: string } {
  if (status === 'activo') return { label: 'Dentro', cls: 'text-emerald-700 bg-emerald-100' }
  if (status === 'cerrado') return { label: 'Cerrado', cls: 'text-slate-700 bg-slate-100' }
  return { label: 'Anulado', cls: 'text-rose-700 bg-rose-100' }
}

function resetFilters(): void {
  filters.value = { desde: '', hasta: '', plaza: '', vehiculo: '', origen: '' }
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

onMounted(async () => {
  await loadParkings()
  await loadBranch()
})
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Entradas / Salidas</h1>
    <p class="text-sm text-slate-500 mb-6">
      Log de movimientos de vehículos de tu sucursal
    </p>

    <!-- Selector de sucursal + filtros -->
    <section class="bg-white rounded-xl shadow-card p-5 mb-6">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-sucursal">
            Sucursal
          </label>
          <select
            id="mov-sucursal"
            v-model="parkingId"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option v-for="p in parkings" :key="p.id" :value="String(p.id)">
              {{ p.name }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-desde">Desde</label>
          <input
            id="mov-desde"
            v-model="filters.desde"
            type="date"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-hasta">Hasta</label>
          <input
            id="mov-hasta"
            v-model="filters.hasta"
            type="date"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-plaza">Plaza</label>
          <select
            id="mov-plaza"
            v-model="filters.plaza"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">Todas</option>
            <option v-for="s in spaces" :key="s.id" :value="String(s.id)">
              {{ s.number.startsWith(`${s.lane}-`) ? s.number : `${s.lane}-${s.number}` }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-vehiculo">
            Vehículo
          </label>
          <select
            id="mov-vehiculo"
            v-model="filters.vehiculo"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">Todos</option>
            <option v-for="v in vehicles" :key="v.id" :value="String(v.id)">{{ v.plate }}</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="mov-origen">Origen</label>
          <select
            id="mov-origen"
            v-model="filters.origen"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">Todos</option>
            <option value="automatic">Automático (OCR)</option>
            <option value="manual_entry">Alta manual (entrada)</option>
            <option value="manual_exit">Alta manual (salida)</option>
          </select>
        </div>
      </div>

      <div class="mt-3 flex items-center gap-3">
        <button
          type="button"
          class="px-3 py-1.5 text-xs rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50"
          @click="resetFilters"
        >
          Limpiar filtros
        </button>
        <span class="text-xs text-slate-500">
          {{ filtered.length }} de {{ movements.length }} movimientos
        </span>
      </div>

      <p class="mt-3 text-xs text-slate-500">
        El backend sólo filtra por sucursal y limita la respuesta a 200
        registros; la fecha, la plaza, el vehículo y el origen se filtran en
        el navegador sobre los datos descargados.
      </p>
    </section>

    <p
      v-if="error"
      class="mb-4 text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
      role="alert"
    >
      {{ error }}
    </p>

    <section class="bg-white rounded-xl shadow-card p-5">
      <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>
      <div v-else-if="!filtered.length" class="text-sm text-slate-500">
        No hay movimientos que cumplan los filtros.
      </div>
      <table v-else class="w-full text-sm">
        <thead class="bg-slate-50 text-slate-500 text-left">
          <tr>
            <th class="px-3 py-2 font-medium">#</th>
            <th class="px-3 py-2 font-medium">Entrada</th>
            <th class="px-3 py-2 font-medium">Salida</th>
            <th class="px-3 py-2 font-medium">Vehículo · Plaza</th>
            <th class="px-3 py-2 font-medium">Origen</th>
            <th class="px-3 py-2 font-medium">Estado</th>
            <th class="px-3 py-2 font-medium text-right">Importe</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="m in filtered" :key="m.id" class="hover:bg-slate-50">
            <td class="px-3 py-2 font-mono text-xs">#{{ m.id }}</td>
            <td class="px-3 py-2">{{ fmt(m.entry_at) }}</td>
            <td class="px-3 py-2">{{ fmt(m.exit_at) }}</td>
            <td class="px-3 py-2 font-medium">{{ movementLabel(m, labels) }}</td>
            <td class="px-3 py-2 text-xs text-slate-600">{{ originLabel(m.origin) }}</td>
            <td class="px-3 py-2">
              <span :class="['text-xs font-semibold px-2 py-0.5 rounded', statusBadge(m.status).cls]">
                {{ statusBadge(m.status).label }}
              </span>
            </td>
            <td class="px-3 py-2 text-right font-medium">{{ eur(m.total) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </AppLayout>
</template>
