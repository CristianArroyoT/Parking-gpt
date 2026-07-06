/**
 * Cliente HTTP compartido. Adjunta el access token, gestiona refresh
 * automático ante 401 y expone helpers tipados por endpoint.
 *
 * Formato de tokens (Pydantic `TokenPair`):
 *   access_token:  str  (TTL 15 min)
 *   refresh_token: str  (TTL 7 días)
 *   token_type:    str  ("bearer")
 *   expires_in:    int  (segundos)
 */
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

// El frontend SIEMPRE habla con rutas relativas '/api/v1'. Vite las
// redirige al backend (docker-compose: http://backend:8000, local:
// http://localhost:8000) según VITE_PROXY_TARGET, variable que NO se
// inyecta al bundle porque su nombre no empieza por VITE_API_*.
const baseURL = '/api/v1'

export const http: AxiosInstance = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

// ── Tokens (persistidos en sessionStorage: se borran al cerrar pestaña) ──
const ACCESS_KEY = 'solidapp.access'
const REFRESH_KEY = 'solidapp.refresh'

export function setTokens(access: string, refresh: string): void {
  sessionStorage.setItem(ACCESS_KEY, access)
  sessionStorage.setItem(REFRESH_KEY, refresh)
}

export function setAccessToken(access: string): void {
  sessionStorage.setItem(ACCESS_KEY, access)
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY)
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}

// ── Interceptor: Authorization header ──────────────────────────────────
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Interceptor: refresh en 401, una sola vez por petición ─────────────
let refreshing: Promise<string | null> | null = null

async function doRefresh(): Promise<string | null> {
  const refresh = getRefreshToken()
  if (!refresh) return null
  try {
    const { data } = await axios.post<{
      access_token: string
      refresh_token: string
      expires_in: number
    }>(`${baseURL}/auth/refresh`, { refresh_token: refresh })
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch {
    clearTokens()
    return null
  }
}

http.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !original.url?.includes('/auth/')
    ) {
      original._retry = true
      refreshing = refreshing ?? doRefresh()
      const newAccess = await refreshing
      refreshing = null
      if (newAccess) {
        original.headers = original.headers ?? {}
        original.headers.Authorization = `Bearer ${newAccess}`
        return http(original)
      }
    }
    return Promise.reject(error)
  },
)

// ── Tipos compartidos (espejo de los schemas Pydantic) ─────────────────
export interface User {
  id: number
  email: string
  full_name: string
  phone: string | null
  role: 'admin' | 'gestor' | 'operador' | 'cliente'
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

// ── Tipos de alta manual (espejo de app/schemas/ticket.py) ───────────
export type ManualEntryReason = 'camera_down' | 'ocr_failed' | 'other'
export type TicketDirection = 'entry' | 'exit'
export type TicketOrigin =
  | 'automatic'
  | 'manual_entry'
  | 'manual_exit'

export interface ManualEntryPayload {
  plate: string
  direction: TicketDirection
  parking_id: number
  parking_space_id?: number | null
  reason: ManualEntryReason
  notes?: string | null
  camera_id?: number | null
  occurred_at?: string | null
}

// ── Tipos de incidentes (marcar plaza, reportar robo, rehabilitar) ───
export type IncidentKind = 'space_broken' | 'space_unbroken' | 'robery_reported'
export type IncidentReason =
  | 'physical_damage' | 'paint' | 'sensor_failure'
  | 'theft_attempt' | 'suspicious_behavior' | 'other'
export interface IncidentCreatePayload {
  kind: IncidentKind
  parking_space_id?: number | null
  plate?: string | null
  reason: IncidentReason
  notes?: string | null
  photos?: string[]
}

// ── Resumen operativo de tickets (Sprint Fase 4-parte-2) ─────────────
// Espejo de app/schemas/ticket_summary.py::TicketSummaryRead.
export interface TicketSummary {
  total_tickets_24h: number
  active_tickets_now: number
  closed_tickets_24h: number
  cancelled_tickets_24h: number
  total_revenue_24h: number | null
  average_duration_minutes: number | null
  window_hours: number
}

export async function getTicketSummary(parkingId: number): Promise<TicketSummary> {
  const r = await http.get<TicketSummary>(
    `/parkings/${parkingId}/tickets/summary`,
  )
  return r.data
}

// ── Costes operativos + reporte de margen (Sprint P1, 2026-07-06) ────
// Espejo de app/schemas/cost.py y app/schemas/reports.py.
export type CostCategory = 'mantenimiento' | 'camaras' | 'operacion' | 'otros'
export type CostPeriod = 'puntual' | 'mensual' | 'trimestral' | 'anual'

export interface Cost {
  id: number
  parking_id: number
  category: CostCategory
  amount: number
  periodicity: CostPeriod
  period_start: string
  period_end: string | null
  description: string | null
  created_at: string
  updated_at: string
}

export interface CostCreatePayload {
  parking_id: number
  category: CostCategory
  amount: number
  periodicity: CostPeriod
  period_start: string
  period_end?: string | null
  description?: string | null
}

export interface CostBreakdownEntry {
  category: CostCategory
  amount: number
  cost_count: number
}

export interface MarginReport {
  parking_id: number
  parking_name: string
  from: string
  to: string
  total_revenue: number
  closed_tickets: number
  total_costs: number
  margin: number
  cost_breakdown: CostBreakdownEntry[]
}

export async function listCosts(params: {
  parking_id?: number
  category?: CostCategory
  periodicity?: CostPeriod
  from?: string
  to?: string
}): Promise<Cost[]> {
  const r = await http.get<Cost[]>('/admin/costs', { params })
  return r.data
}

export async function createCost(payload: CostCreatePayload): Promise<Cost> {
  const r = await http.post<Cost>('/admin/costs', payload)
  return r.data
}

export async function deleteCost(id: number): Promise<void> {
  await http.delete(`/admin/costs/${id}`)
}

export async function getMarginReport(params: {
  parking_id: number
  from: string
  to: string
}): Promise<MarginReport> {
  const r = await http.get<MarginReport>('/admin/reports/margins', { params })
  return r.data
}

export function downloadMarginReportCsv(params: {
  parking_id: number
  from: string
  to: string
}): string {
  // Construye la URL para descargar como ``Blob`` (el interceptor
  // añade el Authorization Bearer).
  const qs = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ).toString()
  return `${baseURL}/admin/reports/margins.csv?${qs}`
}

// ── Dashboard KPIs (Sprint UI Costes + Dashboard KPIs, 2026-07-06) ────
// Espejo de app/schemas/dashboard_kpis.py.
// Admin-only. ``parking_id`` ausente = agregado de TODAS las sucursales.
export interface DashboardSpaces {
  total: number
  occupied: number
  free: number
  broken: number
}

export interface DashboardCameras {
  total: number
  operational: number
  alert: number
  never_probed: number
}

export interface DashboardMoneyPeriod {
  day: number | null
  week: number | null
  month: number | null
}

export interface DashboardKpis {
  parking_id: number | null
  spaces: DashboardSpaces
  cameras: DashboardCameras
  revenue: DashboardMoneyPeriod
  costs: DashboardMoneyPeriod
  window_hours_day: number
  window_hours_week: number
  window_hours_month: number
}

export async function getDashboardKpis(
  parkingId?: number,
): Promise<DashboardKpis> {
  const r = await http.get<DashboardKpis>('/admin/dashboard/kpis', {
    params: parkingId !== undefined ? { parking_id: parkingId } : {},
  })
  return r.data
}