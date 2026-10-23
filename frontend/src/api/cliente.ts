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
 * devuelve 403) ni sucursales. Y `GET /tickets`, aunque ya acota por
 * vehículo (T-19/T-24), no trae la etiqueta de la plaza, el nombre de
 * la sucursal ni el flag de "pendiente de pago". `/cliente/*` acota
 * siempre por `vehicle_users` y devuelve los datos ya enriquecidos.
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
  /** T-97: el PDF se pide a la API; la ruta interna del servidor ya no sale. */
  pdf_available: boolean
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

/**
 * Descarga el PDF de un ticket (T-97).
 *
 * Va con `fetch` (y no con un `<a href>`) por dos motivos:
 *  1. el PDF **no** se puede enlazar en el HTML: necesita la cabecera
 *     `Authorization`, y un `<a>` no la manda;
 *  2. antes el enlace apuntaba a `pdf_path`, que era la ruta del PDF en
 *     el **disco del servidor** (`/tmp/solidapp-tickets/ticket-1.pdf`):
 *     un 404 de manual y, de paso, la estructura de ficheros del
 *     servidor en la respuesta de la API.
 */
export async function descargarPdfTicket(ticketId: number): Promise<void> {
  const r = await http.get(`/tickets/${ticketId}/pdf`, { responseType: 'blob' })
  const url = URL.createObjectURL(r.data as Blob)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = `ticket-${ticketId}.pdf`
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  URL.revokeObjectURL(url)
}
