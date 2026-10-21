<script setup lang="ts">
/**
 * CRUD de tarifas por sucursal (solo administrador).
 * El backend (commit 36ae194) expone GET/POST/PATCH/DELETE bajo
 *   /api/v1/parkings/{parking_id}/tariffs
 *   - Lectura autenticada para cualquier rol.
 *   - POST/PATCH: gestor con membresía o admin (parking_context).
 *   - DELETE: solo admin.
 * El esquema Pydantic TariffCreate/TariffUpdate vive en
 *   backend/app/schemas/pricing.py.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number
  code: string
  name: string
  city: string
}

interface Tariff {
  id: number
  parking_id: number
  name: string
  price_per_hour: number
  price_per_fraction: number
  fraction_minutes: number
  max_daily: number | null
  valid_from: string
  valid_to: string | null
  created_at: string
  updated_at: string
}

type TariffForm = {
  name: string
  price_per_hour: number
  price_per_fraction: number
  fraction_minutes: number
  max_daily: number | null
  valid_from: string
  valid_to: string | null
}

const auth = useAuthStore()
const ui = useUiStore()
const canDelete = computed(() => auth.role === 'admin')

const parkings = ref<Parking[]>([])
const parkingId = ref<number | null>(null)
const tariffs = ref<Tariff[]>([])
const loadingParkings = ref(true)
const loadingTariffs = ref(false)
const editing = ref<Tariff | null>(null)

const EMPTY_FORM: TariffForm = {
  name: '',
  price_per_hour: 2.5,
  price_per_fraction: 0.7,
  fraction_minutes: 15,
  max_daily: 25,
  valid_from: toLocalInput(new Date()),
  valid_to: null,
}
const form = reactive<TariffForm>({ ...EMPTY_FORM })

function toLocalInput(d: Date): string {
  // datetime-local espera "YYYY-MM-DDTHH:mm" en hora local.
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function fromLocalInput(v: string): string {
  // "YYYY-MM-DDTHH:mm" → ISO 8601 con zona UTC (lo que Pydantic acepta).
  return new Date(v).toISOString()
}

async function loadParkings(): Promise<void> {
  loadingParkings.value = true
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (!parkingId.value && data.length) parkingId.value = data[0].id
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loadingParkings.value = false
  }
}

async function loadTariffs(): Promise<void> {
  if (!parkingId.value) {
    tariffs.value = []
    return
  }
  loadingTariffs.value = true
  try {
    const { data } = await http.get<Tariff[]>(`/parkings/${parkingId.value}/tariffs`)
    tariffs.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las tarifas')
  } finally {
    loadingTariffs.value = false
  }
}

watch(parkingId, () => {
  editing.value = null
  Object.assign(form, EMPTY_FORM)
  loadTariffs()
})

function fmtMoney(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(2).replace('.', ',')} €`
}
function fmtDate(v: string | null): string {
  if (!v) return '—'
  return new Date(v).toLocaleString('es-ES', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}
function isVigente(t: Tariff): boolean {
  const now = Date.now()
  const from = new Date(t.valid_from).getTime()
  const to = t.valid_to ? new Date(t.valid_to).getTime() : Number.POSITIVE_INFINITY
  return from <= now && now <= to
}

function startCreate(): void {
  editing.value = null
  Object.assign(form, EMPTY_FORM)
}
function startEdit(t: Tariff): void {
  editing.value = t
  Object.assign(form, {
    name: t.name,
    price_per_hour: t.price_per_hour,
    price_per_fraction: t.price_per_fraction,
    fraction_minutes: t.fraction_minutes,
    max_daily: t.max_daily,
    valid_from: toLocalInput(new Date(t.valid_from)),
    valid_to: t.valid_to ? toLocalInput(new Date(t.valid_to)) : null,
  })
}

async function submit(): Promise<void> {
  if (!parkingId.value) {
    ui.pushToast('warn', 'Selecciona una sucursal primero')
    return
  }
  const payload = {
    parking_id: parkingId.value,
    name: form.name,
    price_per_hour: Number(form.price_per_hour),
    price_per_fraction: Number(form.price_per_fraction),
    fraction_minutes: Number(form.fraction_minutes) || 15,
    max_daily: form.max_daily === null || form.max_daily === undefined || Number.isNaN(Number(form.max_daily))
      ? null
      : Number(form.max_daily),
    valid_from: fromLocalInput(form.valid_from),
    valid_to: form.valid_to ? fromLocalInput(form.valid_to) : null,
  }
  try {
    if (editing.value) {
      // PATCH con campos omitibles (TariffUpdate los marca todos Optional).
      const patch: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(payload)) {
        if (k === 'parking_id') continue // no se puede reasignar.
        patch[k] = v
      }
      await http.patch(`/parkings/${parkingId.value}/tariffs/${editing.value.id}`, patch)
      ui.pushToast('success', 'Tarifa actualizada')
    } else {
      await http.post(`/parkings/${parkingId.value}/tariffs`, payload)
      ui.pushToast('success', 'Tarifa creada')
    }
    await loadTariffs()
    startCreate()
  } catch (err: unknown) {
    const msg = extractError(err, 'No se pudo guardar la tarifa')
    ui.pushToast('error', msg)
  }
}

async function remove(t: Tariff): Promise<void> {
  if (!canDelete.value) return
  if (!confirm(`¿Eliminar la tarifa "${t.name}"? Se conservará el histórico de tickets.`)) return
  try {
    await http.delete(`/parkings/${parkingId.value}/tariffs/${t.id}`)
    ui.pushToast('success', 'Tarifa eliminada')
    await loadTariffs()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo eliminar la tarifa'))
  }
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

onMounted(loadParkings)
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Tarifas</h1>
        <p class="text-sm text-slate-500">
          Tarifas por hora y fracción de cada sucursal. La vigente se aplica al cerrar el ticket.
        </p>
      </div>
    </div>

    <div class="bg-white rounded-xl shadow-card p-5 mb-6">
      <div class="flex items-end gap-3">
        <div class="flex-1">
          <label class="block text-xs font-medium text-slate-700">Sucursal</label>
          <select v-model.number="parkingId" class="input" :disabled="loadingParkings">
            <option v-if="!loadingParkings && !parkings.length" :value="null">Sin sucursales</option>
            <option v-for="p in parkings" :key="p.id" :value="p.id">
              {{ p.name }} · {{ p.city }} ({{ p.code }})
            </option>
          </select>
        </div>
        <button
          type="button"
          class="btn-primary"
          :disabled="!parkingId"
          @click="startCreate"
        >
          + Nueva tarifa
        </button>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 bg-white rounded-xl shadow-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full min-w-max text-sm">
            <thead class="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th class="px-5 py-3 font-medium">Nombre</th>
                <th class="px-5 py-3 font-medium">€/hora</th>
                <th class="px-5 py-3 font-medium">Fracción</th>
                <th class="px-5 py-3 font-medium">Máx. día</th>
                <th class="px-5 py-3 font-medium">Vigencia</th>
                <th class="px-5 py-3 font-medium">Estado</th>
                <th class="px-5 py-3 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="!parkingId"><td colspan="7" class="px-5 py-6 text-center text-slate-500">Selecciona una sucursal</td></tr>
              <tr v-else-if="loadingTariffs"><td colspan="7" class="px-5 py-6 text-center text-slate-500">Cargando…</td></tr>
              <tr v-else-if="!tariffs.length"><td colspan="7" class="px-5 py-6 text-center text-slate-500">No hay tarifas para esta sucursal</td></tr>
              <tr v-for="t in tariffs" :key="t.id">
                <td class="px-5 py-3 font-medium">{{ t.name }}</td>
                <td class="px-5 py-3">{{ fmtMoney(t.price_per_hour) }}</td>
                <td class="px-5 py-3">
                  {{ fmtMoney(t.price_per_fraction) }} / {{ t.fraction_minutes }} min
                </td>
                <td class="px-5 py-3">{{ fmtMoney(t.max_daily) }}</td>
                <td class="px-5 py-3 text-xs">
                  <div>desde {{ fmtDate(t.valid_from) }}</div>
                  <div class="text-slate-500">hasta {{ fmtDate(t.valid_to) }}</div>
                </td>
                <td class="px-5 py-3">
                  <span
                    :class="isVigente(t) ? 'text-emerald-600' : 'text-slate-500'"
                    class="text-xs"
                  >
                    {{ isVigente(t) ? 'Vigente' : 'No vigente' }}
                  </span>
                </td>
                <td class="px-5 py-3 text-right space-x-2 whitespace-nowrap">
                  <button class="btn-secondary" @click="startEdit(t)">Editar</button>
                  <button
                    v-if="canDelete"
                    class="btn-secondary text-rose-600 border-rose-300"
                    @click="remove(t)"
                  >
                    Eliminar
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-4">
          {{ editing ? 'Editar tarifa' : 'Nueva tarifa' }}
        </h2>
        <form class="space-y-3" @submit.prevent="submit">
          <div>
            <label class="block text-xs font-medium text-slate-700">Nombre</label>
            <input v-model="form.name" required minlength="2" maxlength="64" class="input" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-700">€/hora</label>
              <input v-model.number="form.price_per_hour" type="number" step="0.01" min="0" required class="input" />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700">€ por fracción</label>
              <input v-model.number="form.price_per_fraction" type="number" step="0.01" min="0" required class="input" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <!--
                "Minutos por fracción" y no "Minutos/fracción": la barra
                hacía de todo el texto un único token sin espacios (98 px)
                que no cabía en la caja de la etiqueta (86 px) con una
                ventana de 1024 px, y se salía de la columna.
              -->
              <label class="block text-xs font-medium text-slate-700">Minutos por fracción</label>
              <input v-model.number="form.fraction_minutes" type="number" min="1" max="60" required class="input" />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700">Máx. diario (€)</label>
              <input v-model.number="form.max_daily" type="number" step="0.01" min="0" class="input" placeholder="Sin tope" />
            </div>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Vigente desde</label>
            <input v-model="form.valid_from" type="datetime-local" required class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Vigente hasta (opcional)</label>
            <input v-model="form.valid_to" type="datetime-local" class="input" />
          </div>
          <div class="flex gap-2 pt-2">
            <button type="submit" class="btn-primary" :disabled="!parkingId">
              {{ editing ? 'Guardar cambios' : 'Crear tarifa' }}
            </button>
            <button v-if="editing" type="button" class="btn-secondary" @click="startCreate">
              Cancelar
            </button>
          </div>
        </form>
      </div>
    </div>
  </AppLayout>
</template>