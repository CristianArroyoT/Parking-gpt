/**
 * API de los módulos del gestor (T-20): log de entradas/salidas, alertas
 * activas y operadores de la sucursal.
 *
 * Endpoints backend:
 *   - `GET  /api/v1/parkings`                        → sucursales del usuario.
 *   - `GET  /api/v1/tickets?parking_id=`             → movimientos (tickets).
 *   - `GET  /api/v1/parkings/{id}/spaces`            → plazas de la sucursal.
 *   - `GET  /api/v1/vehicles`                        → vehículos (staff).
 *   - `GET  /api/v1/parkings/{id}/alerts`            → alertas de la sucursal.
 *   - `POST /api/v1/parkings/{id}/alerts/{aid}/acknowledge` → revisar alerta.
 *   - `GET  /api/v1/users`                           → usuarios (**admin**).
 *   - `POST /api/v1/users`                           → alta de usuario (**admin**).
 *   - `POST /api/v1/users/{id}/memberships`          → asignar a sucursal (**admin**).
 *
 * Límites del backend que la UI debe respetar (documentados en las vistas):
 *   - `GET /tickets` sólo filtra por `parking_id` y `only_active`; el resto
 *     de filtros (fecha, plaza, vehículo, origen) se aplican en el
 *     navegador sobre los registros devueltos (tope de 200 en el backend).
 *   - El listado y el alta de operadores son **admin-only**: un gestor
 *     recibe 403 y la vista lo explica en lugar de fallar en silencio.
 */
import { http } from './client'

/** Sucursal. */
export interface Parking {
  id: number
  code: string
  name: string
  address: string
  city: string
  is_active: boolean
}

/** Movimiento (ticket) del log de entradas/salidas. */
export interface MovementTicket {
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
  origin: string
}

/** Origen del movimiento. */
export type MovementOrigin = 'automatic' | 'manual_entry' | 'manual_exit'

/** Vehículo (sólo staff). */
export interface VehiclePlate {
  id: number
  plate: string
  brand: string | null
  model: string | null
  color: string | null
  vehicle_type: string | null
}

/** Plaza de una sucursal. */
export interface ParkingSpace {
  id: number
  parking_id: number
  lane: string
  number: string
  is_active: boolean
  is_broken: boolean
}

/** Alerta operativa de una sucursal. */
export interface Alert {
  id: number
  parking_id: number
  type: string
  severity: string
  message: string
  context: Record<string, unknown> | null
  acknowledged_at: string | null
  acknowledged_by: number | null
  created_at: string
}

/** Usuario del sistema (admin-only en la API). */
export interface StaffUser {
  id: number
  email: string
  full_name: string
  phone: string | null
  role: 'admin' | 'gestor' | 'operador' | 'cliente'
  is_active: boolean
}

/** Membresía de un usuario en una sucursal. */
export interface Membership {
  id: number
  user_id: number
  parking_id: number
  role_in_parking: string
}

export async function listParkings(): Promise<Parking[]> {
  const { data } = await http.get<Parking[]>('/parkings')
  return data
}

export async function listMovements(parkingId: number): Promise<MovementTicket[]> {
  const { data } = await http.get<MovementTicket[]>('/tickets', {
    params: { parking_id: parkingId },
  })
  return data
}

export async function listSpaces(parkingId: number): Promise<ParkingSpace[]> {
  const { data } = await http.get<ParkingSpace[]>(`/parkings/${parkingId}/spaces`)
  return data
}

export async function listVehicles(plate?: string): Promise<VehiclePlate[]> {
  const { data } = await http.get<VehiclePlate[]>('/vehicles', {
    params: plate ? { plate } : {},
  })
  return data
}

export async function listAlerts(
  parkingId: number,
  params: { acknowledged?: boolean; severity?: string; type?: string } = {},
): Promise<Alert[]> {
  const { data } = await http.get<Alert[]>(`/parkings/${parkingId}/alerts`, { params })
  return data
}

/**
 * Marca una alerta como revisada por el usuario actual.
 *
 * El backend **no** tiene "resolver" ni "ignorar": la única acción sobre
 * una alerta es el *acknowledge* (`acknowledged_at` + `acknowledged_by`),
 * que es idempotente. Por eso la UI la llama "marcar como revisada" y la
 * saca de la lista de activas.
 */
export async function acknowledgeAlert(
  parkingId: number,
  alertId: number,
): Promise<Alert> {
  const { data } = await http.post<Alert>(
    `/parkings/${parkingId}/alerts/${alertId}/acknowledge`,
  )
  return data
}

/** Usuarios del sistema. ** Sólo admin** (el gestor recibe 403). */
export async function listStaffUsers(): Promise<StaffUser[]> {
  const { data } = await http.get<StaffUser[]>('/users')
  return data
}

