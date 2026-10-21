<script setup lang="ts">
/**
 * T-20 (2026-10-21): "Operadores" del gestor.
 *
 * Endpoints (``backend/app/api/v1/users.py``):
 *   - ``GET  /api/v1/users``                      → usuarios (**admin-only**).
 *   - ``POST /api/v1/users``                      → alta de operador (**admin-only**).
 *   - ``POST /api/v1/users/{id}/memberships``     → asignar a sucursal (**admin-only**).
 *
 * Limitación de RBAC del backend (importante, y por eso la UI lo dice):
 * las tres operaciones exigen rol ``admin``. Un gestor recibe 403, así que
 * la vista **no** falla en silencio: muestra un aviso explicando que el
 * alta y la asignación las tiene que hacer el administrador.
 *
 * Tampoco existe un endpoint de lectura de membresías (``GET
 * /users/{id}/memberships``), así que la vista no puede listar las
 * asignaciones ya hechas: se indica en pantalla y el backend responde 409
 * si la asignación ya existía.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { useUiStore } from '@/stores/ui'
import {
  assignUserToParking,
  createStaffUser,
  listParkings,
  listStaffUsers,
  type Parking,
  type StaffUser,
} from '@/api/gestorOps'

const ui = useUiStore()

const parkings = ref<Parking[]>([])
const parkingId = ref('')
const users = ref<StaffUser[]>([])

/** ``null`` = todavía no se ha comprobado; ``false`` = el gestor no puede. */
const canManage = ref<boolean | null>(null)
const forbidden = ref<string | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

const operators = ref<StaffUser[]>([])

// ── Alta de operador ────────────────────────────────────────────────────

const createForm = ref({ email: '', full_name: '', password: '', phone: '' })
const creating = ref(false)

async function onCreate(): Promise<void> {
  error.value = null
  if (!createForm.value.email.trim() || !createForm.value.full_name.trim()) {
    error.value = 'Indica correo y nombre.'
    return
  }
  if (createForm.value.password.length < 8) {
    error.value = 'La contraseña debe tener al menos 8 caracteres.'
    return
  }
  creating.value = true
  try {
    const nuevo = await createStaffUser({
      email: createForm.value.email.trim(),
      full_name: createForm.value.full_name.trim(),
      password: createForm.value.password,
      phone: createForm.value.phone.trim() === '' ? null : createForm.value.phone.trim(),
      role: 'operador',
    })
    operators.value = [...operators.value, nuevo]
    users.value = [...users.value, nuevo]
    createForm.value = { email: '', full_name: '', password: '', phone: '' }
    ui.pushToast('success', `Operador ${nuevo.full_name} creado`)
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo crear el operador')
  } finally {
    creating.value = false
  }
}

// ── Asignación a sucursal ───────────────────────────────────────────────

const assignUserId = ref('')
const assignRole = ref('operador')
const assigning = ref(false)

async function onAssign(): Promise<void> {
  error.value = null
  if (!assignUserId.value || !parkingId.value) {
    error.value = 'Selecciona operador y sucursal.'
    return
  }
  assigning.value = true
  try {
    await assignUserToParking(
      Number(assignUserId.value),
      Number(parkingId.value),
      assignRole.value,
    )
    ui.pushToast('success', 'Operador asignado a la sucursal')
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo asignar el operador')
  } finally {
    assigning.value = false
  }
}

// ── Carga ───────────────────────────────────────────────────────────────

async function load(): Promise<void> {
  loading.value = true
  try {
    parkings.value = await listParkings()
    if (parkings.value.length && parkingId.value === '') {
      parkingId.value = String(parkings.value[0].id)
    }
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudieron cargar las sucursales')
  }

  try {
    users.value = await listStaffUsers()
    canManage.value = true
  } catch (err: unknown) {
    if (statusOf(err) === 403) {
      canManage.value = false
      forbidden.value =
        'El listado y el alta de operadores son operaciones exclusivas del ' +
        'administrador (la API responde 403 al gestor). Pide al administrador ' +
        'que cree el operador y lo asigne a esta sucursal.'
    } else {
      error.value = extractError(err, 'No se pudieron cargar los operadores')
    }
  } finally {
    loading.value = false
  }
  operators.value = users.value.filter((u) => u.role === 'operador')
}

