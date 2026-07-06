<script setup lang="ts">
/**
 * Listado de cámaras del parking seleccionado. Desde cada fila se
 * enlaza con la vista de calibración de geocercas sobre el frame.
 *
 * Sprint Fase 4 (2026-07-01):
 *   - Campo ``kind`` ('surveillance' | 'gate') en la respuesta del
 *     backend → chip visual + filtro.
 *   - Form modal "Añadir cámara" (POST /parkings/{id}/cameras).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string; code: string }
type CameraKind = 'surveillance' | 'gate'
interface Camera {
  id: number; parking_id: number; code: string; name: string;
  rtsp_url: string; lane_hint: string | null; fps: number; is_active: boolean
  kind: CameraKind
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const selectedId = ref<number | null>(null)
const cameras = ref<Camera[]>([])
const loading = ref(true)

// ── Filtro por kind ──────────────────────────────────────────────
const kindFilter = ref<'all' | CameraKind>('all')
const filteredCameras = computed(() => {
  if (kindFilter.value === 'all') return cameras.value
  return cameras.value.filter((c) => c.kind === kindFilter.value)
})

async function loadCameras(): Promise<void> {
  if (!selectedId.value) return
  try {
    const { data } = await http.get<Camera[]>(`/parkings/${selectedId.value}/cameras`)
    cameras.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las cámaras')
  } finally {
    loading.value = false
  }
}

async function load(): Promise<void> {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
    if (data.length) selectedId.value = data[0].id
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las cámaras')
  } finally {
    loading.value = false
  }
  await loadCameras()
}

watch(selectedId, () => { void loadCameras() })
onMounted(load)

// ── Modal "Añadir cámara" ────────────────────────────────────────
const showCreate = ref(false)
const createForm = ref({
  code: '',
  name: '',
  rtsp_url: '',
  lane_hint: '' as '' | 'entry' | 'exit',
  fps: 10,
  kind: 'surveillance' as CameraKind,
})
const saving = ref(false)

function openCreate(): void {
  createForm.value = {
    code: '',
    name: '',
    rtsp_url: '',
    lane_hint: '',
    fps: 10,
    kind: 'surveillance',
  }
  showCreate.value = true
}
function closeCreate(): void {
  showCreate.value = false
}
async function submitCreate(): Promise<void> {
  if (!selectedId.value) return
  saving.value = true
  try {
    await http.post(
      `/parkings/${selectedId.value}/cameras`,
      {
        code: createForm.value.code.trim(),
        name: createForm.value.name.trim(),
        rtsp_url: createForm.value.rtsp_url.trim(),
        lane_hint: createForm.value.lane_hint || null,
        fps: Number(createForm.value.fps) || 10,
        kind: createForm.value.kind,
      },
    )
    ui.pushToast('success', 'Cámara creada')
    showCreate.value = false
    await loadCameras()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo crear la cámara'))
  } finally {
    saving.value = false
  }
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

function kindLabel(k: CameraKind): string {
  return k === 'gate' ? 'Portería' : 'Fiscalización'
}
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Cámaras</h1>
        <p class="text-sm text-slate-500">Inventario y calibración de geocercas</p>
      </div>
      <div class="flex items-center gap-2">
        <select v-model.number="selectedId" class="input w-auto" @change="load">
          <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button type="button" class="btn-primary" @click="openCreate">
          Añadir cámara
        </button>
      </div>
    </div>

    <!-- Filtro por tipo (Sprint Fase 4) -->
    <div class="flex items-center gap-2 mb-3 text-xs">
      <span class="text-slate-500">Filtrar:</span>
      <button
        type="button"
        :class="['px-2 py-1 rounded border', kindFilter === 'all' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white']"
        @click="kindFilter = 'all'"
      >Todas ({{ cameras.length }})</button>
      <button
        type="button"
        :class="['px-2 py-1 rounded border', kindFilter === 'surveillance' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white']"
        @click="kindFilter = 'surveillance'"
      >Fiscalización ({{ cameras.filter(c => c.kind === 'surveillance').length }})</button>
      <button
        type="button"
        :class="['px-2 py-1 rounded border', kindFilter === 'gate' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-300 bg-white']"
        @click="kindFilter = 'gate'"
      >Portería ({{ cameras.filter(c => c.kind === 'gate').length }})</button>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando cámaras…</div>

    <div v-else class="bg-white rounded-xl shadow-card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 text-slate-500 text-left">
          <tr>
            <th class="px-5 py-3 font-medium">Código</th>
            <th class="px-5 py-3 font-medium">Nombre</th>
            <th class="px-5 py-3 font-medium">Tipo</th>
            <th class="px-5 py-3 font-medium">Calle</th>
            <th class="px-5 py-3 font-medium">FPS</th>
            <th class="px-5 py-3 font-medium">URL RTSP</th>
            <th class="px-5 py-3 font-medium">Estado</th>
            <th class="px-5 py-3 font-medium text-right">Acciones</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="cam in filteredCameras" :key="cam.id">
            <td class="px-5 py-3 font-mono text-xs">{{ cam.code }}</td>
            <td class="px-5 py-3">{{ cam.name }}</td>
            <td class="px-5 py-3">
              <span
                :class="['inline-block text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded',
                         cam.kind === 'gate' ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-700']"
              >{{ kindLabel(cam.kind) }}</span>
            </td>
            <td class="px-5 py-3">{{ cam.lane_hint ?? '—' }}</td>
            <td class="px-5 py-3">{{ cam.fps }}</td>
            <td class="px-5 py-3 font-mono text-xs truncate max-w-xs">{{ cam.rtsp_url }}</td>
            <td class="px-5 py-3">
              <span :class="cam.is_active ? 'text-emerald-600' : 'text-slate-500'">
                {{ cam.is_active ? 'Activa' : 'Inactiva' }}
              </span>
            </td>
            <td class="px-5 py-3 text-right">
              <RouterLink
                :to="{ name: 'gestor-calibrate', params: { parkingId: selectedId, cameraId: cam.id } }"
                class="btn-secondary"
              >Calibrar</RouterLink>
            </td>
          </tr>
          <tr v-if="!filteredCameras.length">
            <td colspan="8" class="px-5 py-6 text-center text-slate-500">
              <template v-if="!cameras.length">
                Esta sucursal no tiene cámaras dadas de alta.
                <button type="button" class="text-blue-600 hover:underline ml-2" @click="openCreate">
                  Añadir la primera
                </button>
              </template>
              <template v-else>
                Ninguna cámara coincide con el filtro seleccionado.
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Modal Añadir cámara (Sprint Fase 4) -->
    <Teleport to="body">
      <div
        v-if="showCreate"
        class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-camera-title"
        @keydown.esc="closeCreate"
        @click.self="closeCreate"
      >
        <div class="bg-white rounded-xl shadow-card w-full max-w-lg p-6">
          <h2 id="create-camera-title" class="text-lg font-semibold mb-4">
            Añadir cámara
          </h2>
          <form class="space-y-3 text-sm" @submit.prevent="submitCreate">
            <div>
              <label class="block text-slate-700 font-medium mb-1">Código</label>
              <input
                v-model="createForm.code"
                class="input"
                required
                minlength="2"
                maxlength="32"
                placeholder="Ej: CAM-A1"
              >
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Nombre</label>
              <input
                v-model="createForm.name"
                class="input"
                required
                minlength="2"
                maxlength="128"
                placeholder="Ej: Entrada principal A"
              >
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">URL RTSP</label>
              <input
                v-model="createForm.rtsp_url"
                class="input font-mono"
                required
                minlength="8"
                maxlength="1024"
                placeholder="rtsp://usuario:pass@host:puerto/stream"
              >
              <p class="text-xs text-slate-500 mt-1">
                Cadena completa con credenciales. Si quieres probar, usa una URL pública
                como <code class="bg-slate-100 px-1 rounded">rtsp://demo.invalid/test</code>.
              </p>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-slate-700 font-medium mb-1">Calle (lane)</label>
                <select v-model="createForm.lane_hint" class="input">
                  <option value="">Sin asignar</option>
                  <option value="entry">Entrada</option>
                  <option value="exit">Salida</option>
                </select>
              </div>
              <div>
                <label class="block text-slate-700 font-medium mb-1">FPS</label>
                <input
                  v-model.number="createForm.fps"
                  class="input"
                  type="number"
                  min="1"
                  max="60"
                  required
                >
              </div>
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Tipo</label>
              <select v-model="createForm.kind" class="input">
                <option value="surveillance">Fiscalización (observa el parking)</option>
                <option value="gate">Portería (entrada/salida manual)</option>
              </select>
              <p class="text-xs text-slate-500 mt-1">
                Sprint Fase 4: distingue cámaras que vigilan plazas (fiscalización) de
                las que están dedicadas a una barrera (portería).
              </p>
            </div>
            <div class="flex gap-2 pt-3">
              <button
                type="button"
                class="btn-secondary flex-1"
                :disabled="saving"
                @click="closeCreate"
              >Cancelar</button>
              <button
                type="submit"
                class="btn-primary flex-1"
                :disabled="saving"
              >{{ saving ? 'Guardando…' : 'Crear cámara' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>