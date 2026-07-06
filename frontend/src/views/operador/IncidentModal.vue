<script setup lang="ts">
/**
 * Modal de incidentes del operador (sprint 2026-06-30).
 */
import { computed, reactive, ref, watch } from 'vue'
import { createIncident } from '@/api/incidents'
import type {
  IncidentKind,
  IncidentReason,
  IncidentCreatePayload,
} from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Space {
  id: number
  parking_id: number
  lane: string
  number: string
  is_active?: boolean
  is_broken?: boolean
}

const props = defineProps<{
  open: boolean
  parkingId: number
  spaces: Space[]
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success'): void
}>()

const ui = useUiStore()
const submitting = ref(false)
const errorMsg = ref<string | null>(null)

type Tab = 'broken' | 'robery' | 'unbroken'
const activeTab = ref<Tab>('broken')

const SPACE_REASONS: { value: IncidentReason; label: string }[] = [
  { value: 'physical_damage', label: 'Daño físico' },
  { value: 'paint', label: 'Pintura / señalización' },
  { value: 'sensor_failure', label: 'Sensor / barrera' },
  { value: 'other', label: 'Otro' },
]
const ROBERY_REASONS: { value: IncidentReason; label: string }[] = [
  { value: 'theft_attempt', label: 'Intento de robo' },
  { value: 'suspicious_behavior', label: 'Comportamiento sospechoso' },
  { value: 'other', label: 'Otro' },
]

const form = reactive({
  spaceId: null as number | null,
  reason: 'physical_damage' as IncidentReason,
  notes: '',
  plate: '',
  photos: ['', '', ''] as string[],
})

const availableSpaces = computed(() => props.spaces.filter((s) => s.is_active !== false))

const kindForTab: Record<Tab, IncidentKind> = {
  broken: 'space_broken',
  robery: 'robery_reported',
  unbroken: 'space_unbroken',
}

watch(() => props.open, (v) => {
  if (v) {
    errorMsg.value = null
    submitting.value = false
    activeTab.value = 'broken'
    form.spaceId = availableSpaces.value[0]?.id ?? null
    form.reason = 'physical_damage'
    form.notes = ''
    form.plate = ''
    form.photos = ['', '', '']
  }
})

async function submit(): Promise<void> {
  if (!props.parkingId) {
    errorMsg.value = 'Sin sucursal activa'
    return
  }
  const kind = kindForTab[activeTab.value]
  const payload: IncidentCreatePayload = {
    kind,
    reason: form.reason,
    notes: form.notes || null,
  }

  if (activeTab.value !== 'robery') {
    if (form.spaceId === null) {
      errorMsg.value = 'Selecciona una plaza'
      return
    }
    payload.parking_space_id = form.spaceId
  } else {
    payload.plate = form.plate || null
    payload.photos = form.photos.map((p) => p.trim()).filter((p) => p.length > 0)
  }

  submitting.value = true
  errorMsg.value = null
  try {
    const result = await createIncident(props.parkingId, payload)
    if (result.noop) {
      ui.pushToast('info', result.detail ?? 'Sin cambios')
    } else {
      const label =
        activeTab.value === 'broken' ? 'Plaza marcada como averiada' :
        activeTab.value === 'unbroken' ? 'Plaza rehabilitada' :
        'Reporte de robo enviado'
      ui.pushToast('success', label)
    }
    emit('success')
    emit('close')
  } catch (err: unknown) {
    const detail =
      (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
      'No se pudo registrar el incidente.'
    errorMsg.value = detail
    ui.pushToast('error', detail)
  } finally {
    submitting.value = false
  }
}

function close(): void {
  if (!submitting.value) emit('close')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4"
    @click.self="close"
  >
    <div class="bg-white rounded-xl shadow-card max-w-2xl w-full max-h-[90vh] overflow-y-auto">
      <header class="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
        <h2 class="font-semibold text-lg">Reportar incidente</h2>
        <button
          type="button"
          class="text-slate-400 hover:text-slate-700"
          aria-label="Cerrar"
          @click="close"
        >✕</button>
      </header>

      <div class="p-6 space-y-5">
        <div class="bg-slate-100 rounded-lg p-1 inline-flex flex-wrap">
          <button
            type="button"
            class="px-3 py-1.5 rounded-md text-sm font-medium"
            :class="activeTab === 'broken' ? 'bg-amber-600 text-white' : 'text-slate-600'"
            @click="activeTab = 'broken'"
          >🛠 Averiada</button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-md text-sm font-medium"
            :class="activeTab === 'robery' ? 'bg-rose-700 text-white' : 'text-slate-600'"
            @click="activeTab = 'robery'"
          >🚨 Robo</button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-md text-sm font-medium"
            :class="activeTab === 'unbroken' ? 'bg-emerald-600 text-white' : 'text-slate-600'"
            @click="activeTab = 'unbroken'"
          >✅ Rehabilitar</button>
        </div>

        <template v-if="activeTab !== 'robery'">
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">Plaza</label>
            <select v-model.number="form.spaceId" class="input">
              <option v-for="s in availableSpaces" :key="s.id" :value="s.id">
                {{ s.lane }}-{{ s.number }}{{ s.is_broken ? ' (averiada)' : '' }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">Motivo</label>
            <select v-model="form.reason" class="input">
              <option v-for="r in SPACE_REASONS" :key="r.value" :value="r.value">
                {{ r.label }}
              </option>
            </select>
          </div>
        </template>

        <template v-else>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">
              Plaza (opcional)
            </label>
            <select v-model.number="form.spaceId" class="input">
              <option :value="null">— No determinada —</option>
              <option v-for="s in availableSpaces" :key="s.id" :value="s.id">
                {{ s.lane }}-{{ s.number }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">Motivo</label>
            <select v-model="form.reason" class="input">
              <option v-for="r in ROBERY_REASONS" :key="r.value" :value="r.value">
                {{ r.label }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">
              Matrícula (opcional)
            </label>
            <input
              v-model="form.plate"
              type="text"
              maxlength="16"
              placeholder="0000-ABC"
              class="input font-mono uppercase tracking-widest"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700 mb-1">
              Fotos (nombres de archivo, máx. 3)
            </label>
            <div class="space-y-2">
              <input
                v-for="(_, i) in form.photos"
                :key="i"
                v-model="form.photos[i]"
                type="text"
                :placeholder="`foto-${i + 1}.jpg`"
                class="input font-mono text-sm"
              />
            </div>
            <p class="text-xs text-slate-500 mt-1">
              MVP: el archivo no se sube. El nombre se persiste en el audit log.
            </p>
          </div>
        </template>

        <div>
          <label class="block text-xs font-medium text-slate-700 mb-1">Notas</label>
          <textarea
            v-model="form.notes"
            rows="3"
            maxlength="500"
            class="input"
            placeholder="Contexto adicional (opcional)"
          />
        </div>

        <div
          v-if="errorMsg"
          class="bg-rose-50 border border-rose-200 rounded-lg p-3"
        >
          <p class="text-sm text-rose-800">{{ errorMsg }}</p>
        </div>
      </div>

      <footer class="px-6 py-4 border-t border-slate-200 flex gap-3 justify-end">
        <button
          type="button"
          class="btn-secondary"
          :disabled="submitting"
          @click="close"
        >Cancelar</button>
        <button
          type="button"
          class="btn-primary"
          :disabled="submitting"
          @click="submit"
        >{{ submitting ? 'Enviando…' : 'Registrar incidente' }}</button>
      </footer>
    </div>
  </div>
</template>