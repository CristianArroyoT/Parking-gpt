<script setup lang="ts">
/**
 * Planes y suscripciones — vista admin (T-18).
 *
 * Endpoints consumidos:
 *   - GET    /plans                    — catálogo de planes.
 *   - POST   /plans                    — alta de plan.
 *   - PATCH  /plans/{id}               — edición de plan (precio, descuento,
 *                                        activar/desactivar).
 *   - DELETE /plans/{id}               — baja de plan (409 si tiene
 *                                        suscripciones: hay que desactivarlo).
 *   - GET    /plans/subscriptions      — suscripciones vigentes.
 *   - POST   /plans/subscriptions      — alta de suscripción.
 *   - DELETE /plans/subscriptions/{id} — baja de suscripción.
 *   - GET    /users                    — clientes a los que suscribir.
 *
 * Decisión D2 (2026-10-21): el cobro de los planes es **contable**. Se
 * registra el precio y la suscripción, pero no se cobra nada todavía porque
 * no hay pasarela de pago. El aviso de arriba lo deja explícito para que
 * nadie (ni el admin) lo lea como un cobro real.
 *
 * RBAC: admin-only (la guarda del router ya redirige a otros perfiles).
 */
import { computed, onMounted, reactive, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import {
  cancelSubscription,
  createPlan,
  createSubscription,
  deletePlan,
  listPlans,
  listSubscriptions,
  updatePlan,
  type Plan,
  type Subscription,
} from '@/api/plans'
import { http, type User } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const plans = ref<Plan[]>([])
const subscriptions = ref<Subscription[]>([])
const clientes = ref<User[]>([])
const loading = ref(true)
const editing = ref<Plan | null>(null)

type PlanForm = {
  code: string
  name: string
  monthly_price: number
  discount_percent: number
  included_vehicles: number
  is_active: boolean
}

const EMPTY_FORM: PlanForm = {
  code: '',
  name: '',
  monthly_price: 30,
  discount_percent: 5,
  included_vehicles: 0,
  is_active: true,
}
const form = reactive<PlanForm>({ ...EMPTY_FORM })

// ── Formulario de suscripción ─────────────────────────────────────────
const showSubForm = ref(false)
const subForm = reactive({
  user_id: null as number | null,
  plan_id: null as number | null,
  starts_at: toLocalInput(new Date()),
  ends_at: toLocalInput(addMonths(new Date(), 1)),
})
const subSaving = ref(false)

// ── Helpers ────────────────────────────────────────────────────────────

function toLocalInput(d: Date): string {
  // datetime-local espera "YYYY-MM-DDTHH:mm" en hora local.
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromLocalInput(v: string): string {
  // "YYYY-MM-DDTHH:mm" → ISO 8601 con zona (lo que Pydantic acepta).
  return new Date(v).toISOString()
}

function addMonths(d: Date, months: number): Date {
  const copia = new Date(d)
  copia.setMonth(copia.getMonth() + months)
  return copia
}

function euro(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(2).replace('.', ',')} €`
}

function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(2).replace('.', ',')} %`
}

function fmtDate(v: string | null): string {
  if (!v) return '—'
  return new Date(v).toLocaleString('es-ES', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

// ── Carga ──────────────────────────────────────────────────────────────

async function loadPlans(): Promise<void> {
  try {
    plans.value = await listPlans()
  } catch {
    ui.pushToast('error', 'No se pudieron cargar los planes')
  }
}

async function loadSubscriptions(): Promise<void> {
  try {
    subscriptions.value = await listSubscriptions()
  } catch {
    ui.pushToast('error', 'No se pudieron cargar las suscripciones')
  }
}

async function loadClientes(): Promise<void> {
  try {
    const { data } = await http.get<User[]>('/users')
    clientes.value = data.filter((u) => u.role === 'cliente')
  } catch {
    ui.pushToast('error', 'No se pudieron cargar los clientes')
  }
}

async function reload(): Promise<void> {
  await Promise.all([loadPlans(), loadSubscriptions()])
}

// ── Acciones sobre planes ──────────────────────────────────────────────

function startCreate(): void {
  editing.value = null
  Object.assign(form, EMPTY_FORM)
}

function startEdit(p: Plan): void {
  editing.value = p
  Object.assign(form, {
    code: p.code,
    name: p.name,
    monthly_price: p.monthly_price,
    discount_percent: p.discount_percent,
    included_vehicles: p.included_vehicles,
    is_active: p.is_active,
  })
}

async function submitPlan(): Promise<void> {
  const payload = {
    code: form.code.trim(),
    name: form.name.trim(),
    monthly_price: Number(form.monthly_price),
    discount_percent: Number(form.discount_percent),
    included_vehicles: Number(form.included_vehicles),
    is_active: form.is_active,
  }
  if (!payload.code || !payload.name) {
    ui.pushToast('warn', 'El código y el nombre son obligatorios')
    return
  }
  if (payload.discount_percent < 0 || payload.discount_percent > 100) {
    ui.pushToast('warn', 'El descuento debe estar entre 0 y 100 %')
    return
  }
  try {
    if (editing.value) {
      await updatePlan(editing.value.id, payload)
      ui.pushToast('success', 'Plan actualizado')
    } else {
      await createPlan(payload)
      ui.pushToast('success', 'Plan creado')
    }
    startCreate()
    await reload()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo guardar el plan'))
  }
}

async function toggleActive(p: Plan): Promise<void> {
  try {
    await updatePlan(p.id, { is_active: !p.is_active })
    ui.pushToast('success', p.is_active ? 'Plan desactivado' : 'Plan activado')
    await reload()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo cambiar el estado del plan'))
  }
}

async function removePlan(p: Plan): Promise<void> {
  if (!confirm(`¿Eliminar el plan "${p.name}"?`)) return
  try {
    await deletePlan(p.id)
    ui.pushToast('success', 'Plan eliminado')
    await reload()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo eliminar el plan'))
  }
}

// ── Acciones sobre suscripciones ───────────────────────────────────────

async function submitSubscription(): Promise<void> {
  if (subForm.user_id === null || subForm.plan_id === null) {
    ui.pushToast('warn', 'Elige cliente y plan')
    return
  }
  subSaving.value = true
  try {
    await createSubscription({
      user_id: subForm.user_id,
      plan_id: subForm.plan_id,
      starts_at: fromLocalInput(subForm.starts_at),
      ends_at: fromLocalInput(subForm.ends_at),
    })
    ui.pushToast('success', 'Suscripción creada')
    showSubForm.value = false
    subForm.user_id = null
    subForm.plan_id = null
    subForm.starts_at = toLocalInput(new Date())
    subForm.ends_at = toLocalInput(addMonths(new Date(), 1))
    await reload()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo crear la suscripción'))
  } finally {
    subSaving.value = false
  }
}

async function cancel(s: Subscription): Promise<void> {
  if (!confirm(`¿Dar de baja la suscripción de ${s.user_email}?`)) return
  try {
    await cancelSubscription(s.id)
    ui.pushToast('success', 'Suscripción dada de baja')
    await reload()
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo dar de baja la suscripción'))
  }
}

// ── Derivados ──────────────────────────────────────────────────────────

const planesActivos = computed(() => plans.value.filter((p) => p.is_active))

onMounted(async () => {
  await Promise.all([loadPlans(), loadSubscriptions(), loadClientes()])
  loading.value = false
})
</script>

<template>
  <AppLayout>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Planes</h1>
        <p class="text-sm text-slate-500">
          Planes de suscripción y clientes suscritos. El descuento del plan se
          aplica automáticamente al cerrar el ticket.
        </p>
      </div>
      <button class="btn-secondary text-sm" :disabled="loading" @click="reload">
        Refrescar
      </button>
    </div>

    <!-- Aviso de cobro contable (decisión D2): no hay pasarela de pago. -->
    <div
      class="mb-6 rounded-xl border border-amber-300 bg-amber-50 px-5 py-4 text-sm text-amber-900"
      role="note"
    >
      <span class="font-semibold">Cobro contable.</span>
      Se registra el precio del plan y la suscripción del cliente, pero
      <strong>no se cobra nada</strong>: todavía no hay pasarela de pago
      (falta un cliente piloto). El descuento sí se aplica al cerrar el
      ticket.
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Lista de planes -->
        <div class="lg:col-span-2 bg-white rounded-xl shadow-card overflow-hidden">
          <div class="px-5 py-4 border-b border-slate-200">
            <h2 class="font-semibold">Catálogo de planes</h2>
            <p class="text-xs text-slate-500 mt-0.5">
              {{ plans.length }} planes · {{ planesActivos.length }} activos
            </p>
          </div>
          <div class="overflow-x-auto min-w-0">
            <table class="w-full min-w-max text-sm">
              <thead class="bg-slate-50 text-slate-500 text-left">
                <tr>
                  <th class="px-5 py-3 font-medium">Código</th>
                  <th class="px-5 py-3 font-medium">Nombre</th>
                  <th class="px-5 py-3 font-medium">€/mes</th>
                  <th class="px-5 py-3 font-medium">Descuento</th>
                  <th class="px-5 py-3 font-medium">Vehículos</th>
                  <th class="px-5 py-3 font-medium">Estado</th>
                  <th class="px-5 py-3 font-medium text-right">Acciones</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                <tr v-if="!plans.length">
                  <td colspan="7" class="px-5 py-6 text-center text-slate-500">
                    No hay planes dados de alta.
                  </td>
                </tr>
                <tr v-for="p in plans" :key="p.id">
                  <td class="px-5 py-3 font-mono text-xs">{{ p.code }}</td>
                  <td class="px-5 py-3 font-medium">{{ p.name }}</td>
                  <td class="px-5 py-3">{{ euro(p.monthly_price) }}</td>
                  <td class="px-5 py-3">{{ pct(p.discount_percent) }}</td>
                  <td class="px-5 py-3">{{ p.included_vehicles }}</td>
                  <td class="px-5 py-3">
                    <span
                      :class="[
                        'text-xs font-semibold px-2 py-0.5 rounded',
                        p.is_active
                          ? 'text-emerald-700 bg-emerald-100'
                          : 'text-slate-600 bg-slate-100',
                      ]"
                    >
                      {{ p.is_active ? 'Activo' : 'Inactivo' }}
                    </span>
                  </td>
                  <td class="px-5 py-3 text-right space-x-2 whitespace-nowrap">
                    <button class="btn-secondary" @click="startEdit(p)">Editar</button>
                    <button class="btn-secondary" @click="toggleActive(p)">
                      {{ p.is_active ? 'Desactivar' : 'Activar' }}
                    </button>
                    <button
                      class="btn-secondary text-rose-600 border-rose-300"
                      @click="removePlan(p)"
                    >
                      Eliminar
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Formulario de plan -->
        <div class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-4">
            {{ editing ? 'Editar plan' : 'Nuevo plan' }}
          </h2>
          <form class="space-y-3" @submit.prevent="submitPlan">
            <div>
              <label class="block text-xs font-medium text-slate-700" for="plan-codigo">Código</label>
              <input id="plan-codigo"
                v-model="form.code"
                required
                minlength="2"
                maxlength="32"
                placeholder="basico"
                class="input"
              />
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700" for="plan-nombre">Nombre</label>
              <input id="plan-nombre"
                v-model="form.name"
                required
                minlength="2"
                maxlength="64"
                placeholder="Básico"
                class="input"
              />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-medium text-slate-700" for="plan-precio-mes">€/mes</label>
                <input id="plan-precio-mes"
                  v-model.number="form.monthly_price"
                  type="number"
                  step="0.01"
                  min="0"
                  required
                  class="input"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-slate-700" for="plan-descuento">Descuento %</label>
                <input id="plan-descuento"
                  v-model.number="form.discount_percent"
                  type="number"
                  step="0.01"
                  min="0"
                  max="100"
                  required
                  class="input"
                />
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-700" for="plan-vehiculos">
                Vehículos incluidos
              </label>
              <input id="plan-vehiculos"
                v-model.number="form.included_vehicles"
                type="number"
                min="0"
                required
                class="input"
              />
            </div>
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input v-model="form.is_active" type="checkbox" />
              Plan activo (los clientes pueden suscribirse)
            </label>
            <div class="flex gap-2 pt-2">
              <button type="submit" class="btn-primary">
                {{ editing ? 'Guardar cambios' : 'Crear plan' }}
              </button>
              <button v-if="editing" type="button" class="btn-secondary" @click="startCreate">
                Cancelar
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- Suscripciones -->
      <section class="bg-white rounded-xl shadow-card overflow-hidden mt-6">
        <div class="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            <h2 class="font-semibold">Suscripciones</h2>
            <p class="text-xs text-slate-500 mt-0.5">
              {{ subscriptions.length }} registradas · la baja deja de aplicar
              descuento pero conserva el histórico
            </p>
          </div>
          <button class="btn-primary text-sm" @click="showSubForm = !showSubForm">
            {{ showSubForm ? 'Cancelar' : 'Nueva suscripción' }}
          </button>
        </div>

        <div
          v-if="showSubForm"
          class="px-5 py-4 bg-slate-50 border-b border-slate-200"
        >
          <form
            class="grid grid-cols-1 md:grid-cols-4 gap-3"
            @submit.prevent="submitSubscription"
          >
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Cliente</span>
              <select v-model.number="subForm.user_id" class="input w-full" required>
                <option :value="null">Selecciona…</option>
                <option v-for="c in clientes" :key="c.id" :value="c.id">
                  {{ c.full_name }} · {{ c.email }}
                </option>
              </select>
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Plan</span>
              <select v-model.number="subForm.plan_id" class="input w-full" required>
                <option :value="null">Selecciona…</option>
                <option v-for="p in planesActivos" :key="p.id" :value="p.id">
                  {{ p.name }} ({{ pct(p.discount_percent) }})
                </option>
              </select>
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Alta</span>
              <input v-model="subForm.starts_at" type="datetime-local" class="input w-full" required />
            </label>
            <label class="text-sm">
              <span class="block text-slate-700 mb-1">Vence</span>
              <input v-model="subForm.ends_at" type="datetime-local" class="input w-full" required />
            </label>
            <div class="md:col-span-4 flex justify-end">
              <button type="submit" class="btn-primary text-sm" :disabled="subSaving">
                {{ subSaving ? 'Guardando…' : 'Crear suscripción' }}
              </button>
            </div>
          </form>
        </div>

        <div class="overflow-x-auto min-w-0">
          <table class="w-full min-w-max text-sm">
            <thead class="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th class="px-5 py-3 font-medium">Cliente</th>
                <th class="px-5 py-3 font-medium">Plan</th>
                <th class="px-5 py-3 font-medium">Alta</th>
                <th class="px-5 py-3 font-medium">Vence</th>
                <th class="px-5 py-3 font-medium">Estado</th>
                <th class="px-5 py-3 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-if="!subscriptions.length">
                <td colspan="6" class="px-5 py-6 text-center text-slate-500">
                  No hay suscripciones registradas.
                </td>
              </tr>
              <tr v-for="s in subscriptions" :key="s.id">
                <td class="px-5 py-3">
                  <div class="font-medium">{{ s.user_full_name }}</div>
                  <div class="text-xs text-slate-500">{{ s.user_email }}</div>
                </td>
                <td class="px-5 py-3">
                  {{ s.plan.name }}
                  <span class="text-xs text-slate-500">
                    ({{ pct(s.plan.discount_percent) }})
                  </span>
                </td>
                <td class="px-5 py-3 text-xs">{{ fmtDate(s.starts_at) }}</td>
                <td class="px-5 py-3 text-xs">{{ fmtDate(s.ends_at) }}</td>
                <td class="px-5 py-3">
                  <span
                    :class="[
                      'text-xs font-semibold px-2 py-0.5 rounded',
                      s.is_active
                        ? 'text-emerald-700 bg-emerald-100'
                        : 'text-slate-600 bg-slate-100',
                    ]"
                  >
                    {{ s.is_active ? 'Activa' : 'Dada de baja' }}
                  </span>
                </td>
                <td class="px-5 py-3 text-right">
                  <button
                    v-if="s.is_active"
                    class="btn-secondary text-rose-600 border-rose-300"
                    @click="cancel(s)"
                  >
                    Dar de baja
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppLayout>
</template>
