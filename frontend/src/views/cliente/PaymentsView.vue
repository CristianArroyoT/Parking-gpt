<script setup lang="ts">
/**
 * "Pago" (T-24 · PWA del cliente final).
 *
 * IMPORTANTE — cobro contable, sin pasarela (decisión D2 del plan
 * maestro 2026-10-21): esta pantalla **no cobra**. No hay TPV, no hay
 * redirección a un gateway, no se piden datos de tarjeta y no hay ningún
 * "botón de pagar" que haga algo que no debe. Mientras no haya cliente
 * piloto, el cobro es contable: el personal de la sucursal registra el
 * pago del ticket y esta pantalla sólo informa del importe pendiente.
 *
 * Datos:
 *   - `GET /cliente/tickets?solo_pendientes=true` → tickets sin pagar (T-24).
 *   - `GET /cliente/tickets`                       → histórico (cobrados).
 *   - `GET /plans/me`                              → plan y suscripción (T-18).
 *
 * El % de descuento del plan se muestra como información: es el mismo
 * que el servicio de precios ya aplicó al cerrar el ticket (por eso el
 * ticket trae su propio importe de descuento ya descontado).
 */
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { listarTickets, type ClienteTicket } from '@/api/cliente'
import { getMyPlan, type MiPlan } from '@/api/plans'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const pendientes = ref<ClienteTicket[]>([])
const historial = ref<ClienteTicket[]>([])
const plan = ref<MiPlan | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function cargar(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [pend, todos, miPlan] = await Promise.all([
      listarTickets(true),
      listarTickets(false),
      getMyPlan(),
    ])
    pendientes.value = pend
    historial.value = todos.filter((t) => !t.pending_payment)
    plan.value = miPlan
  } catch (err: unknown) {
    const msg = extractError(err, 'No se pudo cargar la información de pago')
    error.value = msg
    ui.pushToast('error', msg)
  } finally {
    loading.value = false
  }
}

onMounted(cargar)

// ── Presentación ────────────────────────────────────────────────

/** El plan sólo se muestra si está vigente (`GET /plans/me`). */
const planActivo = computed(() => {
  const p = plan.value
  if (!p || p.status !== 'vigente' || !p.plan) return null
  return p.plan
})

/** Días que le quedan al plan vigente. */
const diasRestantes = computed(() => plan.value?.days_remaining ?? null)

function eur(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toFixed(2).replace('.', ',') + ' €'
}

