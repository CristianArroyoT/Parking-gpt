<script setup lang="ts">
/**
 * Modal de incidentes del operador (sprint 2026-06-30).
 *
 * T-21 (plan maestro 2026-10-21): el operador puede adjuntar **hasta 3
 * fotos** al reportar. El fichero sube de verdad al backend
 * (`POST /api/v1/incidents/{id}/attachments`), que valida los **bytes**
 * (no la extensión), lo guarda en un volumen local y deja sólo la
 * metadata en la base de datos.
 *
 * Decisión D5: los adjuntos **no se exponen a ningún canal externo** y
 * sólo los ven el **gestor** y el **admin** de esa sucursal. El
 * operador que los sube no puede volver a listarlos: por eso, cuando el
 * usuario no es gestor/admin, la vista muestra un aviso en lugar de las
 * miniaturas.
 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { createIncident } from '@/api/incidents'
import { getAccessToken, http } from '@/api/client'
import type {
  IncidentKind,
  IncidentReason,
  IncidentCreatePayload,
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

interface Space {
  id: number
  parking_id: number
  lane: string
  number: string
  is_active?: boolean
  is_broken?: boolean
}

/** Adjunto ya subido (metadata que devuelve la API). */
interface IncidentAttachment {
  id: number
  alert_id: number
  original_filename: string
  mime_type: string
  size_bytes: number
  thumbnail_url: string
  download_url: string
  expires_at: string | null
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
const auth = useAuthStore()
const submitting = ref(false)
const errorMsg = ref<string | null>(null)

type Tab = 'broken' | 'robery' | 'unbroken'
const activeTab = ref<Tab>('broken')

/** Límites (los mismos que aplica el backend). */
const MAX_FOTOS = 3
const MAX_BYTES = 10 * 1024 * 1024

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
})

/** Ficheros elegidos (aún no subidos). */
const selected = ref<File[]>([])
/** Previsualización local (object URLs). */
const previews = ref<string[]>([])
/** Adjuntos ya subidos y aceptados por el backend. */
const uploaded = ref<IncidentAttachment[]>([])

const availableSpaces = computed(() => props.spaces.filter((s) => s.is_active !== false))

/** Sólo gestor y admin ven las fotos del incidente (decisión D5). */
const puedeVerAdjuntos = computed(
  () => auth.role === 'admin' || auth.role === 'gestor',
)

const kindForTab: Record<Tab, IncidentKind> = {
  broken: 'space_broken',
  robery: 'robery_reported',
  unbroken: 'space_unbroken',
}

function limpiarPreviews(): void {
  previews.value.forEach((url) => URL.revokeObjectURL(url))
  previews.value = []
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
    selected.value = []
    uploaded.value = []
    limpiarPreviews()
  }
})

onBeforeUnmount(() => {
  limpiarPreviews()
})

/** Elige hasta 3 fotos y muestra su previsualización local. */
function onFilesChosen(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  limpiarPreviews()
  selected.value = []

  if (files.length > MAX_FOTOS) {
    errorMsg.value = `Máximo ${MAX_FOTOS} fotos por incidente`
    input.value = ''
    return
  }
  const demasiadoGrande = files.find((f) => f.size > MAX_BYTES)
  if (demasiadoGrande) {
    errorMsg.value = `La foto «${demasiadoGrande.name}» supera el tamaño máximo (10 MB)`
    input.value = ''
    return
  }
  selected.value = files
  previews.value = files.map((f) => URL.createObjectURL(f))
}

