<script setup lang="ts">
/**
 * Listado de cámaras del parking seleccionado. La calibración de geocercas
 * (rectángulos sobre frame RTSP) entra en Fase 2.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking { id: number; name: string; code: string }
interface Camera {
  id: number; parking_id: number; code: string; name: string;
  rtsp_url: string; lane_hint: string | null; fps: number; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const selectedId = ref<number | null>(null)
const cameras = ref<Camera[]>([])
const loading = ref(true)

async function load(): Promise<void> {
  try {
    const [p, c] = await Promise.all([
      http.get<Parking[]>('/parkings'),
      selectedId.value
        ? http.get<Camera[]>(`/parkings/${selectedId.value}/cameras`)
        : Promise.resolve({ data: [] as Camera[] }),
    ])
    parkings.value = p.data
    cameras.value = c.data
    if (!selectedId.value && p.data.length) selectedId.value = p.data[0].id
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las cámaras')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Cámaras</h1>
        <p class="text-sm text-slate-500">Inventario y geocercas (calibración en Fase 2)</p>
      </div>
      <select v-model.number="selectedId" class="input w-auto" @change="load">
        <option v-for="p in parkings" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando cámaras…</div>

    <div v-else class="bg-white rounded-xl shadow-card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-slate-50 text-slate-500 text-left">
          <tr>
            <th class="px-5 py-3 font-medium">Código</th>
            <th class="px-5 py-3 font-medium">Nombre</th>
            <th class="px-5 py-3 font-medium">Calle</th>
            <th class="px-5 py-3 font-medium">FPS</th>
            <th class="px-5 py-3 font-medium">URL RTSP</th>
            <th class="px-5 py-3 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="cam in cameras" :key="cam.id">
            <td class="px-5 py-3 font-mono text-xs">{{ cam.code }}</td>
            <td class="px-5 py-3">{{ cam.name }}</td>
            <td class="px-5 py-3">{{ cam.lane_hint ?? '—' }}</td>
            <td class="px-5 py-3">{{ cam.fps }}</td>
            <td class="px-5 py-3 font-mono text-xs truncate max-w-xs">{{ cam.rtsp_url }}</td>
            <td class="px-5 py-3">
              <span :class="cam.is_active ? 'text-emerald-600' : 'text-slate-500'">
                {{ cam.is_active ? 'Activa' : 'Inactiva' }}
              </span>
            </td>
          </tr>
          <tr v-if="!cameras.length">
            <td colspan="6" class="px-5 py-6 text-center text-slate-500">
              Esta sucursal no tiene cámaras dadas de alta.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppLayout>
</template>