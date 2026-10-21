/**
 * Cliente HTTP del panel del cliente final (T-24 · PWA instalable).
 *
 * Endpoints propios del panel (backend `app/api/v1/cliente.py`):
 *   - `GET /api/v1/cliente/plazas`  → plazas ocupadas **ahora mismo** por
 *                                     sus vehículos (ticket activo), con la
 *                                     etiqueta de plaza, el nombre de la
 *                                     sucursal y el aviso de avería.
 *   - `GET /api/v1/cliente/tickets` → tickets de **sus** vehículos con la
 *                                     matrícula, el nombre de la sucursal,
 *                                     la etiqueta de plaza y el flag de
 *                                     "pendiente de pago"
 *                                     (`?solo_pendientes=true` los filtra).
 *
 * Lo que **no** vive aquí (para no duplicar APIs):
 *   - Los vehículos: `GET /users/me/vehicles` (T-19) → `@/api/userScope`.
 *   - El plan y la suscripción: `GET /plans/me` (T-18) → `@/api/plans`.
 *
 * Por qué hace falta `/cliente/*`: el cliente no tiene membresía de
 * sucursal, así que no puede listar espacios (`GET /parkings/{id}/spaces`
 * devuelve 403) ni sucursales. Y `GET /tickets` acota por membresía, no
 * por vehículo: un cliente con membresía vería tickets de vehículos
 * ajenos. `/cliente/*` acota siempre por `vehicle_users` y devuelve los
 * datos ya enriquecidos (plaza, sucursal, pendiente de pago).
 */
import { http } from './client'

/** Plaza ocupada ahora mismo por uno de sus vehículos. */
export interface ClientePlaza {
  ticket_id: number
  vehicle_id: number
  plate: string
  parking_id: number
  parking_name: string
  parking_space_id: number | null
  lane: string | null
  number: string | null
  space_label: string | null
  entry_at: string
  is_broken: boolean
}

/** Ticket del cliente (con el flag de pago pendiente). */
export interface ClienteTicket {
  id: number
  vehicle_id: number
  plate: string
  parking_id: number
  parking_name: string
  parking_space_id: number | null
  space_label: string | null
  status: string
  entry_at: string
  exit_at: string | null
  amount: number | null
  discount: number | null
  total: number | null
  payment_method: string | null
  pdf_path: string | null
  pending_payment: boolean
  days_pending: number | null
}

export async function listarPlazas(): Promise<ClientePlaza[]> {
  const { data } = await http.get<ClientePlaza[]>('/cliente/plazas')
  return data
}

export async function listarTickets(
  soloPendientes = false,
): Promise<ClienteTicket[]> {
  const { data } = await http.get<ClienteTicket[]>('/cliente/tickets', {
    params: soloPendientes ? { solo_pendientes: true } : {},
  })
  return data
}