/** Sube las fotos al incidente ya creado. */
async function subirFotos(alertId: number): Promise<void> {
  if (!selected.value.length) return
  const formData = new FormData()
  selected.value.forEach((f) => formData.append('files', f, f.name))
  const { data } = await http.post<IncidentAttachment[]>(
    `/incidents/${alertId}/attachments`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  uploaded.value = data
}

/**
 * Las miniaturas y las descargas van en un <img>/<a>, que no pueden
 * mandar la cabecera Authorization: se les pasa el token por query
 * (mismo patrón que el preview MJPEG y el stream SSE del backend).
 */
function urlConToken(ruta: string): string {
  const token = getAccessToken()
  return token ? `${ruta}?token=${encodeURIComponent(token)}` : ruta
}

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
    // Se conservan los nombres en el audit log (no los binarios).
    payload.photos = selected.value.map((f) => f.name)
  }

  submitting.value = true
  errorMsg.value = null
  try {
    const result = await createIncident(props.parkingId, payload)
    if (result.noop) {
      ui.pushToast('info', result.detail ?? 'Sin cambios')
      emit('success')
      emit('close')
      return
    }

    const alertId = result.alert?.id
    if (alertId && selected.value.length) {
      try {
        await subirFotos(alertId)
      } catch (err: unknown) {
        // El incidente YA está creado: la foto fallida no lo invalida.
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'No se pudieron subir las fotos.'
        errorMsg.value = detail
        ui.pushToast('error', detail)
      }
    }

    const label =
      activeTab.value === 'broken' ? 'Plaza marcada como averiada' :
      activeTab.value === 'unbroken' ? 'Plaza rehabilitada' :
      'Reporte de robo enviado'
    ui.pushToast('success', label)
    emit('success')

    if (uploaded.value.length) {
      // Con fotos, el modal se queda abierto para mostrar las
      // miniaturas y la descarga (o el aviso de D5).
      selected.value = []
      limpiarPreviews()
    } else {
      emit('close')
    }
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
        </template>

        <div>
          <label class="block text-xs font-medium text-slate-700 mb-1">
            Fotos (máx. {{ MAX_FOTOS }})
          </label>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            class="input text-sm"
            :disabled="submitting"
            @change="onFilesChosen"
          />
          <p class="text-xs text-slate-500 mt-1">
            Sólo JPEG, PNG o WebP, hasta {{ MAX_FOTOS }} fotos y 10 MB por
            foto. El backend comprueba el contenido real del fichero, no
            su extensión.
          </p>
          <ul v-if="previews.length" class="mt-2 grid grid-cols-3 gap-2">
            <li v-for="(url, i) in previews" :key="url">
              <img
                :src="url"
                :alt="`Foto ${i + 1}`"
                class="w-full h-20 object-cover rounded-lg border border-slate-200"
              />
              <span class="block text-[10px] text-slate-600 truncate">
                {{ selected[i]?.name }}
              </span>
            </li>
          </ul>
        </div>

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
          <!-- T-169 (2026-10-24): el error se ANUNCIA (`role="alert"` =
               region viva). Antes solo se veia. -->
          <p class="text-sm text-rose-800" role="alert" aria-live="assertive">
            {{ errorMsg }}
          </p>
        </div>

        <div
          v-if="uploaded.length"
          class="bg-emerald-50 border border-emerald-200 rounded-lg p-3 space-y-2"
        >
          <p class="text-sm text-emerald-800">
            Incidente registrado con {{ uploaded.length }} foto(s).
          </p>
          <div v-if="puedeVerAdjuntos" class="grid grid-cols-3 gap-2">
            <a
              v-for="att in uploaded"
              :key="att.id"
              :href="urlConToken(att.download_url)"
              :title="att.original_filename"
              class="block"
            >
              <img
                :src="urlConToken(att.thumbnail_url)"
                :alt="att.original_filename"
                class="w-full h-20 object-cover rounded-lg border border-slate-200"
              />
              <span class="block text-[10px] text-slate-600 truncate">
                {{ att.original_filename }}
              </span>
            </a>
          </div>
          <p v-else class="text-xs text-emerald-800">
            Las fotos quedan almacenadas, pero sólo el gestor y el admin de
            la sucursal pueden verlas o descargarlas.
          </p>
        </div>
      </div>

      <footer class="px-6 py-4 border-t border-slate-200 flex gap-3 justify-end">
        <button
          type="button"
          class="btn-secondary"
          :disabled="submitting"
          @click="close"
        >{{ uploaded.length ? 'Cerrar' : 'Cancelar' }}</button>
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
