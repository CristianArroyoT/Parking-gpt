<script setup lang="ts">
/**
 * T-20 (2026-10-21): "Alertas activas" del gestor.
 *
 * Endpoints (``backend/app/api/v1/alerts.py``):
 *   - ``GET  /api/v1/parkings/{id}/alerts`` → listado filtrable por tipo,
 *     severidad y estado de reconocimiento.
 *   - ``POST /api/v1/parkings/{id}/alerts/{alert_id}/acknowledge`` → marca la
 *     alerta como revisada por el usuario actual (idempotente).
 *
 * Sobre "resolver/ignorar": el backend **no** tiene cierre ni "ignore" de
 * alertas; la única acción es el *acknowledge*, que fija ``acknowledged_at``
 * y ``acknowledged_by`` y saca la alerta de la lista de activas. La UI lo
 * llama "marcar como revisada" en vez de inventar un endpoint que no
 * existe.
 *
 * El scope por sucursal lo aplica el backend: ``parking_context`` rechaza
 * (403) a quien no tenga membresía en la sucursal de la alerta.
 */
import { computed, onMounted, ref, watch } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { useUiStore } from '@/stores/ui'
import {
  acknowledgeAlert,
  listAlerts,
  listParkings,
  type Alert,
  type Parking,
} from '@/api/gestorOps'

const ui = useUiStore()

const parkings = ref<Parking[]>([])
const parkingId = ref('')
const alerts = ref<Alert[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const busyId = ref<number | null>(null)

/** ``activas`` = sin reconocer; ``revisadas`` = ya reconocidas. */
const estado = ref<'activas' | 'revisadas' | 'todas'>('activas')
const severidad = ref('')
const tipo = ref('')

const TIPOS: Record<string, string> = {
  ocr_failed: 'Fallo de OCR',
  camera_offline: 'Cámara caída',
  // T-164 (2026-10-24): la camara dejo de enviar lecturas (no es que el
  // RTSP no responda).
  camera_push_silent: 'Cámara sin lecturas',
  space_empty_too_long: 'Plaza vacía mucho tiempo',
  robbery_reported: 'Robo reportado',
  space_broken: 'Plaza averiada',
  other: 'Otra',
}

const filtered = computed(() =>
  alerts.value.filter((a) => {
    if (estado.value === 'activas' && a.acknowledged_at) return false
    if (estado.value === 'revisadas' && !a.acknowledged_at) return false
    if (severidad.value && a.severity !== severidad.value) return false
    if (tipo.value && a.type !== tipo.value) return false
    return true
  }),
)

const activasCount = computed(() => alerts.value.filter((a) => !a.acknowledged_at).length)

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

async function loadAlerts(): Promise<void> {
  if (parkingId.value === '') {
    alerts.value = []
    // T-138 (2026-10-24): el `return` temprano no bajaba el flag
    // `loading` -> «Cargando…» para siempre.
    loading.value = false
    error.value = 'No tienes ninguna sucursal asignada'
    return
  }
  loading.value = true
  error.value = null
  try {
    alerts.value = await listAlerts(Number(parkingId.value))
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudieron cargar las alertas')
    alerts.value = []
  } finally {
    loading.value = false
  }
}

watch(parkingId, () => {
  void loadAlerts()
})

async function onAcknowledge(a: Alert): Promise<void> {
  error.value = null
  busyId.value = a.id
  try {
    const actualizada = await acknowledgeAlert(Number(parkingId.value), a.id)
    alerts.value = alerts.value.map((x) => (x.id === a.id ? actualizada : x))
    ui.pushToast('success', 'Alerta marcada como revisada')
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo marcar la alerta como revisada')
  } finally {
    busyId.value = null
  }
}

function fmt(d: string | null): string {
  return d ? new Date(d).toLocaleString('es-ES') : '—'
}

function severityBadge(sev: string): { label: string; cls: string } {
  if (sev === 'critical') return { label: 'Crítica', cls: 'text-rose-700 bg-rose-100' }
  if (sev === 'warn') return { label: 'Aviso', cls: 'text-amber-700 bg-amber-100' }
  return { label: 'Info', cls: 'text-slate-700 bg-slate-100' }
}

function typeLabel(t: string): string {
  return TIPOS[t] ?? t
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
  await loadAlerts()
})
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Alertas</h1>
    <p class="text-sm text-slate-500 mb-6">
      Alertas operativas de tu sucursal ({{ activasCount }} sin revisar)
    </p>

    <section class="bg-white rounded-xl shadow-card p-5 mb-6">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="alt-sucursal">
            Sucursal
          </label>
          <select
            id="alt-sucursal"
            v-model="parkingId"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option v-for="p in parkings" :key="p.id" :value="String(p.id)">
              {{ p.name }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="alt-estado">Estado</label>
          <select
            id="alt-estado"
            v-model="estado"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="activas">Sin revisar</option>
            <option value="revisadas">Revisadas</option>
            <option value="todas">Todas</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="alt-severidad">
            Severidad
          </label>
          <select
            id="alt-severidad"
            v-model="severidad"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">Todas</option>
            <option value="critical">Crítica</option>
            <option value="warn">Aviso</option>
            <option value="info">Info</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="alt-tipo">Tipo</label>
          <select
            id="alt-tipo"
            v-model="tipo"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">Todos</option>
            <option v-for="(label, key) in TIPOS" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
      </div>

      <p class="mt-3 text-xs text-slate-500">
        La API no tiene "resolver" ni "ignorar": la única acción disponible
        es marcar la alerta como revisada, que es lo que la saca de la lista
        de sin revisar.
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
      <div v-else-if="!error && !filtered.length" class="text-sm text-slate-500">
        No hay alertas con estos filtros.
      </div>

      <ul v-else class="divide-y divide-slate-100">
        <li v-for="a in filtered" :key="a.id" class="py-3 flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span :class="['text-xs font-semibold px-2 py-0.5 rounded', severityBadge(a.severity).cls]">
                {{ severityBadge(a.severity).label }}
              </span>
              <span class="text-sm font-medium">{{ typeLabel(a.type) }}</span>
              <span
                v-if="a.acknowledged_at"
                class="text-xs font-semibold px-2 py-0.5 rounded text-slate-700 bg-slate-100"
              >
                Revisada
              </span>
            </div>
            <p class="text-sm text-slate-700 mt-1">{{ a.message }}</p>
            <p class="text-xs text-slate-500 mt-1">
              {{ fmt(a.created_at) }}
              <span v-if="a.acknowledged_at"> · revisada el {{ fmt(a.acknowledged_at) }}</span>
            </p>
          </div>
          <button
            v-if="!a.acknowledged_at"
            type="button"
            class="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            :disabled="busyId === a.id"
            @click="onAcknowledge(a)"
          >
            {{ busyId === a.id ? 'Guardando…' : 'Marcar como revisada' }}
          </button>
        </li>
      </ul>
    </section>
  </AppLayout>
</template>
