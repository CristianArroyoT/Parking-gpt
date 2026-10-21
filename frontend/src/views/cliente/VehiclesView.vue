<script setup lang="ts">
/**
 * T-19 (2026-10-21): vista "Mis vehículos" del cliente.
 *
 * Alta, edición y vínculo de roles (propietario / conductor) sobre los
 * vehículos del usuario. Los endpoints son *user-scoped*
 * (`/users/me/vehicles...`): el cliente nunca ve ni toca vehículos de
 * otros usuarios, cosa que con `/vehicles` (staff-only) no se podría
 * garantizar.
 *
 * Reglas de permisos que aplica el backend:
 *   - Alta: el usuario queda como `propietario`.
 *   - Edición: sólo el `propietario` puede editar los datos del vehículo.
 *   - Vínculo/desvínculo de personas: sólo el `propietario`.
 *   - No se puede quitar el último propietario del vehículo.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import {
  createMyVehicle,
  linkVehicleUser,
  listMyVehicles,
  unlinkVehicleUser,
  updateMyVehicle,
  type MyVehicle,
  type VehicleRole,
} from '@/api/userScope'

const auth = useAuthStore()
const ui = useUiStore()

const vehicles = ref<MyVehicle[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// ── Alta ────────────────────────────────────────────────────────────────

const createForm = ref({ plate: '', brand: '', model: '', color: '', vehicle_type: '' })
const creating = ref(false)

async function reload(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    vehicles.value = await listMyVehicles()
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudieron cargar tus vehículos')
  } finally {
    loading.value = false
  }
}

async function onCreate(): Promise<void> {
  error.value = null
  const plate = createForm.value.plate.trim().toUpperCase()
  if (plate.length < 4) {
    error.value = 'La matrícula debe tener al menos 4 caracteres.'
    return
  }
  creating.value = true
  try {
    const nuevo = await createMyVehicle({
      plate,
      brand: nullIfEmpty(createForm.value.brand),
      model: nullIfEmpty(createForm.value.model),
      color: nullIfEmpty(createForm.value.color),
      vehicle_type: nullIfEmpty(createForm.value.vehicle_type),
    })
    vehicles.value = [...vehicles.value, nuevo].sort((a, b) =>
      a.plate.localeCompare(b.plate),
    )
    createForm.value = { plate: '', brand: '', model: '', color: '', vehicle_type: '' }
    ui.pushToast('success', `Vehículo ${nuevo.plate} añadido`)
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo añadir el vehículo')
  } finally {
    creating.value = false
  }
}

// ── Edición ─────────────────────────────────────────────────────────────

const editingId = ref<number | null>(null)
const editForm = ref({ brand: '', model: '', color: '', vehicle_type: '' })
const saving = ref(false)

function startEdit(v: MyVehicle): void {
  editingId.value = v.id
  editForm.value = {
    brand: v.brand ?? '',
    model: v.model ?? '',
    color: v.color ?? '',
    vehicle_type: v.vehicle_type ?? '',
  }
}

function cancelEdit(): void {
  editingId.value = null
}

async function onSaveEdit(v: MyVehicle): Promise<void> {
  error.value = null
  saving.value = true
  try {
    const actualizado = await updateMyVehicle(v.id, {
      brand: nullIfEmpty(editForm.value.brand),
      model: nullIfEmpty(editForm.value.model),
      color: nullIfEmpty(editForm.value.color),
      vehicle_type: nullIfEmpty(editForm.value.vehicle_type),
    })
    vehicles.value = vehicles.value.map((x) => (x.id === v.id ? actualizado : x))
    editingId.value = null
    ui.pushToast('success', `Vehículo ${actualizado.plate} actualizado`)
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo actualizar el vehículo')
  } finally {
    saving.value = false
  }
}

// ── Vínculos de personas ────────────────────────────────────────────────

const linkForm = ref<{ vehicleId: number; email: string; role: VehicleRole } | null>(null)
const linking = ref(false)

function startLink(v: MyVehicle): void {
  linkForm.value = { vehicleId: v.id, email: '', role: 'conductor' }
}

async function onLink(): Promise<void> {
  if (!linkForm.value) return
  error.value = null
  const email = linkForm.value.email.trim()
  if (!email) {
    error.value = 'Indica el correo de la persona a vincular.'
    return
  }
  linking.value = true
  try {
    await linkVehicleUser(linkForm.value.vehicleId, {
      email,
      role: linkForm.value.role,
    })
    linkForm.value = null
    await reload()
    ui.pushToast('success', 'Persona vinculada')
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo vincular la persona')
  } finally {
    linking.value = false
  }
}

async function onUnlink(v: MyVehicle, userId: number): Promise<void> {
  error.value = null
  try {
    await unlinkVehicleUser(v.id, userId)
    await reload()
    ui.pushToast('success', 'Vínculo eliminado')
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo eliminar el vínculo')
  }
}

// ── Utilidades ──────────────────────────────────────────────────────────

function nullIfEmpty(value: string): string | null {
  const v = value.trim()
  return v === '' ? null : v
}

function roleLabel(role: string): string {
  return role === 'conductor' ? 'Conductor' : 'Propietario'
}

function roleBadge(role: string): string {
  return role === 'conductor'
    ? 'text-slate-700 bg-slate-100'
    : 'text-blue-700 bg-blue-100'
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

onMounted(reload)
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Mis vehículos</h1>
    <p class="text-sm text-slate-500 mb-6">
      Alta, edición y personas que conducen tus vehículos
    </p>

    <p
      v-if="error"
      class="mb-4 text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
      role="alert"
    >
      {{ error }}
    </p>

    <!-- Alta -->
    <section class="bg-white rounded-xl shadow-card p-5 mb-6">
      <h2 class="font-semibold mb-3">Añadir vehículo</h2>
      <form class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" @submit.prevent="onCreate">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="veh-matricula">
            Matrícula
          </label>
          <input
            id="veh-matricula"
            v-model="createForm.plate"
            type="text"
            maxlength="16"
            placeholder="1234ABC"
            required
            :disabled="creating"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="veh-marca">Marca</label>
          <input
            id="veh-marca"
            v-model="createForm.brand"
            type="text"
            maxlength="64"
            :disabled="creating"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="veh-modelo">Modelo</label>
          <input
            id="veh-modelo"
            v-model="createForm.model"
            type="text"
            maxlength="64"
            :disabled="creating"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="veh-color">Color</label>
          <input
            id="veh-color"
            v-model="createForm.color"
            type="text"
            maxlength="32"
            :disabled="creating"
            class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
          />
        </div>
        <div class="flex items-end">
          <button
            type="submit"
            class="w-full px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            :disabled="creating"
          >
            {{ creating ? 'Añadiendo…' : 'Añadir' }}
          </button>
        </div>
      </form>
      <p class="mt-2 text-xs text-slate-500">
        Al añadirlo, tú quedas como <strong>propietario</strong>.
      </p>
    </section>

    <!-- Listado -->
    <section class="bg-white rounded-xl shadow-card p-5">
      <h2 class="font-semibold mb-3">Tus vehículos</h2>

      <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>
      <div v-else-if="!vehicles.length" class="text-sm text-slate-500">
        Todavía no tienes vehículos. Añade el primero con el formulario de arriba.
      </div>

      <ul v-else class="divide-y divide-slate-100">
        <li v-for="v in vehicles" :key="v.id" class="py-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div class="flex items-center gap-2">
                <span class="font-mono text-lg font-semibold">{{ v.plate }}</span>
                <span
                  :class="['text-xs font-semibold px-2 py-0.5 rounded', roleBadge(v.my_role)]"
                >
                  {{ roleLabel(v.my_role) }}
                </span>
              </div>
              <div class="text-xs text-slate-500 mt-1">
                {{ [v.brand, v.model, v.color].filter(Boolean).join(' · ') || 'Sin detalles' }}
              </div>
            </div>
            <div class="flex items-center gap-2">
              <button
                v-if="v.my_role === 'propietario'"
                type="button"
                class="px-3 py-1.5 text-xs rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50"
                @click="editingId === v.id ? cancelEdit() : startEdit(v)"
              >
                {{ editingId === v.id ? 'Cancelar' : 'Editar' }}
              </button>
              <button
                v-if="v.my_role === 'propietario'"
                type="button"
                class="px-3 py-1.5 text-xs rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50"
                @click="startLink(v)"
              >
                Vincular persona
              </button>
            </div>
          </div>

          <!-- Edición -->
          <form
            v-if="editingId === v.id"
            class="mt-3 grid gap-3 sm:grid-cols-4 bg-slate-50 rounded-lg p-3"
            @submit.prevent="onSaveEdit(v)"
          >
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1">Marca</label>
              <input
                v-model="editForm.brand"
                type="text"
                maxlength="64"
                class="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1">Modelo</label>
              <input
                v-model="editForm.model"
                type="text"
                maxlength="64"
                class="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1">Color</label>
              <input
                v-model="editForm.color"
                type="text"
                maxlength="32"
                class="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div class="flex items-end gap-2">
              <button
                type="submit"
                class="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                :disabled="saving"
              >
                {{ saving ? 'Guardando…' : 'Guardar' }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 text-xs rounded-md border border-slate-300 text-slate-700"
                @click="cancelEdit"
              >
                Cancelar
              </button>
            </div>
          </form>

          <!-- Vínculos -->
          <div class="mt-3">
            <div class="text-xs text-slate-500 mb-1">Personas vinculadas</div>
            <ul class="flex flex-wrap gap-2">
              <li
                v-for="l in v.links"
                :key="l.user_id"
                class="flex items-center gap-2 text-xs bg-slate-50 border border-slate-200 rounded-md px-2 py-1"
              >
                <span>{{ l.full_name || l.email }}</span>
                <span :class="['px-1.5 py-0.5 rounded', roleBadge(l.role)]">
                  {{ roleLabel(l.role) }}
                </span>
                <button
                  v-if="v.my_role === 'propietario' || l.user_id === auth.user?.id"
                  type="button"
                  class="text-rose-600 hover:underline"
                  @click="onUnlink(v, l.user_id)"
                >
                  Quitar
                </button>
              </li>
            </ul>
          </div>

          <!-- Alta de vínculo -->
          <form
            v-if="linkForm && linkForm.vehicleId === v.id"
            class="mt-3 flex flex-wrap items-end gap-3 bg-slate-50 rounded-lg p-3"
            @submit.prevent="onLink"
          >
            <div class="flex-1 min-w-[220px]">
              <label class="block text-xs font-medium text-slate-700 mb-1" for="link-email">
                Correo de la persona
              </label>
              <input
                id="link-email"
                v-model="linkForm.email"
                type="email"
                required
                placeholder="persona@ejemplo.es"
                class="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700 mb-1" for="link-rol">Rol</label>
              <select
                id="link-rol"
                v-model="linkForm.role"
                class="rounded-md border border-slate-300 px-3 py-1.5 text-sm bg-white"
              >
                <option value="conductor">Conductor</option>
                <option value="propietario">Propietario</option>
              </select>
            </div>
            <div class="flex gap-2">
              <button
                type="submit"
                class="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                :disabled="linking"
              >
                {{ linking ? 'Vinculando…' : 'Vincular' }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 text-xs rounded-md border border-slate-300 text-slate-700"
                @click="linkForm = null"
              >
                Cancelar
              </button>
            </div>
          </form>
        </li>
      </ul>
    </section>
  </AppLayout>
</template>
