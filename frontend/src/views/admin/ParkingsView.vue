<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { useUiStore } from '@/stores/ui'

interface Parking {
  id: number; code: string; name: string; address: string; city: string
  latitude: number | null; longitude: number | null; is_active: boolean
}

const ui = useUiStore()
const parkings = ref<Parking[]>([])
const loading = ref(true)
const editing = ref<Parking | null>(null)
const form = reactive({
  code: '', name: '', address: '', city: '',
  latitude: null as number | null, longitude: null as number | null, is_active: true,
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const { data } = await http.get<Parking[]>('/parkings')
    parkings.value = data
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las sucursales')
  } finally {
    loading.value = false
  }
}

function startCreate(): void {
  editing.value = null
  Object.assign(form, { code: '', name: '', address: '', city: '', latitude: null, longitude: null, is_active: true })
}

function startEdit(p: Parking): void {
  editing.value = p
  Object.assign(form, p)
}

async function submit(): Promise<void> {
  try {
    if (editing.value) {
      await http.patch(`/parkings/${editing.value.id}`, form)
      ui.pushToast('success', 'Sucursal actualizada')
    } else {
      await http.post('/parkings', form)
      ui.pushToast('success', 'Sucursal creada')
    }
    await load()
    startCreate()
  } catch {
    ui.pushToast('error', 'No se pudo guardar la sucursal')
  }
}

async function remove(p: Parking): Promise<void> {
  if (!confirm(`¿Eliminar la sucursal ${p.name}?`)) return
  try {
    await http.delete(`/parkings/${p.id}`)
    ui.pushToast('success', 'Sucursal eliminada')
    await load()
  } catch {
    ui.pushToast('error', 'No se pudo eliminar la sucursal')
  }
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Sucursales</h1>
        <p class="text-sm text-slate-500">CRUD de parkings del sistema</p>
      </div>
      <button type="button" class="btn-primary" @click="startCreate">+ Nueva sucursal</button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 bg-white rounded-xl shadow-card overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-5 py-3 font-medium">Nombre</th>
              <th class="px-5 py-3 font-medium">Código</th>
              <th class="px-5 py-3 font-medium">Ciudad</th>
              <th class="px-5 py-3 font-medium text-right">Acciones</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="loading"><td colspan="4" class="px-5 py-6 text-center text-slate-500">Cargando…</td></tr>
            <tr v-for="p in parkings" :key="p.id" v-else>
              <td class="px-5 py-3 font-medium">{{ p.name }}</td>
              <td class="px-5 py-3 font-mono text-xs">{{ p.code }}</td>
              <td class="px-5 py-3">{{ p.city }}</td>
              <td class="px-5 py-3 text-right space-x-2">
                <button class="btn-secondary" @click="startEdit(p)">Editar</button>
                <button class="btn-secondary text-rose-600 border-rose-300" @click="remove(p)">Eliminar</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-4">{{ editing ? 'Editar sucursal' : 'Nueva sucursal' }}</h2>
        <form class="space-y-3" @submit.prevent="submit">
          <div>
            <label class="block text-xs font-medium text-slate-700">Código</label>
            <input v-model="form.code" required minlength="2" maxlength="32" class="input" :disabled="!!editing" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Nombre</label>
            <input v-model="form.name" required minlength="2" class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Dirección</label>
            <input v-model="form.address" required class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700">Ciudad</label>
            <input v-model="form.city" required class="input" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-medium text-slate-700">Latitud</label>
              <input v-model.number="form.latitude" type="number" step="0.000001" class="input" />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700">Longitud</label>
              <input v-model.number="form.longitude" type="number" step="0.000001" class="input" />
            </div>
          </div>
          <label class="inline-flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" v-model="form.is_active" class="rounded border-slate-300" /> Activa
          </label>
          <div class="flex gap-2 pt-2">
            <button type="submit" class="btn-primary">{{ editing ? 'Guardar cambios' : 'Crear sucursal' }}</button>
            <button v-if="editing" type="button" class="btn-secondary" @click="startCreate">Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  </AppLayout>
</template>