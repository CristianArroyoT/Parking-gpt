/**
 * Wrapper tipado del módulo de planes y suscripciones (T-18).
 *
 * Endpoints backend (`backend/app/api/v1/plans.py`):
 *   - GET    /plans                      — catálogo de planes.
 *   - POST   /plans                      — alta de plan (admin).
 *   - PATCH  /plans/{id}                 — edición de plan (admin).
 *   - DELETE /plans/{id}                 — baja de plan (admin; 409 si tiene
 *                                          suscripciones: desactívalo).
 *   - GET    /plans/subscriptions        — lista de suscripciones (admin).
 *   - POST   /plans/subscriptions        — alta de suscripción (admin).
 *   - DELETE /plans/subscriptions/{id}   — baja de suscripción (admin).
 *   - GET    /plans/me                   — mi plan (cliente; siempre el suyo).
 *
 * Decisión D2 (2026-10-21): el cobro es **contable**. Se registra la
 * suscripción y su precio, pero no se cobra nada porque todavía no hay
 * pasarela de pago. Los campos `billing_mode` / `billing_note` lo explican
 * para que la interfaz se lo diga al cliente en vez de dar a entender que
 * ya se ha pagado.
 */
import { http } from './client'

export interface Plan {
  id: number
  code: string
  name: string
  monthly_price: number
  discount_percent: number
  included_vehicles: number
  is_active: boolean
  created_at: string
  updated_at: string
}

/** Datos del plan que necesita la vista "Mi plan" (sin metadatos). */
export interface PlanResumen {
  id: number
  code: string
  name: string
  monthly_price: number
  discount_percent: number
  included_vehicles: number
}

export interface Subscription {
  id: number
  user_id: number
  plan_id: number
  starts_at: string
  ends_at: string
  is_active: boolean
  plan: PlanResumen
  user_email: string
  user_full_name: string
  created_at: string
  updated_at: string
}

/** Estado de la suscripción tal y como lo ve el cliente. */
export type MiPlanEstado = 'vigente' | 'caducada' | 'cancelada' | 'sin_plan'

export interface MiPlan {
  status: MiPlanEstado
  plan: PlanResumen | null
  subscription_id: number | null
  starts_at: string | null
  ends_at: string | null
  subscription_active: boolean
  /** ¿Se aplica descuento ahora mismo? */
  applies_discount: boolean
  days_remaining: number | null
  /** Próximo cobro contable (renovación) y su importe. */
  next_billing_at: string | null
  next_billing_amount: number | null
  billing_mode: string
  billing_note: string
}

export interface PlanPayload {
  code: string
  name: string
  monthly_price: number
  discount_percent: number
  included_vehicles: number
  is_active?: boolean
}

export interface SubscriptionPayload {
  user_id: number
  plan_id: number
  starts_at: string
  ends_at: string
}

export interface SubscriptionFilters {
  user_id?: number
  plan_id?: number
  only_active?: boolean
}

/**
 * Catálogo de planes.
 *
 * El admin ve todos (incluidos los desactivados) salvo que pida
 * `only_active`; el cliente ve sólo los activos.
 */
export async function listPlans(onlyActive?: boolean): Promise<Plan[]> {
  const { data } = await http.get<Plan[]>('/plans', {
    params: onlyActive === undefined ? {} : { only_active: onlyActive },
  })
  return data
}

export async function createPlan(payload: PlanPayload): Promise<Plan> {
  const { data } = await http.post<Plan>('/plans', payload)
  return data
}

export async function updatePlan(
  id: number,
  payload: Partial<PlanPayload>,
): Promise<Plan> {
  const { data } = await http.patch<Plan>(`/plans/${id}`, payload)
  return data
}

export async function deletePlan(id: number): Promise<void> {
  await http.delete(`/plans/${id}`)
}

export async function listSubscriptions(
  filters: SubscriptionFilters = {},
): Promise<Subscription[]> {
  const { data } = await http.get<Subscription[]>('/plans/subscriptions', {
    params: filters,
  })
  return data
}

export async function createSubscription(
  payload: SubscriptionPayload,
): Promise<Subscription> {
  const { data } = await http.post<Subscription>('/plans/subscriptions', payload)
  return data
}

/** Baja de la suscripción (baja lógica: deja de aplicar descuento). */
export async function cancelSubscription(id: number): Promise<void> {
  await http.delete(`/plans/subscriptions/${id}`)
}

/** Mi plan: siempre el del usuario autenticado. */
export async function getMyPlan(): Promise<MiPlan> {
  const { data } = await http.get<MiPlan>('/plans/me')
  return data
}