function statusOf(err: unknown): number | null {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { status?: number } }
    return anyErr.response?.status ?? null
  }
  return null
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Operadores</h1>
    <p class="text-sm text-slate-500 mb-6">
      Operadores de la sucursal: alta y asignación
    </p>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <!-- El gestor no tiene permisos: se explica, no se falla. -->
      <section
        v-if="canManage === false"
        class="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-6"
      >
        <h2 class="font-semibold text-amber-900 mb-2">Operadores: requiere permisos de administrador</h2>
        <p class="text-sm text-amber-900">{{ forbidden }}</p>
        <p class="text-xs text-amber-800 mt-2">
          Tu sucursal:
          <strong>{{ parkings.find((p) => String(p.id) === parkingId)?.name ?? '—' }}</strong>
        </p>
      </section>

      <template v-else>
        <p
          v-if="error"
          class="mb-4 text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
          role="alert"
        >
          {{ error }}
        </p>

        <!-- Listado -->
        <section class="bg-white rounded-xl shadow-card p-5 mb-6">
          <h2 class="font-semibold mb-3">Operadores dados de alta</h2>
          <div v-if="!operators.length" class="text-sm text-slate-500">
            Todavía no hay operadores registrados.
          </div>
          <table v-else class="w-full text-sm">
            <thead class="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th class="px-3 py-2 font-medium">Nombre</th>
                <th class="px-3 py-2 font-medium">Correo</th>
                <th class="px-3 py-2 font-medium">Teléfono</th>
                <th class="px-3 py-2 font-medium">Estado</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="o in operators" :key="o.id" class="hover:bg-slate-50">
                <td class="px-3 py-2 font-medium">{{ o.full_name }}</td>
                <td class="px-3 py-2">{{ o.email }}</td>
                <td class="px-3 py-2">{{ o.phone ?? '—' }}</td>
                <td class="px-3 py-2">
                  <span
                    :class="[
                      'text-xs font-semibold px-2 py-0.5 rounded',
                      o.is_active ? 'text-emerald-700 bg-emerald-100' : 'text-slate-700 bg-slate-100',
                    ]"
                  >
                    {{ o.is_active ? 'Activo' : 'Inactivo' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="mt-3 text-xs text-slate-500">
            La API no expone las asignaciones ya hechas (no existe
            ``GET /users/{id}/memberships``): para saber si un operador ya
            está en la sucursal hay que intentar la asignación, y el backend
            responde 409 si estaba duplicada.
          </p>
        </section>

        <div class="grid gap-6 lg:grid-cols-2">
          <!-- Alta -->
          <section class="bg-white rounded-xl shadow-card p-5">
            <h2 class="font-semibold mb-3">Nuevo operador</h2>
            <form class="space-y-3" @submit.prevent="onCreate">
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-nombre">
                  Nombre
                </label>
                <input
                  id="op-nombre"
                  v-model="createForm.full_name"
                  type="text"
                  required
                  :disabled="creating"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-correo">
                  Correo
                </label>
                <input
                  id="op-correo"
                  v-model="createForm.email"
                  type="email"
                  required
                  :disabled="creating"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-telefono">
                  Teléfono
                </label>
                <input
                  id="op-telefono"
                  v-model="createForm.phone"
                  type="tel"
                  maxlength="32"
                  :disabled="creating"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-password">
                  Contraseña
                </label>
                <input
                  id="op-password"
                  v-model="createForm.password"
                  type="password"
                  minlength="8"
                  required
                  :disabled="creating"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
                />
                <p class="mt-1 text-xs text-slate-500">Mínimo 8 caracteres.</p>
              </div>
              <div class="flex justify-end pt-1">
                <button
                  type="submit"
                  class="px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                  :disabled="creating"
                >
                  {{ creating ? 'Creando…' : 'Crear operador' }}
                </button>
              </div>
            </form>
          </section>

          <!-- Asignación -->
          <section class="bg-white rounded-xl shadow-card p-5">
            <h2 class="font-semibold mb-3">Asignar operador a la sucursal</h2>
            <form class="space-y-3" @submit.prevent="onAssign">
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-sucursal">
                  Sucursal
                </label>
                <select
                  id="op-sucursal"
                  v-model="parkingId"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
                >
                  <option v-for="p in parkings" :key="p.id" :value="String(p.id)">
                    {{ p.name }}
                  </option>
                </select>
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-operador">
                  Operador
                </label>
                <select
                  id="op-operador"
                  v-model="assignUserId"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
                >
                  <option value="">Selecciona…</option>
                  <option v-for="o in operators" :key="o.id" :value="String(o.id)">
                    {{ o.full_name }} ({{ o.email }})
                  </option>
                </select>
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1" for="op-rol-sucursal">
                  Rol en la sucursal
                </label>
                <select
                  id="op-rol-sucursal"
                  v-model="assignRole"
                  class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"
                >
                  <option value="operador">Operador</option>
                  <option value="gestor">Gestor</option>
                </select>
              </div>
              <div class="flex justify-end pt-1">
                <button
                  type="submit"
                  class="px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                  :disabled="assigning"
                >
                  {{ assigning ? 'Asignando…' : 'Asignar a la sucursal' }}
                </button>
              </div>
            </form>
          </section>
        </div>
      </template>
    </template>
  </AppLayout>
</template>
