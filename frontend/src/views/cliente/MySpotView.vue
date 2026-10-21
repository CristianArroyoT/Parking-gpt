<script setup lang="ts">
/**
 * "Mi plaza" (T-24 · PWA del cliente final).
 *
 * Dónde está mi coche ahora mismo. La información viene del router
 * ``/cliente`` del backend (`backend/app/api/v1/cliente.py`), que acota
 * por `vehicle_users`: el cliente sólo ve sus propios vehículos.
 *
 * Datos que se muestran:
 *   - Plaza ocupada ahora mismo (ticket activo): etiqueta de plaza,
 *     sucursal, hora de entrada y tiempo transcurrido.
 *   - Aviso si la plaza figura como averiada (`is_broken`).
 *   - Mis vehículos (los vinculados a mi cuenta).
 *
 * Si la API no está desplegada todavía (el router `/cliente` aún no
 * registrado), la pantalla cae en el estado de error con un botón de
 * reintento: nunca se inventa una plaza que no se conoce.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { listarPlazas, type ClientePlaza } from '@/api/cliente'
// Los vehículos los sirve el endpoint user-scoped de T-19 (`/users/me/vehicles`):
// no se duplica aquí.
import { listMyVehicles, type MyVehicle } from '@/api/userScope'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const plazas = ref<ClientePlaza[]>([])
const vehiculos = ref<MyVehicle[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
// Reloj para el tiempo transcurrido: se refresca cada 30 s.
const ahora = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null

async function cargar(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [p, v] = await Promise.all([listarPlazas(), listMyVehicles()])
    plazas.value = p
    vehiculos.value = v
  } catch (err: unknown) {
    const msg = extractError(err, 'No se pudo cargar la información de tu plaza')
    error.value = msg
    ui.pushToast('error', msg)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void cargar()
  ticker = setInterval(() => {
    ahora.value = Date.now()
  }, 30_000)
})

onBeforeUnmount(() => {
  if (ticker !== null) clearInterval(ticker)
})

// ── Presentación ────────────────────────────────────────────────

function fmtFecha(d: string): string {
  return new Date(d).toLocaleString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtHora(d: string): string {
  return new Date(d).toLocaleTimeString('es-ES', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Tiempo transcurrido desde la entrada, en días/horas/minutos. */
function transcurrido(entrada: string): string {
  const ms = ahora.value - new Date(entrada).getTime()
  if (ms < 0) return '0 min'
  const mins = Math.floor(ms / 60_000)
  const dias = Math.floor(mins / 1440)
  const horas = Math.floor((mins % 1440) / 60)
  const m = mins % 60
  if (dias > 0) return `${dias} d ${horas} h`
  if (horas > 0) return `${horas} h ${m.toString().padStart(2, '0')} min`
  return `${m} min`
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

const hayVehiculos = computed(() => vehiculos.value.length > 0)
const hayPlazas = computed(() => plazas.value.length > 0)
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Mi plaza</h1>
    <p class="text-sm text-slate-500 mb-6">
      Dónde está tu coche ahora mismo
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
      <!-- Plazas ocupadas ahora mismo -->
      <section class="bg-white rounded-xl shadow-card p-5 mb-6">
        <h2 class="font-semibold mb-3">En el parking ahora mismo</h2>

        <div v-if="!hayVehiculos" class="text-sm text-slate-500">
          <p>
            No tienes ningún vehículo vinculado a tu cuenta todavía.
          </p>
          <p class="mt-2 text-xs text-slate-400">
            Pide al gestor que asocie tu matrícula a tu usuario para poder
            ver aquí tu plaza y tus tickets.
          </p>
        </div>

        <div v-else-if="!hayPlazas" class="text-sm text-slate-500">
          <p>Tus {{ vehiculos.length }} vehículo(s) no están dentro de ningún parking.</p>
          <p class="mt-2 text-xs text-slate-400">
            En cuanto entres, aquí verás la plaza que te han asignado.
          </p>
        </div>

        <ul v-else class="space-y-4">
          <li
            v-for="p in plazas"
            :key="p.ticket_id"
            class="border border-slate-200 rounded-lg p-4"
          >
            <div class="flex items-start justify-between gap-4">
              <div>
                <div class="text-xs uppercase tracking-wide text-slate-500">
                  Plaza
                </div>
                <div class="text-3xl font-bold text-slate-900 leading-tight">
                  {{ p.space_label ?? 'Sin plaza asignada' }}
                </div>
                <div class="text-sm text-slate-600 mt-1">{{ p.parking_name }}</div>
              </div>
              <div class="text-right">
                <div class="text-xs uppercase tracking-wide text-slate-500">
                  Matrícula
                </div>
                <div class="font-mono text-sm font-semibold text-slate-900">
                  {{ p.plate }}
                </div>
              </div>
            </div>

            <dl class="grid grid-cols-2 gap-3 mt-4 text-sm">
              <div>
                <dt class="text-xs text-slate-500">Entrada</dt>
                <dd class="font-medium">{{ fmtFecha(p.entry_at) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-slate-500">Transcurrido</dt>
                <dd class="font-medium">{{ transcurrido(p.entry_at) }}</dd>
              </div>
            </dl>

            <p
              v-if="p.is_broken"
              class="mt-3 text-xs bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-3 py-2"
            >
              ⚠ Esta plaza figura como averiada. Si el coche está en mal
              estado, avisa al personal de la sucursal.
            </p>

            <p class="mt-3 text-xs text-slate-400">
              Entrada registrada a las {{ fmtHora(p.entry_at) }} ·
              ticket #{{ p.ticket_id }}
            </p>
          </li>
        </ul>
      </section>

      <!-- Mis vehículos -->
      <section class="bg-white rounded-xl shadow-card p-5">
        <h2 class="font-semibold mb-3">Mis vehículos</h2>
        <div v-if="!hayVehiculos" class="text-sm text-slate-500">
          Ninguno.
        </div>
        <ul v-else class="divide-y divide-slate-100 text-sm">
          <li
            v-for="v in vehiculos"
            :key="v.id"
            class="py-3 flex items-center justify-between"
          >
            <div>
              <div class="font-mono font-medium">{{ v.plate }}</div>
              <div class="text-xs text-slate-500">
                {{ [v.brand, v.model, v.color].filter(Boolean).join(' · ') || 'Sin detalles' }}
              </div>
            </div>
            <span
              v-if="plazas.some((p) => p.vehicle_id === v.id)"
              class="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-100 text-emerald-700"
            >
              Dentro
            </span>
            <span
              v-else
              class="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600"
            >
              Fuera
            </span>
          </li>
        </ul>
      </section>
    </template>
  </AppLayout>
</template>
