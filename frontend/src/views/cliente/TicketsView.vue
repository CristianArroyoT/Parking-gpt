<script setup lang="ts">
/**
 * Sprint Fase 4 (2026-07-01): el cliente puede ver el detalle individual
 * de cada ticket. Antes sólo tenía un listado plano. Ahora click en
 * cualquier fila → modal con desglose de tarifa, plaza, método de
 * pago y enlace al PDF (si existe).
 *
 * Endpoint usado: ``GET /api/v1/tickets/{ticket_id}``. El backend ya
 * implementaba este endpoint (Fase 2) con scope por
 * ``ParkingMembership``; el cliente sólo ve los tickets de sus plazas.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { http } from '@/api/client'
import { descargarPdfTicket } from '@/api/cliente'
import { useUiStore } from '@/stores/ui'

// Tipos espejo de ``app/schemas/ticket.py::TicketRead``.
type TicketStatus = 'activo' | 'cerrado' | 'anulado'
type TicketOrigin = 'automatic' | 'manual_entry' | 'manual_exit'

interface Ticket {
  id: number
  parking_id: number
  vehicle_id: number
  parking_space_id: number | null
  status: TicketStatus
  entry_at: string
  exit_at: string | null
  amount: number | null
  discount: number | null
  total: number | null
  payment_method: string | null
  pdf_available: boolean
  origin: TicketOrigin
}

const ui = useUiStore()
const tickets = ref<Ticket[]>([])
const loading = ref(true)

// ── Modal detalle ───────────────────────────────────────────────
const selected = ref<Ticket | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
const descargandoPdf = ref(false)

/**
 * Descarga el PDF del ticket (T-97).
 *
 * Va contra la API (``GET /tickets/{id}/pdf``) en vez de enlazar el
 * fichero: un `<a href>` no puede mandar la cabecera `Authorization`,
 * y antes el enlace apuntaba a ``pdf_path``, que era la ruta del PDF
 * en el disco del servidor (un 404 y, de paso, la estructura de
 * ficheros del servidor en la respuesta de la API).
 */
async function descargarPdf(ticketId: number): Promise<void> {
  descargandoPdf.value = true
  try {
    await descargarPdfTicket(ticketId)
  } catch {
    ui.pushToast('error', 'No se ha podido generar el PDF')
  } finally {
    descargandoPdf.value = false
  }
}

