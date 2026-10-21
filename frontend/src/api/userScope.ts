/**
 * API del ámbito del usuario (T-19): perfil, vehículos vinculados y
 * tickets de los vehículos que el usuario conduce.
 *
 * Endpoints backend (`backend/app/api/v1/users.py`):
 *   - `GET    /api/v1/users/me`                         → perfil (UserRead).
 *   - `PATCH  /api/v1/users/me/profile`                 → nombre y teléfono.
 *   - `GET    /api/v1/users/me/vehicles`                → vehículos + rol + vínculos.
 *   - `POST   /api/v1/users/me/vehicles`                → alta (queda como propietario).
 *   - `PATCH  /api/v1/users/me/vehicles/{id}`           → edición (sólo propietario).
 *   - `POST   /api/v1/users/me/vehicles/{id}/links`     → vincula a otra persona.
 *   - `DELETE /api/v1/users/me/vehicles/{id}/links/{uid}`→ desvincula.
 *   - `GET    /api/v1/users/me/tickets`                 → tickets de SUS vehículos.
 *
 * Por qué no se usan `/vehicles` ni `/tickets`:
 *   - `GET /api/v1/vehicles` es *staff-only* (admin/gestor/operador): un
 *     cliente recibe 403 y no puede ni ver sus propios coches.
 *   - `GET /api/v1/tickets` acota por **membresía de sucursal**, no por
 *     vehículo: un cliente con membresía vería los tickets de vehículos
 *     ajenos de esa sucursal.
 *
 * Estos endpoints acotan siempre por `vehicle_users` (propietario o
 * conductor), que es el scope correcto para el cliente final.
 */
import { http } from './client'
import type { User } from './client'

/** Rol que tiene el usuario sobre un vehículo. */
export type VehicleRole = 'propietario' | 'conductor'

/** Persona vinculada a un vehículo. */
export interface VehicleLink {
  user_id: number
  email: string
  full_name: string
  role: VehicleRole
}

/** Vehículo visto desde la perspectiva del usuario autenticado. */
export interface MyVehicle {
  id: number
  plate: string
  brand: string | null
  model: string | null
  color: string | null
  vehicle_type: string | null
  created_at: string
  updated_at: string
  /** Rol del usuario autenticado sobre este vehículo. */
  my_role: VehicleRole
  /** Todas las personas vinculadas al vehículo. */
  links: VehicleLink[]
}

/** Alta de vehículo. */
export interface MyVehicleCreate {
  plate: string
  brand?: string | null
  model?: string | null
  color?: string | null
  vehicle_type?: string | null
}

/** Edición de vehículo (la matrícula no se edita). */
export interface MyVehicleUpdate {
  brand?: string | null
  model?: string | null
  color?: string | null
  vehicle_type?: string | null
}

/** Ticket visto desde el ámbito del usuario. */
export interface UserScopedTicket {
  id: number
  parking_id: number
  vehicle_id: number
  parking_space_id: number | null
  status: string
  entry_at: string
  exit_at: string | null
  amount: number | null
  discount: number | null
  total: number | null
  payment_method: string | null
  pdf_path: string | null
  origin: string
}

export async function getMyProfile(): Promise<User> {
  const { data } = await http.get<User>('/users/me')
  return data
}

/** Actualiza nombre y/o teléfono del usuario autenticado. */
export async function updateMyProfile(payload: {
  full_name?: string
  phone?: string | null
}): Promise<User> {
  const { data } = await http.patch<User>('/users/me/profile', payload)
  return data
}

export async function listMyVehicles(): Promise<MyVehicle[]> {
  const { data } = await http.get<MyVehicle[]>('/users/me/vehicles')
  return data
}

export async function createMyVehicle(payload: MyVehicleCreate): Promise<MyVehicle> {
  const { data } = await http.post<MyVehicle>('/users/me/vehicles', payload)
  return data
}

export async function updateMyVehicle(
  id: number,
  payload: MyVehicleUpdate,
): Promise<MyVehicle> {
  const { data } = await http.patch<MyVehicle>(`/users/me/vehicles/${id}`, payload)
  return data
}

/** Vincula a otra persona con el vehículo (se identifica por email). */
export async function linkVehicleUser(
  vehicleId: number,
  payload: { email: string; role: VehicleRole },
): Promise<VehicleLink> {
  const { data } = await http.post<VehicleLink>(
    `/users/me/vehicles/${vehicleId}/links`,
    payload,
  )
  return data
}

/** Desvincula a una persona (o al propio usuario) del vehículo. */
export async function unlinkVehicleUser(
  vehicleId: number,
  userId: number,
): Promise<void> {
  await http.delete(`/users/me/vehicles/${vehicleId}/links/${userId}`)
}

/** Tickets de los vehículos del usuario (propietario o conductor). */
export async function listMyTickets(): Promise<UserScopedTicket[]> {
  const { data } = await http.get<UserScopedTicket[]>('/users/me/tickets')
  return data
}

/**
 * Filtra tickets por los vehículos permitidos para el usuario.
 *
 * **Defensa en profundidad**: el backend ya acota `/users/me/tickets` por
 * `vehicle_users`, pero `GET /api/v1/tickets` (el endpoint que usa la
 * vista "Mis tickets") acota por *membresía de sucursal*, así que un
 * cliente con membresía vería tickets de vehículos ajenos. Aplicar este
 * filtro en el cliente evita que se muestren tickets que no son suyos
 * aunque el backend ampliase el rango.
 *
 * Función pura (sin efectos): se puede testear sin montar la app.
 */
export function filterTicketsByVehicleScope<T extends { vehicle_id: number }>(
  tickets: T[],
  allowedVehicleIds: Iterable<number>,
): T[] {
  const allowed = new Set(allowedVehicleIds)
  return tickets.filter((t) => allowed.has(t.vehicle_id))
}
