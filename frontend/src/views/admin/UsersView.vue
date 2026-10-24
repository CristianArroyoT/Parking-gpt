<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http, type User } from '@/api/client'
import {
  ROLES_DE_SUCURSAL,
  assignUserToParking,
  listMemberships,
  listParkings,
  removeMembership,
  updateMembershipRole,
  type Membership,
  type MembershipRole,
  type Parking,
} from '@/api/gestorOps'
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

// ── Panel «Sucursales y roles» (T-179, ADR 0005) ────────────────────────
//
// El RBAC por sucursal (ADR 0005): el **rol global es el techo** y el rol
// de la sucursal es el poder real. Esta pantalla es la que permite
// gestionar ese rol: antes la columna `role_in_parking` se escribía al
// crear la membresía y no había ninguna pantalla para cambiarla.
const panelUser = ref<User | null>(null)
const parkings = ref<Parking[]>([])
const memberships = ref<Membership[]>([])
const membLoading = ref(false)
const membError = ref('')
const nuevaSucursal = ref('')
const nuevoRol = ref<MembershipRole>('gestor')

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

// ── Membresías (RBAC por sucursal) ──────────────────────────────────────

/**
 * El mensaje del backend, no uno genérico.
 *
 * OJO: el 422 de pydantic no llega como texto, sino como LISTA de errores
 * (`detail: [{loc, msg, ...}]`). Si solo se leyera `detail` como cadena,
 * el 422 del «admin» (que no es un rol por sucursal) se mostraría como un
 * error genérico y el admin no sabría por qué falló.
 */
function extraerError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string }
    const detail = anyErr.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => (typeof d === 'string' ? d : ((d as { msg?: string })?.msg ?? '')))
        .filter((m) => m !== '')
      if (msgs.length) return msgs.join(' · ')
    }
    if (anyErr.message) return anyErr.message
  }
  return fallback
}

function nombreSucursal(parkingId: number): string {
  const p = parkings.value.find((x) => x.id === parkingId)
  return p ? `${p.name} (${p.code})` : `Sucursal ${parkingId}`
}

function yaAsignada(parkingId: number): boolean {
  return memberships.value.some((m) => m.parking_id === parkingId)
}

async function abrirPanel(u: User): Promise<void> {
  panelUser.value = u
  membError.value = ''
  memberships.value = []
  nuevaSucursal.value = ''
  nuevoRol.value = 'gestor'
  try {
    // El admin ve todas las sucursales (`GET /parkings`).
    parkings.value = await listParkings()
  } catch (err) {
    parkings.value = []
    membError.value = extraerError(err, 'No se pudieron cargar las sucursales')
  }
  await cargarMembresias()
}

function cerrarPanel(): void {
  panelUser.value = null
  membError.value = ''
}

async function cargarMembresias(): Promise<void> {
  if (!panelUser.value) return
  membLoading.value = true
  try {
    memberships.value = await listMemberships(panelUser.value.id)
  } catch (err) {
    memberships.value = []
    membError.value = extraerError(err, 'No se pudieron cargar las membresías')
  } finally {
    membLoading.value = false
  }
}

async function anadirMembresia(): Promise<void> {
  if (!panelUser.value) return
  if (!nuevaSucursal.value) {
    membError.value = 'Elige una sucursal'
    return
  }
  try {
    await assignUserToParking(panelUser.value.id, Number(nuevaSucursal.value), nuevoRol.value)
    await cargarMembresias()
    nuevaSucursal.value = ''
    ui.pushToast('success', 'Membresía añadida')
  } catch (err) {
    membError.value = extraerError(err, 'No se pudo añadir la membresía')
    ui.pushToast('error', membError.value)
  }
}

async function cambiarRol(m: Membership, ev: Event): Promise<void> {
  if (!panelUser.value) return
  const valor = (ev.target as HTMLSelectElement).value
  if (!ROLES_DE_SUCURSAL.includes(valor as MembershipRole)) return
  const anterior = m.role_in_parking
  try {
    await updateMembershipRole(panelUser.value.id, m.id, valor as MembershipRole)
    m.role_in_parking = valor as MembershipRole
    ui.pushToast('success', `Rol en ${nombreSucursal(m.parking_id)}: ${valor}`)
  } catch (err) {
    // Se deja el selector como estaba: si no, la pantalla mentiría.
    m.role_in_parking = anterior
    membError.value = extraerError(err, 'No se pudo cambiar el rol')
    ui.pushToast('error', membError.value)
  }
}