async function openDetail(t: Ticket): Promise<void> {
  // Carga perezosa del detalle completo. El listado ya tiene casi todo
  // pero usamos el endpoint individual para garantizar campos frescos
  // (importe recalculado, método de pago, etc.).
  selected.value = t
  detailLoading.value = true
  detailError.value = null
  try {
    const { data } = await http.get<Ticket>(`/tickets/${t.id}`)
    selected.value = data
  } catch (err: unknown) {
    const msg = extractError(err, 'No se pudo cargar el detalle del ticket')
    detailError.value = msg
    ui.pushToast('error', msg)
  } finally {
    detailLoading.value = false
  }
}
function closeDetail(): void {
  selected.value = null
  detailError.value = null
}

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
function durationMinutes(entry: string, exit: string | null): string {
  if (!exit) return '—'
  const ms = new Date(exit).getTime() - new Date(entry).getTime()
  const mins = Math.max(0, Math.round(ms / 60000))
  const h = Math.floor(mins / 60)
  const m = mins % 60
  if (h === 0) return `${m} min`
  return `${h} h ${m.toString().padStart(2, '0')} min`
}
function statusBadge(status: TicketStatus): { label: string; cls: string } {
  if (status === 'activo') return { label: 'Activo', cls: 'text-emerald-700 bg-emerald-100' }
  if (status === 'cerrado') return { label: 'Cerrado', cls: 'text-slate-700 bg-slate-100' }
  if (status === 'anulado') return { label: 'Anulado', cls: 'text-rose-700 bg-rose-100' }
  // Un estado que no conocemos se muestra TAL CUAL: antes caia en el
  // "Anulado" de la ultima rama, que es una afirmacion falsa sobre el
  // ticket. La puerta tools/verificar_enums_frontend.py avisa si el
  // backend anade un estado que el frontend no conoce.
  return { label: status, cls: 'text-slate-700 bg-slate-100' }
}
function originLabel(o: TicketOrigin): string {
  if (o === 'automatic') return 'Automático (OCR)'
  if (o === 'manual_entry') return 'Alta manual (entrada)'
  return 'Alta manual (salida)'
}
function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
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
        <div v-if="!activos().length" class="text-sm text-slate-500">
          No tienes tickets activos.
        </div>
        <ul v-else class="divide-y divide-slate-100 text-sm">
          <li
            v-for="t in activos()"
            :key="t.id"
            class="py-3 flex justify-between items-center cursor-pointer hover:bg-slate-50 px-2 -mx-2 rounded"
            @click="openDetail(t)"
          >
            <div>
              <div class="font-medium">Ticket #{{ t.id }} · Sucursal {{ t.parking_id }}</div>
              <div class="text-xs text-slate-500">Entrada: {{ fmt(t.entry_at) }}</div>
            </div>
            <span
              :class="['text-xs font-semibold px-2 py-0.5 rounded', statusBadge(t.status).cls]"
            >{{ statusBadge(t.status).label }}</span>
          </li>
        </ul>
      </section>

      <section class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Histórico</h2>
        <div v-if="!cerrados().length" class="text-sm text-slate-500">
          Sin tickets cerrados todavía.
        </div>
        <div v-else class="overflow-x-auto min-w-0">
          <table class="w-full text-sm min-w-max">
            <thead class="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th class="px-3 py-2 font-medium">#</th>
                <th class="px-3 py-2 font-medium">Entrada</th>
                <th class="px-3 py-2 font-medium">Salida</th>
                <th class="px-3 py-2 font-medium text-right">Importe</th>
                <th class="px-3 py-2 font-medium text-right">Detalle</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr
                v-for="t in cerrados()"
                :key="t.id"
                class="cursor-pointer hover:bg-slate-50"
                @click="openDetail(t)"
              >
                <td class="px-3 py-2 font-mono text-xs">#{{ t.id }}</td>
                <td class="px-3 py-2">{{ fmt(t.entry_at) }}</td>
                <td class="px-3 py-2">{{ fmt(t.exit_at) }}</td>
                <td class="px-3 py-2 text-right font-medium">{{ eur(t.total) }}</td>
                <td class="px-3 py-2 text-right">
                  <button type="button" class="text-blue-600 hover:underline text-xs">
                    Ver detalle
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- Modal detalle ticket (Sprint Fase 4) -->
    <Teleport to="body">
      <div
        v-if="selected"
        class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`ticket-${selected.id}-title`"
        @keydown.esc="closeDetail"
        @click.self="closeDetail"
      >
        <div class="bg-white rounded-xl shadow-card w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
          <div class="flex items-start justify-between mb-4">
            <div>
              <h2 :id="`ticket-${selected.id}-title`" class="text-lg font-semibold">
                Ticket #{{ selected.id }}
              </h2>
              <p class="text-xs text-slate-500">
                Sucursal {{ selected.parking_id }}
                · <span
                  :class="['font-semibold', statusBadge(selected.status).cls.split(' ')[0]]"
                >{{ statusBadge(selected.status).label }}</span>
              </p>
            </div>
            <button
              type="button"
              class="text-slate-400 hover:text-slate-700 text-xl leading-none"
              aria-label="Cerrar"
              @click="closeDetail"
            >×</button>
          </div>

          <div v-if="detailLoading" class="text-sm text-slate-500 py-4 text-center">
            Cargando detalle…
          </div>
          <!-- T-169 (2026-10-24): el error se ANUNCIA (`role="alert"` =
               region viva). Antes solo se veia. -->
          <div
            v-else-if="detailError"
            class="text-sm text-rose-600 py-4 text-center"
            role="alert"
            aria-live="assertive"
          >
            {{ detailError }}
          </div>
          <div v-else class="space-y-4 text-sm">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <div class="text-xs text-slate-500">Entrada</div>
                <div class="font-medium">{{ fmt(selected.entry_at) }}</div>
              </div>
              <div>
                <div class="text-xs text-slate-500">Salida</div>
                <div class="font-medium">{{ fmt(selected.exit_at) }}</div>
              </div>
              <div>
                <div class="text-xs text-slate-500">Duración</div>
                <div class="font-medium">
                  {{ durationMinutes(selected.entry_at, selected.exit_at) }}
                </div>
              </div>
              <div>
                <div class="text-xs text-slate-500">Plaza</div>
                <div class="font-medium">
                  {{ selected.parking_space_id ?? '—' }}
                </div>
              </div>
            </div>

            <div class="border-t border-slate-200 pt-3">
              <div class="text-xs text-slate-500 mb-2">Desglose de tarifa</div>
              <div class="space-y-1">
                <div class="flex justify-between">
                  <span>Importe base</span>
                  <span class="font-mono">{{ eur(selected.amount) }}</span>
                </div>
                <div v-if="selected.discount && selected.discount > 0" class="flex justify-between text-rose-700">
                  <span>Descuento</span>
                  <span class="font-mono">-{{ eur(selected.discount) }}</span>
                </div>
                <div class="flex justify-between text-base font-semibold border-t border-slate-100 pt-1">
                  <span>Total</span>
                  <span class="font-mono">{{ eur(selected.total) }}</span>
                </div>
              </div>
            </div>

            <div class="border-t border-slate-200 pt-3 grid grid-cols-2 gap-3">
              <div>
                <div class="text-xs text-slate-500">Método de pago</div>
                <div class="font-medium">{{ selected.payment_method ?? '—' }}</div>
              </div>
              <div>
                <div class="text-xs text-slate-500">Origen</div>
                <div class="font-medium">{{ originLabel(selected.origin) }}</div>
              </div>
            </div>

            <div v-if="selected.pdf_available" class="border-t border-slate-200 pt-3">
              <button
                type="button"
                class="btn-secondary inline-flex items-center gap-2"
                :disabled="descargandoPdf"
                @click="descargarPdf(selected.id)"
              >
                <span>📄</span>
                {{ descargandoPdf ? 'Generando PDF…' : 'Descargar PDF' }}
              </button>
            </div>
          </div>

          <div class="mt-6 flex justify-end">
            <button type="button" class="btn-secondary" @click="closeDetail">
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>