<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
})

const KPIS = [
  { label: 'Ingresos (24h)', value: '1.247,40 €', delta: '+8,4 % vs ayer', color: 'text-emerald-600' },
  { label: 'Tickets cerrados', value: '348', delta: '29 en curso ahora', color: 'text-slate-500' },
  { label: 'Ocupación media', value: '76 %', delta: 'Plazas: 260 / 342', color: 'text-slate-500' },
  { label: 'Alertas activas', value: '12', delta: '3 de severidad alta', color: 'text-amber-500' },
]
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Dashboard global</h1>
        <p class="text-sm text-slate-500">Resumen de las últimas 24 horas · {{ parkings.length }} sucursales activas</p>
      </div>
    </div>

    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div v-for="k in KPIS" :key="k.label" class="bg-white rounded-xl p-5 shadow-card">
        <div class="text-xs uppercase tracking-wide text-slate-500">{{ k.label }}</div>
        <div class="mt-2 text-3xl font-semibold text-slate-900">{{ k.value }}</div>
        <div class="text-xs mt-1" :class="k.color">{{ k.delta }}</div>
      </div>
    </div>

    <div class="mt-8 bg-white rounded-xl shadow-card overflow-hidden">
      <div class="px-5 py-4 border-b border-slate-200">
        <h2 class="font-semibold">Estado de las sucursales</h2>
      </div>
      <div v-if="loading" class="p-6 text-sm text-slate-500">Cargando…</div>
      <table v-else class="w-full text-sm">
        <thead class="bg-slate-50 text-slate-500 text-left">
          <tr>
            <th class="px-5 py-3 font-medium">Sucursal</th>
            <th class="px-5 py-3 font-medium">Código</th>
            <th class="px-5 py-3 font-medium">Ciudad</th>
            <th class="px-5 py-3 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="p in parkings" :key="p.id">
            <td class="px-5 py-3 font-medium">{{ p.name }}</td>
            <td class="px-5 py-3 font-mono text-xs">{{ p.code }}</td>
            <td class="px-5 py-3">{{ p.city }}</td>
            <td class="px-5 py-3">
              <span :class="p.is_active ? 'text-emerald-600' : 'text-slate-500'">
                {{ p.is_active ? 'Activa' : 'Inactiva' }}
              </span>
            </td>
          </tr>
          <tr v-if="!parkings.length">
            <td colspan="4" class="px-5 py-6 text-center text-slate-500">
              No hay sucursales. Ejecuta el seed en el backend.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-8 bg-white rounded-xl shadow-card">
      <div class="px-5 py-4 border-b border-slate-200">
        <h2 class="font-semibold">Eventos recientes</h2>
      </div>
      <p class="px-5 py-6 text-sm text-slate-500">
        Los eventos en vivo llegan en la Fase 2 (worker OCR + Celery).
      </p>
    </div>
  </AppLayout>
</template>