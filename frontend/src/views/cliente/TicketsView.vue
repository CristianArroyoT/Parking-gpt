<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Ticket {
  id: number; parking_id: number; vehicle_id: number; status: string
  entry_at: string; exit_at: string | null
  amount: number | null; discount: number | null; total: number | null
}

const ui = useUiStore()
const tickets = ref<Ticket[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const { data } = await http.get<Ticket[]>('/tickets')
    tickets.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar tus tickets')
  } finally {
    loading.value = false
  }
})

function fmt(d: string | null): string {
  return d ? new Date(d).toLocaleString('es-ES') : '—'
}

function eur(n: number | null): string {
  if (n === null || n === undefined) return '—'
  return n.toFixed(2).replace('.', ',') + ' €'
}

const activos = (): Ticket[] => tickets.value.filter((t) => t.status === 'activo')
const cerrados = (): Ticket[] => tickets.value.filter((t) => t.status === 'cerrado')
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Mis tickets</h1>
    <p class="text-sm text-slate-500 mb-6">Historial de entradas y salidas</p>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <section class="bg-white rounded-xl shadow-card p-5 mb-6">
        <h2 class="font-semibold mb-3">Tickets activos</h2>
        <div v-if="!activos().length" class="text-sm text-slate-500">No tienes tickets activos.</div>
        <ul v-else class="divide-y divide-slate-100 text-sm">
          <li v-for="t in activos()" :key="t.id" class="py-3 flex justify-between">
            <div>
              <div class="font-medium">Ticket #{{ t.id }} · Sucursal {{ t.parking_id }}</div>
              <div class="text-xs text-slate-500">Entrada: {{ fmt(t.entry_at) }}</div>
            </div>
            <span class="text-emerald-600 text-xs">Activo</span>
          </li>
        </ul>
      </section>

      <section class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Histórico</h2>
        <div v-if="!cerrados().length" class="text-sm text-slate-500">Sin tickets cerrados todavía.</div>
        <table v-else class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-3 py-2 font-medium">#</th>
              <th class="px-3 py-2 font-medium">Entrada</th>
              <th class="px-3 py-2 font-medium">Salida</th>
              <th class="px-3 py-2 font-medium text-right">Importe</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="t in cerrados()" :key="t.id">
              <td class="px-3 py-2 font-mono text-xs">#{{ t.id }}</td>
              <td class="px-3 py-2">{{ fmt(t.entry_at) }}</td>
              <td class="px-3 py-2">{{ fmt(t.exit_at) }}</td>
              <td class="px-3 py-2 text-right font-medium">{{ eur(t.total) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </AppLayout>
</template>