async function quitarMembresia(m: Membership): Promise<void> {
  if (!panelUser.value) return
  try {
    await removeMembership(panelUser.value.id, m.id)
    await cargarMembresias()
    ui.pushToast('success', 'Membresía quitada')
  } catch (err) {
    membError.value = extraerError(err, 'No se pudo quitar la membresía')
    ui.pushToast('error', membError.value)
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
                <th class="px-5 py-3 font-medium">Sucursales y roles</th>
                <th class="px-5 py-3 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="loading"><td colspan="6" class="px-5 py-6 text-center text-slate-500">Cargando…</td></tr>
              <tr v-for="u in users" :key="u.id" v-else>
                <td class="px-5 py-3 font-mono text-xs">{{ u.email }}</td>
                <td class="px-5 py-3">{{ u.full_name }}</td>
                <td class="px-5 py-3"><span class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 text-xs">{{ u.role }}</span></td>
                <td class="px-5 py-3">
                  <span :class="u.is_active ? 'text-emerald-600' : 'text-slate-500'">
                    {{ u.is_active ? 'Activo' : 'Inactivo' }}
                  </span>
                </td>
                <td class="px-5 py-3">
                  <button
                    type="button"
                    class="btn-secondary"
                    :aria-label="`Sucursales y roles de ${u.email}`"
                    @click="abrirPanel(u)"
                  >
                    Sucursales y roles
                  </button>
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

    <!-- Panel de RBAC por sucursal. Teleport a body (como el modal de
         contraseña del layout) para no quedar detrás del sidebar. -->
    <Teleport to="body">
      <div
        v-if="panelUser"
        class="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="panel-membresias-titulo"
      >
        <div class="my-6 w-full max-w-2xl bg-white rounded-lg shadow-xl">
          <div class="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
            <div>
              <h2 id="panel-membresias-titulo" class="text-base font-semibold text-slate-900">
                Sucursales y roles
              </h2>
              <p class="text-xs text-slate-500">
                {{ panelUser.full_name }} · {{ panelUser.email }} · rol global: {{ panelUser.role }}
              </p>
            </div>
            <button type="button" class="btn-secondary" @click="cerrarPanel">Cerrar</button>
          </div>

          <div class="px-6 py-5 space-y-4">
            <!-- El techo (ADR 0005): el rol global manda. -->
            <p class="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <strong>El rol global es el techo.</strong>
              El rol de la sucursal nunca da más poder del que el usuario ya tiene: asignar
              «gestor» a un «operador» no lo convierte en gestor, y un «cliente» sigue siendo
              cliente. El «admin» no se asigna por sucursal: su poder es global.
            </p>

            <!-- T-169 (2026-10-24): el error se ANUNCIA (`role="alert"` = region
                 viva) y con el mensaje del backend, no uno genérico. -->
            <p
              v-if="membError"
              class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
              role="alert"
              aria-live="assertive"
            >
              {{ membError }}
            </p>

            <p v-if="membLoading" class="text-sm text-slate-500">Cargando membresías…</p>

            <ul v-if="!membLoading" class="divide-y divide-slate-100 rounded-md border border-slate-200">
              <li v-if="!memberships.length" class="px-3 py-3 text-sm text-slate-500">
                Este usuario no está en ninguna sucursal.
              </li>
              <li
                v-for="m in memberships"
                :key="m.id"
                class="flex flex-wrap items-end justify-between gap-3 px-3 py-3"
              >
                <div class="min-w-[12rem] flex-1">
                  <p class="text-sm font-medium text-slate-800">{{ nombreSucursal(m.parking_id) }}</p>
                  <label
                    class="block text-xs font-medium text-slate-700"
                    :for="`memb-rol-${m.id}`"
                  >
                    Rol en {{ nombreSucursal(m.parking_id) }}
                  </label>
                  <select
                    :id="`memb-rol-${m.id}`"
                    class="input"
                    :value="m.role_in_parking"
                    @change="cambiarRol(m, $event)"
                  >
                    <option v-for="r in ROLES_DE_SUCURSAL" :key="r" :value="r">{{ r }}</option>
                  </select>
                </div>
                <button
                  type="button"
                  class="btn-secondary text-rose-600 border-rose-300"
                  :aria-label="`Quitar la membresía de ${nombreSucursal(m.parking_id)}`"
                  @click="quitarMembresia(m)"
                >
                  Quitar
                </button>
              </li>
            </ul>

            <div class="rounded-md border border-slate-200 p-4">
              <h3 class="mb-3 text-sm font-semibold text-slate-800">Añadir una sucursal</h3>
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="block text-xs font-medium text-slate-700" for="memb-nueva-sucursal">
                    Sucursal
                  </label>
                  <select id="memb-nueva-sucursal" v-model="nuevaSucursal" class="input">
                    <option value="">Elige una sucursal</option>
                    <option
                      v-for="p in parkings"
                      :key="p.id"
                      :value="String(p.id)"
                      :disabled="yaAsignada(p.id)"
                    >
                      {{ p.name }} ({{ p.code }}){{ yaAsignada(p.id) ? ' — ya asignada' : '' }}
                    </option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-700" for="memb-nuevo-rol">
                    Rol en la sucursal
                  </label>
                  <select id="memb-nuevo-rol" v-model="nuevoRol" class="input">
                    <option v-for="r in ROLES_DE_SUCURSAL" :key="r" :value="r">{{ r }}</option>
                  </select>
                </div>
              </div>
              <button type="button" class="btn-primary mt-3" @click="anadirMembresia">
                Añadir
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>
