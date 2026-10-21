<script setup lang="ts">
/**
 * "Mi plan" — vista del cliente (T-18).
 *
 * Endpoint consumido: ``GET /api/v1/plans/me``. Devuelve siempre la
 * suscripción del usuario autenticado (el backend no acepta un `user_id`
 * en la entrada), así que aquí no hay forma de ver el plan de otro.
 *
 * Muestra los cuatro datos que pide el criterio de aceptación: plan, fecha
 * de alta, fecha de vencimiento, % de descuento y próximo cobro.
 *
 * Decisión D2 (2026-10-21): el cobro es **contable**. Se registra el
 * importe del plan, pero no se cobra nada porque todavía no hay pasarela de
 * pago; el aviso de la vista lo dice para que el cliente no se crea que ya
 * ha pagado.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { getMyPlan, listPlans, type MiPlan, type MiPlanEstado, type Plan } from '@/api/plans'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const miPlan = ref<MiPlan | null>(null)
const catalogo = ref<Plan[]>([])
const loading = ref(true)

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

const ESTADO_LABEL: Record<MiPlanEstado, { texto: string; clase: string }> = {
  vigente: { texto: 'Plan vigente', clase: 'text-emerald-700 bg-emerald-100' },
  caducada: { texto: 'Plan caducado', clase: 'text-amber-800 bg-amber-100' },
  cancelada: { texto: 'Suscripción dada de baja', clase: 'text-slate-600 bg-slate-100' },
  sin_plan: { texto: 'Sin plan', clase: 'text-slate-600 bg-slate-100' },
}

onMounted(async () => {
  try {
    const [plan, catalogoPlanes] = await Promise.all([
      getMyPlan(),
      listPlans(true),
    ])
    miPlan.value = plan
    catalogo.value = catalogoPlanes
  } catch (err: unknown) {
    ui.pushToast('error', extractError(err, 'No se pudo cargar tu plan'))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout>
    <div class="mb-6">
      <h1 class="text-2xl font-semibold tracking-tight">Mi plan</h1>
      <p class="text-sm text-slate-500">
        Tu suscripción y el descuento que se aplica al cerrar cada ticket.
      </p>
    </div>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else-if="miPlan">
      <!-- Aviso de cobro contable (decisión D2). -->
      <div
        class="mb-6 rounded-xl border border-amber-300 bg-amber-50 px-5 py-4 text-sm text-amber-900"
        role="note"
      >
        <span class="font-semibold">Cobro contable.</span>
        {{ miPlan.billing_note }}
      </div>

      <!-- Plan actual -->
      <section class="bg-white rounded-xl shadow-card p-5 mb-6">
        <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h2 class="font-semibold">
              {{ miPlan.plan ? miPlan.plan.name : 'Sin plan' }}
            </h2>
            <p v-if="miPlan.plan" class="text-xs text-slate-500">
              {{ miPlan.plan.code }} · {{ euro(miPlan.plan.monthly_price) }}/mes ·
              {{ miPlan.plan.included_vehicles }} vehículo(s) incluido(s)
            </p>
          </div>
          <span
            :class="[
              'text-xs font-semibold px-2 py-1 rounded',
              ESTADO_LABEL[miPlan.status].clase,
            ]"
          >
            {{ ESTADO_LABEL[miPlan.status].texto }}
          </span>
        </div>

        <div v-if="miPlan.plan" class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <div class="text-xs text-slate-500">Descuento aplicado</div>
            <div class="text-xl font-semibold text-emerald-700">
              {{ pct(miPlan.plan.discount_percent) }}
            </div>
            <div class="text-xs text-slate-500 mt-1">
              {{
                miPlan.applies_discount
                  ? 'Se aplica a todos tus tickets.'
                  : 'Ahora mismo no se aplica a tus tickets.'
              }}
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <div class="text-xs text-slate-500">Fecha de alta</div>
            <div class="font-medium">{{ fmtDate(miPlan.starts_at) }}</div>
          </div>
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <div class="text-xs text-slate-500">Vencimiento</div>
            <div class="font-medium">{{ fmtDate(miPlan.ends_at) }}</div>
            <div v-if="miPlan.applies_discount && miPlan.days_remaining !== null" class="text-xs text-slate-500 mt-1">
              Quedan {{ miPlan.days_remaining }} día(s)
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <div class="text-xs text-slate-500">Próximo cobro</div>
            <div class="font-medium">
              {{ miPlan.next_billing_at ? fmtDate(miPlan.next_billing_at) : '—' }}
            </div>
            <div class="text-xs text-slate-500 mt-1">
              {{ miPlan.next_billing_amount ? euro(miPlan.next_billing_amount) : '—' }}
              <span v-if="miPlan.next_billing_amount">(importe contable, sin cobro todavía)</span>
            </div>
          </div>
        </div>

        <p v-else class="text-sm text-slate-500">
          Todavía no tienes ningún plan. Contacta con administración para
          suscribirte a uno de los planes disponibles.
        </p>
      </section>

      <!-- Catálogo de planes -->
      <section class="bg-white rounded-xl shadow-card overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200">
          <h2 class="font-semibold">Planes disponibles</h2>
          <p class="text-xs text-slate-500 mt-0.5">
            El descuento se aplica automáticamente a los tickets de los
            vehículos vinculados a tu cuenta.
          </p>
        </div>
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th class="px-5 py-3 font-medium">Plan</th>
              <th class="px-5 py-3 font-medium">€/mes</th>
              <th class="px-5 py-3 font-medium">Descuento</th>
              <th class="px-5 py-3 font-medium">Vehículos</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-if="!catalogo.length">
              <td colspan="4" class="px-5 py-6 text-center text-slate-500">
                No hay planes disponibles ahora mismo.
              </td>
            </tr>
            <tr v-for="p in catalogo" v-else :key="p.id">
              <td class="px-5 py-3 font-medium">{{ p.name }}</td>
              <td class="px-5 py-3">{{ euro(p.monthly_price) }}</td>
              <td class="px-5 py-3 text-emerald-700 font-medium">
                {{ pct(p.discount_percent) }}
              </td>
              <td class="px-5 py-3">{{ p.included_vehicles }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </AppLayout>
</template>
