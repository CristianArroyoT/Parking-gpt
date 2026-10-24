<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http, type User } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const users = ref<User[]>([])
const loading = ref(true)
const editing = ref<User | null>(null)
const form = reactive({
  email: '', full_name: '', phone: '' as string | null,
  role: 'cliente' as User['role'], is_active: true, password: '',
})

const ROLES: User['role'][] = ['admin', 'gestor', 'operador', 'cliente']

async function load(): Promise<void> {
  loading.value = true
  try {
    const { data } = await http.get<User[]>('/users')
    users.value = data
  } catch {
    ui.pushToast('error', 'No se pudo cargar la lista de usuarios')
  } finally {
    loading.value = false
  }
}

function startCreate(): void {
  editing.value = null
  Object.assign(form, { email: '', full_name: '', phone: '', role: 'cliente', is_active: true, password: '' })
}

function startEdit(u: User): void {
  editing.value = u
  Object.assign(form, { ...u, password: '' })
}

async function submit(): Promise<void> {
  try {
    if (editing.value) {
      const payload: Record<string, unknown> = { ...form }
      if (!payload.password) delete payload.password
      await http.patch(`/users/${editing.value.id}`, payload)
      ui.pushToast('success', 'Usuario actualizado')
    } else {
      await http.post('/users', form)
      ui.pushToast('success', 'Usuario creado')
    }
    await load()
    startCreate()
  } catch {
    ui.pushToast('error', 'No se pudo guardar el usuario')
  }
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Usuarios</h1>
        <p class="text-sm text-slate-500">Cuentas con acceso a solidAPP y sus roles</p>
      </div>
      <button type="button" class="btn-primary" @click="startCreate">+ Nuevo usuario</button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 bg-white rounded-xl shadow-card overflow-hidden">
        <div class="overflow-x-auto min-w-0">
          <table class="w-full min-w-max text-sm">
            <thead class="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th class="px-5 py-3 font-medium">Email</th>
                <th class="px-5 py-3 font-medium">Nombre</th>
                <th class="px-5 py-3 font-medium">Rol</th>
                <th class="px-5 py-3 font-medium">Estado</th>
                <th class="px-5 py-3 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="loading"><td colspan="5" class="px-5 py-6 text-center text-slate-500">Cargando…</td></tr>
              <tr v-for="u in users" :key="u.id" v-else>
                <td class="px-5 py-3 font-mono text-xs">{{ u.email }}</td>
                <td class="px-5 py-3">{{ u.full_name }}</td>
                <td class="px-5 py-3"><span class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 text-xs">{{ u.role }}</span></td>
                <td class="px-5 py-3">
                  <span :class="u.is_active ? 'text-emerald-600' : 'text-slate-500'">
                    {{ u.is_active ? 'Activo' : 'Inactivo' }}
                  </span>
                </td>
                <td class="px-5 py-3 text-right">
                  <button class="btn-secondary" @click="startEdit(u)">Editar</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-4">{{ editing ? 'Editar usuario' : 'Nuevo usuario' }}</h2>
        <form class="space-y-3" @submit.prevent="submit">
          <div>
            <label class="block text-xs font-medium text-slate-700" for="usuario-email">Email</label>
            <input id="usuario-email" v-model="form.email" type="email" required class="input" :disabled="!!editing" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700" for="usuario-nombre">Nombre completo</label>
            <input id="usuario-nombre" v-model="form.full_name" required minlength="2" class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700" for="usuario-telefono">Teléfono</label>
            <input id="usuario-telefono" v-model="form.phone" class="input" />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700" for="usuario-rol">Rol</label>
            <select id="usuario-rol" v-model="form.role" class="input">
              <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-700" for="usuario-password">
              {{ editing ? 'Nueva contraseña (dejar vacío para no cambiar)' : 'Contraseña' }}
            </label>
            <input id="usuario-password" v-model="form.password" type="password" minlength="8" class="input" :required="!editing" />
          </div>
          <label class="inline-flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" v-model="form.is_active" class="rounded border-slate-300" /> Activo
          </label>
          <div class="flex gap-2 pt-2">
            <button type="submit" class="btn-primary">{{ editing ? 'Guardar' : 'Crear' }}</button>
            <button v-if="editing" type="button" class="btn-secondary" @click="startCreate">Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  </AppLayout>
</template>