/** Alta de usuario. **Sólo admin** (el gestor recibe 403). */
export async function createStaffUser(payload: {
  email: string
  full_name: string
  password: string
  phone?: string | null
  role: StaffUser['role']
}): Promise<StaffUser> {
  const { data } = await http.post<StaffUser>('/users', payload)
  return data
}

/** Asigna un usuario a una sucursal. **Sólo admin** (el gestor recibe 403). */
export async function assignUserToParking(
  userId: number,
  parkingId: number,
  roleInParking: string,
): Promise<Membership> {
  const { data } = await http.post<Membership>(
    `/users/${userId}/memberships`,
    { parking_id: parkingId, role_in_parking: roleInParking },
  )
  return data
}

// ── Operadores de la sucursal (T-20) ──────────────────────────────────────
//
// API **acotada por sucursal** (`backend/app/api/v1/gestor_operadores.py`):
// el gestor sólo puede ver y dar de alta operadores de las sucursales de las
// que es miembro, y el rol creado es siempre `operador`. Los endpoints
// globales de admin (`/users`) **no** se abren: siguen siendo admin-only.
//
// Por eso aquí no se usa `listStaffUsers()`: ésa devuelve 403 al gestor.

/** Operadores asignados a una sucursal. */
export async function listParkingOperators(parkingId: number): Promise<StaffUser[]> {
  const { data } = await http.get<StaffUser[]>(`/parkings/${parkingId}/operadores`)
  return data
}

/**
 * Crea un operador **y** lo deja asignado a la sucursal indicada.
 *
 * El payload no lleva `role`: el backend lo fuerza a `operador`, así que un
 * gestor no puede crear un admin por aquí.
 */
export async function createParkingOperator(
  parkingId: number,
  payload: {
    email: string
    full_name: string
    password: string
    phone?: string | null
  },
): Promise<StaffUser> {
  const { data } = await http.post<StaffUser>(
    `/parkings/${parkingId}/operadores`,
    payload,
  )
  return data
}

// ── Filtros puros del log de movimientos ────────────────────────────────

/** Filtros del log de entradas/salidas (todos opcionales). */
export interface MovementFilters {
  /** Fecha inicial inclusiva (``YYYY-MM-DD``) sobre la entrada. */
  desde: string
  /** Fecha final inclusiva (``YYYY-MM-DD``) sobre la entrada. */
  hasta: string
  /** Id de plaza (vacío = todas). */
  plazaId: number | null
  /** Id de vehículo (vacío = todos). */
  vehicleId: number | null
  /** Origen del movimiento (vacío = todos). */
  origin: '' | MovementOrigin
}

/** Mapas de apoyo para etiquetar los movimientos filtrados. */
export interface MovementLabels {
  /** vehicle_id → matrícula. */
  plateByVehicleId: Record<number, string>
  /** parking_space_id → etiqueta de plaza (``A-01``). */
  spaceLabelById: Record<number, string>
}

/**
 * Aplica los filtros del log de movimientos.
 *
 * El backend (``GET /tickets``) sólo acepta ``parking_id`` y
 * ``only_active``: la fecha, la plaza, el vehículo y el origen se filtran
 * aquí, en el navegador, sobre los registros ya descargados.
 *
 * Las fechas comparan contra el **día UTC** de la entrada (los
 * ``entry_at`` llegan en UTC ISO-8601), para que el filtro sea
 * reproducible y no dependa de la zona horaria del navegador.
 *
 * Función pura (sin efectos): se puede testear sin montar la app.
 */
export function filterMovements(
  movements: MovementTicket[],
  filters: MovementFilters,
): MovementTicket[] {
  return movements.filter((m) => {
    const dia = m.entry_at.slice(0, 10)
    if (filters.desde && dia < filters.desde) return false
    if (filters.hasta && dia > filters.hasta) return false
    if (filters.plazaId !== null && m.parking_space_id !== filters.plazaId) return false
    if (filters.vehicleId !== null && m.vehicle_id !== filters.vehicleId) return false
    if (filters.origin && m.origin !== filters.origin) return false
    return true
  })
}

/** Etiqueta legible de un movimiento: matrícula + plaza. */
export function movementLabel(
  m: MovementTicket,
  labels: MovementLabels,
): string {
  const plate = labels.plateByVehicleId[m.vehicle_id] ?? `Vehículo ${m.vehicle_id}`
  const space =
    m.parking_space_id !== null
      ? labels.spaceLabelById[m.parking_space_id] ?? `Plaza ${m.parking_space_id}`
      : '—'
  return `${plate} · ${space}`
}
