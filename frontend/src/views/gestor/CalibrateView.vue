<script setup lang="ts">
/**
 * Calibración de geocercas para una cámara.
 *
 * El backend (commit 13fe714, routers en app/api/v1/cameras.py) expone:
 *   GET    /parkings/{parking_id}/cameras/{camera_id}/geofences
 *   POST   /parkings/{parking_id}/cameras/{camera_id}/geofences
 *   PATCH  /parkings/{parking_id}/cameras/{camera_id}/geofences/{fence_id}
 * (sin DELETE en MVP — la reasignación de plaza obliga a crear otra).
 *
 * Interacción: en modo "Crear", el usuario hace click-drag sobre el SVG
 * para dibujar un rectángulo; al soltar se abre el formulario lateral
 * con la plaza a asignar y el umbral de confianza. En modo "Seleccionar"
 * se hace click en un rectángulo existente para ver sus datos (PATCH).
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface ParkingSpace { id: number; lane: string; number: string; is_active: boolean }
interface Geofence {
  id: number; camera_id: number; parking_space_id: number
  x: number; y: number; w: number; h: number
  confidence_threshold: number; created_at: string; updated_at: string
  direction: 'entry' | 'exit'
}
interface Camera { id: number; code: string; name: string; rtsp_url: string }
// Sprint Camera Health (2026-07-01): respuesta de
// GET /parkings/{parking_id}/cameras/{camera_id}/health
type HealthStatus = 'never_probed' | 'healthy' | 'degraded' | 'offline'
interface CameraHealth {
  camera_id: number
  status: HealthStatus
  last_heartbeat_at: string | null
  last_heartbeat_ok: boolean | null
  consecutive_failures: number
  stale_threshold_seconds: number
}
type Direction = 'entry' | 'exit'

const route = useRoute()
const ui = useUiStore()
const parkingId = computed(() => Number(route.params.parkingId))
const cameraId = computed(() => Number(route.params.cameraId))

const SVG_W = 960
const SVG_H = 540

const camera = ref<Camera | null>(null)
const spaces = ref<ParkingSpace[]>([])
const geofences = ref<Geofence[]>([])
const loading = ref(true)

type Mode = 'create' | 'select'
const mode = ref<Mode>('create')

interface Draft { x: number; y: number; w: number; h: number }
const draft = ref<Draft | null>(null)
const drawing = ref(false)
const form = reactive({
  parking_space_id: null as number | null,
  confidence_threshold: 0.85,
  direction: 'entry' as Direction,
})
const selectedId = ref<number | null>(null)

// ── Camera Health (sprint 2026-07-01) ────────────────────────────
const health = ref<CameraHealth | null>(null)
let healthPoll: number | null = null
const HEALTH_POLL_MS = 15000

async function loadHealth(): Promise<void> {
  try {
    const { data } = await http.get<CameraHealth>(
      `/parkings/${parkingId.value}/cameras/${cameraId.value}/health`,
    )
    health.value = data
  } catch {
    // No hacer toast en cada poll — el siguiente intento actualizará
    // el estado. Si la cámara no tiene permisos (403), el badge
    // simplemente no aparece (health queda en null).
  }
}

const spacesById = computed(() => new Map(spaces.value.map((s) => [s.id, s])))

async function loadCamera(): Promise<void> {
  const { data } = await http.get<Camera[]>(`/parkings/${parkingId.value}/cameras`)
  camera.value = data.find((c) => c.id === cameraId.value) ?? null
}
async function loadSpaces(): Promise<void> {
  const { data } = await http.get<ParkingSpace[]>(`/parkings/${parkingId.value}/spaces`)
  spaces.value = data
}
async function loadGeofences(): Promise<void> {
  const { data } = await http.get<Geofence[]>(
    `/parkings/${parkingId.value}/cameras/${cameraId.value}/geofences`,
  )
  geofences.value = data
}

onMounted(async () => {
  try {
    await Promise.all([loadCamera(), loadSpaces(), loadGeofences(), loadHealth()])
  } catch {
    ui.pushToast('error', 'No se pudieron cargar los datos de la cámara')
  } finally {
    loading.value = false
  }
  // Polling ligero del endpoint /health cada 15 s. Patrón idéntico al
  // usado en MapView.vue (setInterval + cleanup en onBeforeUnmount).
  healthPoll = window.setInterval(loadHealth, HEALTH_POLL_MS)
})

onBeforeUnmount(() => {
  if (healthPoll !== null) {
    window.clearInterval(healthPoll)
    healthPoll = null
  }
})

watch([parkingId, cameraId], async () => {
  loading.value = true
  selectedId.value = null
  draft.value = null
  try {
    await Promise.all([loadCamera(), loadGeofences(), loadHealth()])
  } catch {
    ui.pushToast('error', 'Error al recargar la cámara')
  } finally {
    loading.value = false
  }
})

// ── Drag-create ───────────────────────────────────────────────────────
const svgRef = ref<SVGSVGElement | null>(null)

function svgPoint(evt: MouseEvent): { x: number; y: number } {
  const svg = svgRef.value
  if (!svg) return { x: 0, y: 0 }
  const r = svg.getBoundingClientRect()
  const x = ((evt.clientX - r.left) / r.width) * SVG_W
  const y = ((evt.clientY - r.top) / r.height) * SVG_H
  return { x: Math.max(0, Math.min(SVG_W, x)), y: Math.max(0, Math.min(SVG_H, y)) }
}
function onMouseDown(evt: MouseEvent): void {
  if (mode.value !== 'create') return
  if ((evt.target as Element).tagName === 'rect' && (evt.target as Element).hasAttribute('data-fence')) return
  const { x, y } = svgPoint(evt)
  drawing.value = true
  draft.value = { x, y, w: 0, h: 0 }
}
function onMouseMove(evt: MouseEvent): void {
  if (!drawing.value || !draft.value) return
  const { x, y } = svgPoint(evt)
  draft.value = {
    x: Math.min(draft.value.x, x),
    y: Math.min(draft.value.y, y),
    w: Math.abs(x - draft.value.x),
    h: Math.abs(y - draft.value.y),
  }
}
function onMouseUp(): void {
  if (!drawing.value || !draft.value) return
  drawing.value = false
  // Si el rect es diminuto, lo descartamos (probable click sin drag).
  if (draft.value.w < 8 || draft.value.h < 8) {
    draft.value = null
    return
  }
  // Pre-selecciona la primera plaza libre (sin geocerca activa) si existe.
  const used = new Set(geofences.value.map((g) => g.parking_space_id))
  const free = spaces.value.find((s) => s.is_active && !used.has(s.id))
  form.parking_space_id = free ? free.id : null
  form.confidence_threshold = 0.85
  form.direction = 'entry'
}
function cancelDraft(): void {
  draft.value = null
}
async function saveDraft(): Promise<void> {
  if (!draft.value || form.parking_space_id === null) return
  try {
    await http.post(
      `/parkings/${parkingId.value}/cameras/${cameraId.value}/geofences`,
      {
        parking_space_id: form.parking_space_id,
        x: round(draft.value.x),
        y: round(draft.value.y),
        w: round(draft.value.w),
        h: round(draft.value.h),
        confidence_threshold: form.confidence_threshold,
        direction: form.direction,
      },
    )
    ui.pushToast('success', 'Geocerca creada')
    draft.value = null
    await loadGeofences()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo guardar la geocerca'))
  }
}

function round(v: number): number { return Math.round(v * 10) / 10 }

function selectFence(id: number): void {
  if (mode.value !== 'select') return
  selectedId.value = selectedId.value === id ? null : id
}
async function updateConfidence(fence: Geofence, value: number): Promise<void> {
  try {
    await http.patch(
      `/parkings/${parkingId.value}/cameras/${cameraId.value}/geofences/${fence.id}`,
      { confidence_threshold: value },
    )
    fence.confidence_threshold = value
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo actualizar la geocerca'))
  }
}
async function updateDirection(fence: Geofence, value: Direction): Promise<void> {
  if (fence.direction === value) return
  try {
    await http.patch(
      `/parkings/${parkingId.value}/cameras/${cameraId.value}/geofences/${fence.id}`,
      { direction: value },
    )
    fence.direction = value
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo actualizar la dirección'))
  }
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

function fenceLabel(g: Geofence): string {
  const s = spacesById.value.get(g.parking_space_id)
  return s ? `${s.lane}-${s.number}` : `Plaza #${g.parking_space_id}`
}
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <div class="text-xs text-slate-500">
          <RouterLink to="/cameras" class="hover:underline">Cámaras</RouterLink>
          · <span>{{ camera?.name ?? 'Cargando…' }}</span>
        </div>
        <h1 class="text-2xl font-semibold tracking-tight">
          Calibrar cámara
          <span class="font-mono text-slate-700">{{ camera?.code ?? '' }}</span>
        </h1>
        <p class="text-sm text-slate-500">
          Dibuja rectángulos sobre la imagen y asígnalos a plazas de la sucursal.
        </p>
      </div>

      <!-- Sprint Camera Health (2026-07-01): badge de salud -->
      <span
        v-if="health"
        class="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium"
        :class="{
          'bg-slate-100 text-slate-700': health.status === 'never_probed',
          'bg-emerald-100 text-emerald-700': health.status === 'healthy',
          'bg-amber-100 text-amber-700': health.status === 'degraded',
          'bg-rose-100 text-rose-700': health.status === 'offline',
        }"
        :title="health.last_heartbeat_at
          ? new Date(health.last_heartbeat_at).toLocaleString('es-ES')
          : 'Nunca se ha probado esta cámara'"
      >
        <span class="h-2 w-2 rounded-full" :class="{
          'bg-slate-400': health.status === 'never_probed',
          'bg-emerald-500': health.status === 'healthy',
          'bg-amber-500': health.status === 'degraded',
          'bg-rose-500': health.status === 'offline',
        }" />
        <template v-if="health.status === 'never_probed'">Nunca probada</template>
        <template v-else-if="health.status === 'healthy'">En línea</template>
        <template v-else-if="health.status === 'degraded'">Sin actualización reciente</template>
        <template v-else>Cámara caída</template>
        <span v-if="health.consecutive_failures > 0" class="text-rose-700">
          · {{ health.consecutive_failures }} fallo(s)
        </span>
      </span>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <div v-else class="grid grid-cols-1 xl:grid-cols-3 gap-6">
      <div class="xl:col-span-2 bg-white rounded-xl shadow-card p-5">
        <div class="flex items-center justify-between mb-3 text-sm">
          <span class="inline-flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-emerald-500" />
            <span>{{ geofences.length }} geocercas activas</span>
          </span>
          <div class="flex items-center gap-2 text-xs">
            <button
              type="button"
              :class="['px-2 py-1 rounded border', mode === 'create' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white']"
              @click="mode = 'create'"
            >Crear</button>
            <button
              type="button"
              :class="['px-2 py-1 rounded border', mode === 'select' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white']"
              @click="mode = 'select'"
            >Seleccionar</button>
          </div>
        </div>

        <div
          class="relative w-full aspect-video bg-slate-900 rounded-lg overflow-hidden select-none"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseUp"
        >
          <svg
            ref="svgRef"
            viewBox="0 0 960 540"
            preserveAspectRatio="xMidYMid slice"
            class="absolute inset-0 w-full h-full"
            @mousedown="onMouseDown"
          >
            <defs>
              <linearGradient id="frame-bg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#1e293b" />
                <stop offset="1" stop-color="#0f172a" />
              </linearGradient>
            </defs>
            <rect width="960" height="540" fill="url(#frame-bg)" />
            <rect x="40" y="40" width="880" height="460" fill="#1f2937" stroke="#334155" />
            <text x="480" y="280" text-anchor="middle" fill="#475569" font-size="20" font-family="Inter, sans-serif">
              {{ camera?.rtsp_url ?? 'Sin stream' }}
            </text>

            <rect
              v-for="g in geofences"
              :key="g.id"
              :x="g.x" :y="g.y" :width="g.w" :height="g.h"
              :stroke="selectedId === g.id ? '#f59e0b' : '#2563eb'"
              :stroke-width="selectedId === g.id ? 3 : 2"
              fill="rgba(37,99,235,.10)"
              data-fence
              class="cursor-pointer"
              @click.stop="selectFence(g.id)"
            />
            <text
              v-for="g in geofences"
              :key="`label-${g.id}`"
              :x="g.x + 6"
              :y="g.y + 16"
              fill="#fff"
              font-size="14"
              font-family="Inter, sans-serif"
              font-weight="600"
              style="pointer-events: none;"
            >{{ fenceLabel(g) }}</text>

            <rect
              v-if="draft"
              :x="draft.x" :y="draft.y" :width="draft.w" :height="draft.h"
              stroke="#10b981"
              stroke-width="2"
              stroke-dasharray="6 4"
              fill="rgba(16,185,129,.10)"
            />
          </svg>

          <div class="absolute right-4 bottom-4 bg-slate-900/80 text-white text-xs px-2 py-1 rounded">
            Modo: <span class="font-medium">{{ mode === 'create' ? 'Crear geocerca' : 'Seleccionar' }}</span>
          </div>
        </div>

        <p class="mt-3 text-xs text-slate-500">
          Tip: en modo Crear, haz click y arrastra sobre el área. La plaza asignada se elige en el panel lateral.
        </p>
      </div>

      <aside class="space-y-4">
        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-3">
            {{ draft ? 'Nueva geocerca' : (selectedId ? 'Geocerca seleccionada' : 'Sin selección') }}
          </h2>

          <div v-if="draft" class="space-y-3 text-sm">
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div><span class="text-slate-500">x</span> <span class="font-mono">{{ Math.round(draft.x) }}</span></div>
              <div><span class="text-slate-500">y</span> <span class="font-mono">{{ Math.round(draft.y) }}</span></div>
              <div><span class="text-slate-500">ancho</span> <span class="font-mono">{{ Math.round(draft.w) }}</span></div>
              <div><span class="text-slate-500">alto</span> <span class="font-mono">{{ Math.round(draft.h) }}</span></div>
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Plaza a asignar</label>
              <select v-model.number="form.parking_space_id" class="input">
                <option :value="null" disabled>Selecciona plaza…</option>
                <option v-for="s in spaces" :key="s.id" :value="s.id">
                  {{ s.lane }}-{{ s.number }} {{ s.is_active ? '' : '(inactiva)' }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Umbral de confianza</label>
              <div class="flex items-center gap-3">
                <input v-model.number="form.confidence_threshold" type="range" min="0" max="1" step="0.01" class="flex-1" />
                <span class="text-sm font-mono w-12 text-right">{{ Math.round(form.confidence_threshold * 100) }} %</span>
              </div>
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Dirección de la cámara</label>
              <select v-model="form.direction" class="input">
                <option value="entry">Entrada (vehículos entran)</option>
                <option value="exit">Salida (vehículos salen)</option>
              </select>
            </div>
            <div class="flex gap-2 pt-2">
              <button type="button" class="btn-secondary flex-1" @click="cancelDraft">Cancelar</button>
              <button
                type="button"
                class="btn-primary flex-1"
                :disabled="form.parking_space_id === null"
                @click="saveDraft"
              >Guardar geocerca</button>
            </div>
          </div>

          <div v-else-if="selectedId" class="space-y-3 text-sm">
            <template v-for="g in geofences" :key="g.id">
              <div v-if="g.id === selectedId">
                <div class="text-xs text-slate-500 mb-1">Plaza asignada</div>
                <div class="font-medium">{{ fenceLabel(g) }}</div>
                <div class="text-xs text-slate-500 mt-1">
                  (re-asignar requiere borrar y volver a crear — sin DELETE en MVP)
                </div>
                <div class="mt-3">
                  <label class="block text-slate-700 font-medium mb-1">Umbral de confianza</label>
                  <div class="flex items-center gap-3">
                    <input
                      type="range" min="0" max="1" step="0.01"
                      :value="g.confidence_threshold"
                      class="flex-1"
                      @change="updateConfidence(g, Number(($event.target as HTMLInputElement).value))"
                    />
                    <span class="text-sm font-mono w-12 text-right">{{ Math.round(g.confidence_threshold * 100) }} %</span>
                  </div>
                </div>
                <div class="mt-3">
                  <label class="block text-slate-700 font-medium mb-1">Dirección de la cámara</label>
                  <select
                    :value="g.direction"
                    class="input"
                    @change="updateDirection(g, ($event.target as HTMLSelectElement).value as Direction)"
                  >
                    <option value="entry">Entrada (vehículos entran)</option>
                    <option value="exit">Salida (vehículos salen)</option>
                  </select>
                </div>
              </div>
            </template>
          </div>

          <p v-else class="text-sm text-slate-500">
            {{ mode === 'create'
              ? 'Dibuja un rectángulo sobre la imagen para empezar.'
              : 'Haz click en una geocerca del frame para verla aquí.' }}
          </p>
        </div>

        <div class="bg-white rounded-xl shadow-card">
          <div class="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
            <h2 class="font-semibold text-sm">Geocercas ({{ geofences.length }})</h2>
          </div>
          <ul v-if="geofences.length" class="divide-y divide-slate-100 text-sm">
            <li
              v-for="g in geofences"
              :key="g.id"
              :class="['px-5 py-2 flex items-center justify-between cursor-pointer hover:bg-slate-50', selectedId === g.id && 'bg-amber-50']"
              @click="selectFence(g.id)"
            >
              <span class="flex items-center gap-2">
                <span class="font-medium">{{ fenceLabel(g) }}</span>
                <span
                  :class="['text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded',
                           g.direction === 'entry' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700']"
                >{{ g.direction === 'entry' ? 'Entrada' : 'Salida' }}</span>
              </span>
              <span class="text-slate-500 font-mono text-xs">
                {{ Math.round(g.x) }},{{ Math.round(g.y) }} · {{ Math.round(g.w) }}×{{ Math.round(g.h) }}
              </span>
            </li>
          </ul>
          <p v-else class="px-5 py-4 text-sm text-slate-500">
            Aún no hay geocercas para esta cámara.
          </p>
        </div>
      </aside>
    </div>
  </AppLayout>
</template>