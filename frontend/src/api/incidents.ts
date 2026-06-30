/**
 * Wrapper tipado para el endpoint de incidentes del operador.
 *
 * Endpoint backend: ``POST /api/v1/parkings/{parking_id}/incidents``
 *   - Permisos: admin, gestor u operador con membresía en la sucursal.
 *   - Cliente → 403.
 *   - kind=space_broken / space_unbroken requieren parking_space_id.
 *   - kind=robery_reported: todos los campos opcionales.
 *
 * Devuelve 201 con Alert si crea una alerta nueva, o 200 con
 * ``{noop: true, detail: ...}`` si la operación era idempotente.
 */
import { http } from './client'
import type { IncidentCreatePayload } from './client'

export interface IncidentResult {
  alert?: {
    id: number
    parking_id: number
    type: string
    severity: string
    message: string
    context?: Record<string, unknown> | null
  }
  noop?: boolean
  detail?: string
}

export async function createIncident(
  parkingId: number,
  payload: IncidentCreatePayload,
): Promise<IncidentResult> {
  const { data } = await http.post(
    `/incidents/parkings/${parkingId}`,
    payload,
  )
  return data as IncidentResult
}