function fmtFecha(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Suma de los importes pendientes (los tickets con `total`). */
const totalPendiente = computed(() =>
  pendientes.value.reduce((acc, t) => acc + (t.total ?? 0), 0),
)

/** Tickets pagados (o free) que ya no están pendientes. */
const yaCobrados = computed(() =>
  historial.value.filter((t) => t.total !== null && t.total > 0),
)

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Pago</h1>
    <p class="text-sm text-slate-500 mb-6">
      Tickets y saldo pendiente de tus vehículos
    </p>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <div
      v-else-if="error"
      class="bg-white rounded-xl shadow-card p-5 border border-rose-200"
      role="alert"
    >
      <p class="text-sm text-rose-700">{{ error }}</p>
      <button type="button" class="btn-secondary mt-4" @click="cargar">
        Reintentar
      </button>
    </div>

    <template v-else>
      <!-- Aviso: no hay pasarela de pago (decisión D2) -->
      <section
        class="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6 text-sm text-amber-900"
        role="note"
      >
        <h2 class="font-semibold mb-1">El cobro se hace en la sucursal, no en la app</h2>
        <p>
          En esta versión el pago es <strong>contable</strong>: no hay pasarela
          de pago, no se pide tarjeta y la app no procesa ningún cobro. Aquí
          sólo ves <strong>cuánto tienes pendiente</strong> y el personal de
          la sucursal registra el pago del ticket por los medios habituales
          (efectivo, TPV o transferencia).
        </p>
      </section>

      <!-- Resumen -->
      <section class="bg-white rounded-xl shadow-card p-5 mb-6">
        <div class="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div class="text-xs uppercase tracking-wide text-slate-500">
              Total pendiente de pago
            </div>
            <div class="text-3xl font-bold text-slate-900 mt-1">
              {{ eur(totalPendiente) }}
            </div>
            <div class="text-xs text-slate-500 mt-1">
              {{ pendientes.length }} ticket(s) sin pagar
            </div>
          </div>
          <div
            v-if="planActivo"
            class="text-sm bg-blue-50 border border-blue-200 rounded-lg px-3 py-2"
          >
            <div class="font-semibold text-blue-900">Plan {{ planActivo.name }}</div>
            <div class="text-xs text-blue-800">
              {{ eur(planActivo.monthly_price) }}/mes ·
              <strong>{{ planActivo.discount_percent }} % de descuento</strong>
            </div>
          </div>
        </div>
      </section>

      <!-- Tickets pendientes -->
      <section class="bg-white rounded-xl shadow-card p-5 mb-6">
        <h2 class="font-semibold mb-3">Tickets pendientes de pago</h2>

        <div v-if="!pendientes.length" class="text-sm text-slate-500">
          No tienes ningún ticket pendiente de pago.
        </div>

        <ul v-else class="divide-y divide-slate-100 text-sm">
          <li v-for="t in pendientes" :key="t.id" class="py-4">
            <div class="flex items-start justify-between gap-4">
              <div>
                <div class="font-medium">
                  Ticket #{{ t.id }} · <span class="font-mono">{{ t.plate }}</span>
                </div>
                <div class="text-xs text-slate-500 mt-0.5">
                  {{ t.parking_name }}
                  <span v-if="t.space_label"> · Plaza {{ t.space_label }}</span>
                </div>
                <div
                  v-if="t.days_pending !== null"
                  class="text-xs mt-1 inline-block px-2 py-0.5 rounded"
                  :class="t.days_pending > 30
                    ? 'bg-rose-100 text-rose-700'
                    : 'bg-slate-100 text-slate-600'"
                >
                  Pendiente desde hace {{ t.days_pending }} día(s)
                </div>
              </div>
              <div class="text-right">
                <div class="font-semibold text-slate-900">{{ eur(t.total) }}</div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-3 mt-3 text-xs text-slate-500">
              <div>
                <div>Entrada</div>
                <div class="text-slate-700">{{ fmtFecha(t.entry_at) }}</div>
              </div>
              <div>
                <div>Salida</div>
                <div class="text-slate-700">{{ fmtFecha(t.exit_at) }}</div>
              </div>
            </div>

            <div
              v-if="t.amount !== null"
              class="mt-3 border-t border-slate-100 pt-2 space-y-1 text-xs"
            >
              <div class="flex justify-between">
                <span class="text-slate-500">Importe base</span>
                <span class="font-mono">{{ eur(t.amount) }}</span>
              </div>
              <div v-if="t.discount" class="flex justify-between text-emerald-700">
                <span>
                  Descuento
                  <span v-if="planActivo">({{ planActivo.discount_percent }} % del plan)</span>
                </span>
                <span class="font-mono">-{{ eur(t.discount) }}</span>
              </div>
              <div class="flex justify-between font-semibold text-slate-800">
                <span>Total a pagar</span>
                <span class="font-mono">{{ eur(t.total) }}</span>
              </div>
            </div>

            <p class="mt-3 text-xs text-slate-500 bg-slate-50 rounded-md px-3 py-2">
              Para pagar: pide en la caseta de salida o al personal de
              {{ t.parking_name }} que registre este ticket. En cuanto lo
              cobren, la app se actualiza sola.
            </p>
          </li>
        </ul>
      </section>

      <!-- Plan (si lo tiene) -->
      <section v-if="planActivo" class="bg-white rounded-xl shadow-card p-5 mb-6">
        <h2 class="font-semibold mb-3">Mi plan</h2>
        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <div class="text-xs text-slate-500">Plan</div>
            <div class="font-medium">{{ planActivo.name }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Cuota mensual</div>
            <div class="font-medium">{{ eur(planActivo.monthly_price) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Descuento aplicado</div>
            <div class="font-medium">{{ planActivo.discount_percent }} %</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">Vehículos incluidos</div>
            <div class="font-medium">{{ planActivo.included_vehicles }}</div>
          </div>
        </div>
        <p
          v-if="diasRestantes !== null"
          class="mt-4 text-xs text-slate-500 bg-slate-50 rounded-md px-3 py-2"
        >
          Tu plan está vigente: quedan {{ diasRestantes }} día(s). La cuota se
          factura aparte, en la sucursal (no se cobra desde la app).
        </p>
      </section>

      <!-- Historial -->
      <section class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Historial cobrado</h2>
        <div v-if="!yaCobrados.length" class="text-sm text-slate-500">
          Todavía no hay tickets cobrados.
        </div>
        <ul v-else class="divide-y divide-slate-100 text-sm">
          <li
            v-for="t in yaCobrados.slice(0, 10)"
            :key="t.id"
            class="py-3 flex items-center justify-between"
          >
            <div>
              <div class="font-medium">
                Ticket #{{ t.id }} · <span class="font-mono">{{ t.plate }}</span>
              </div>
              <div class="text-xs text-slate-500">
                {{ t.parking_name }} · salida {{ fmtFecha(t.exit_at) }}
              </div>
            </div>
            <div class="text-right">
              <div class="font-medium">{{ eur(t.total) }}</div>
              <div class="text-xs text-emerald-700">
                {{ t.payment_method ?? 'Pagado' }}
              </div>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </AppLayout>
</template>
