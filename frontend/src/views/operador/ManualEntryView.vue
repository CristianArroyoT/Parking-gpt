<script setup lang="ts">
/**
 * Alta manual del operador (sprint 2026-06-30).
 *
 * Permite al operador registrar una ENTRADA o SALIDA cuando la cámara
 * cae o el OCR falla. Llama ``POST /api/v1/tickets/manual``.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { createManualTicket } from '@/api/manualEntries'
import type {
  ManualEntryPayload,
  ManualEntryReason,
  TicketDirection,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string }
interface Camera { id: number; code: string; parking_id: number }
interface Space { id: number; parking_id: number; lane: string; number: string }

const ui = useUiStore()
const router = useRouter()

const parkings = ref<Parking[]>([])
const cameras = ref<Camera[]>([])
const spaces = ref<Space[]>([])
const loading = ref(true)
const submitting = ref(false)
const lastError = ref<string | null>(null)

const form = reactive({
  parkingId: 0,
  cameraId: null as number | null,
  spaceId: null as number | null,
  plateDigits: '',
  plateLetters: '',
  reason: 'camera_down' as ManualEntryReason,
  direction: 'entry' as TicketDirection,
  notes: '',
})

const REASONS: { value: ManualEntryReason; label: string; emoji: string }[] = [
  { value: 'camera_down', label: 'Cámara caída', emoji: '📷' },
  { value: 'ocr_failed', label: 'OCR fallido', emoji: '🔎' },
  { value: 'other', label: 'Otro', emoji: '✍️' },
]

const plateFull = computed(() =>
  `${form.plateDigits}${form.plateLetters}`.toUpperCase(),
)

const validPlate = computed(() =>
  /^\d{4}[A-Z]{3}$/.test(plateFull.value),
)

const selectedParking = computed(
  () => parkings.value.find((p) => p.id === form.parkingId) ?? null,
)

async function loadParkings(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (!form.parkingId && data.length) {
      form.parkingId = data[0].id
    }
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
}

async function loadParkingContext(parkingId: number): Promise<void> {
  if (!parkingId) return
  try {
    const [cams, spcs] = await Promise.all([
      http.get<Camera[]>(`/parkings/${parkingId}/cameras`),
      http.get<Space[]>(`/parkings/${parkingId}/spaces`),
    ])
    cameras.value = cams.data
    spaces.value = spcs.data
    form.cameraId = null
    form.spaceId = null
  } catch {
    cameras.value = []
    spaces.value = []
  }
}

watch(
  () => form.parkingId,
  (id) => loadParkingContext(id),
)

async function submit(): Promise<void> {
  lastError.value = null
  if (!validPlate.value) {
    lastError.value = 'La matrícula debe tener 4 dígitos seguidos de 3 letras.'
    return
  }
  if (!form.parkingId) {
    lastError.value = 'Selecciona una sucursal.'
    return
  }
  const payload: ManualEntryPayload = {
    plate: plateFull.value,
    direction: form.direction,
    parking_id: form.parkingId,
    parking_space_id: form.spaceId,
    reason: form.reason,
    notes: form.notes || null,
    camera_id: form.cameraId,
  }
  submitting.value = true
  try {
    await createManualTicket(payload)
    ui.pushToast(
      'success',
      form.direction === 'entry'
        ? `Entrada manual registrada: ${plateFull.value}`
        : `Salida manual registrada: ${plateFull.value}`,
    )
    router.push('/vivo')
  } catch (err: unknown) {
    const detail =
      (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
      'No se pudo registrar la alta manual.'
    lastError.value = detail
    ui.pushToast('error', detail)
  } finally {
    submitting.value = false
  }
}

onMounted(loadParkings)
</script>

<template>
  <AppLayout>
    <div class="mb-6">
      <h1 class="text-2xl font-semibold tracking-tight">Alta manual</h1>
      <p class="mt-1 text-sm text-slate-500">
        Registra entradas o salidas cuando la cámara está caída o el OCR
        no detecta la matrícula. La acción queda auditada.
      </p>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <form
      v-else
      class="grid grid-cols-1 lg:grid-cols-3 gap-6"
      @submit.prevent="submit"
    >
      <div class="lg:col-span-2 space-y-6">
        <div class="bg-white rounded-xl shadow-card p-1 inline-flex">
          <button
            type="button"
            class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            :class="
              form.direction === 'entry'
                ? 'bg-emerald-600 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            "
            @click="form.direction = 'entry'"
          >
            Entrada
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            :class="
              form.direction === 'exit'
                ? 'bg-rose-600 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            "
            @click="form.direction = 'exit'"
          >
            Salida
          </button>
        </div>

        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Motivo</h2>
          <div class="grid grid-cols-3 gap-3">
            <label
              v-for="r in REASONS"
              :key="r.value"
              class="flex items-start gap-3 p-4 border rounded-lg cursor-pointer transition-colors"
              :class="
                form.reason === r.value
                  ? 'border-blue-600 bg-blue-50'
                  : 'border-slate-200 hover:border-slate-400'
              "
            >
              <input
                v-model="form.reason"
                type="radio"
                :value="r.value"
                class="mt-1"
              />
              <span class="flex-1">
                <span class="block text-lg leading-none">{{ r.emoji }}</span>
                <span class="block font-medium text-sm mt-1">{{ r.label }}</span>
              </span>
            </label>
          </div>
        </div>

        <div class="bg-white rounded-xl shadow-card p-5 space-y-4">
          <h2 class="font-semibold">Sucursal, cámara y plaza</h2>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">
              Sucursal
            </label>
            <select v-model.number="form.parkingId" class="input">
              <option v-for="p in parkings" :key="p.id" :value="p.id">
                {{ p.name }}
              </option>
            </select>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1">
                Cámara (opcional)
              </label>
              <select v-model.number="form.cameraId" class="input">
                <option :value="null">— Sin asignar —</option>
                <option v-for="c in cameras" :key="c.id" :value="c.id">
                  {{ c.code }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1">
                Plaza (opcional)
              </label>
              <select v-model.number="form.spaceId" class="input">
                <option :value="null">— Sin asignar —</option>
                <option v-for="s in spaces" :key="s.id" :value="s.id">
                  {{ s.lane }}-{{ s.number }}
                </option>
              </select>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Matrícula</h2>
          <div class="flex items-center gap-3">
            <input
              v-model="form.plateDigits"
              type="text"
              inputmode="numeric"
              maxlength="4"
              placeholder="0000"
              class="input w-24 text-center font-mono tracking-widest uppercase"
            />
            <span class="text-2xl text-slate-400">·</span>
            <input
              v-model="form.plateLetters"
              type="text"
              maxlength="3"
              placeholder="ABC"
              class="input w-24 text-center font-mono tracking-widest uppercase"
            />
            <span
              v-if="plateFull && !validPlate"
              class="text-xs text-rose-600"
            >
              Formato: 4 dígitos + 3 letras.
            </span>
          </div>
        </div>

        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Notas</h2>
          <textarea
            v-model="form.notes"
            rows="3"
            maxlength="500"
            class="input"
            placeholder="Contexto adicional para auditoría (opcional)"
          />
        </div>

        <div v-if="lastError" class="bg-rose-50 border border-rose-200 rounded-xl p-4">
          <!-- T-169 (2026-10-24): el error se ANUNCIA (`role="alert"`
               = region viva). Antes solo se veia: un lector de pantalla
               no enteraba de que el alta manual habia fallado. -->
          <p class="text-sm text-rose-800" role="alert" aria-live="assertive">
            {{ lastError }}
          </p>
        </div>
      </div>

      <aside class="space-y-4">
        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">Vista previa</h2>
          <dl class="text-sm space-y-2">
            <div class="flex justify-between">
              <dt class="text-slate-500">Dirección</dt>
              <dd
                class="font-medium"
                :class="form.direction === 'entry' ? 'text-emerald-700' : 'text-rose-700'"
              >
                {{ form.direction === 'entry' ? 'Entrada' : 'Salida' }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">Sucursal</dt>
              <dd class="font-medium">{{ selectedParking?.name ?? '—' }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">Plaza</dt>
              <dd class="font-medium">
                {{ form.spaceId
                  ? spaces.find((s) => s.id === form.spaceId)?.lane + '-' +
                    spaces.find((s) => s.id === form.spaceId)?.number
                  : '—' }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">Matrícula</dt>
              <dd class="font-mono font-semibold">{{ plateFull || '—' }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">Motivo</dt>
              <dd class="font-medium">
                {{ REASONS.find((r) => r.value === form.reason)?.label }}
              </dd>
            </div>
            <div class="pt-2 border-t border-slate-100">
              <dt class="text-slate-500 text-xs uppercase tracking-wide mb-1">
                Origen
              </dt>
              <dd>
                <span class="inline-block px-2 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">
                  ⚠ Manual
                </span>
              </dd>
            </div>
          </dl>
        </div>

        <button
          type="submit"
          :disabled="submitting || !validPlate"
          class="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ submitting
            ? 'Registrando…'
            : form.direction === 'entry'
              ? 'Crear entrada manual'
              : 'Crear salida manual' }}
        </button>
        <button
          type="button"
          class="btn-secondary w-full"
          @click="router.push('/vivo')"
        >
          Cancelar
        </button>
      </aside>
    </form>
  </AppLayout>
</template>