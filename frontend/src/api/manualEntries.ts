/**
 * Wrapper tipado para el alta manual de tickets del operador.
 *
 * Endpoint backend: ``POST /api/v1/tickets/manual``
 *   - Permisos: admin, gestor u operador con membresía en la sucursal.
 *   - Cliente → 403.
 *   - Plaza ocupada / vehículo ya dentro / sin ticket activo para SALIDA → 409.
 *
 * El backend normaliza la matrícula (mayúsculas + sin separadores) y
 * resuelve el vehículo por lookup o auto-create.
 */
import { http } from './client'
import type { ManualEntryPayload } from './client'

export async function createManualTicket(
  payload: ManualEntryPayload,
): Promise<unknown> {
  const { data } = await http.post('/tickets/manual', payload)
  return data
}