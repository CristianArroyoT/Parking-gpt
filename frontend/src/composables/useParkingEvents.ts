/**
 * Composable SSE: suscripción reactiva al stream de eventos del parking.
 *
 * Sprint O2 (2026-07-06): MapView consume el endpoint
 * ``GET /api/v1/parkings/{id}/events?token=<jwt>`` y reacciona a los
 * eventos publicados en Redis pub/sub por ``event_bus.publish``.
 *
 * Notas:
 *
 * - Usa el ``EventSource`` nativo del navegador (auto-reconnect con
 *   backoff). NO hace polling manual.
 * - El token se pasa por query string porque ``EventSource`` no permite
 *   setear headers arbitrarios. Riesgo mitigado por access TTL 15 min.
 * - Cleanup en ``onBeforeUnmount`` para cerrar la conexión al
 *   desmontar el componente (cambio de vista, hot reload).
 *
 * @param parkingId  ID de la sucursal a la que suscribirse.
 * @param onEvent    Callback por cada evento recibido. El composable
 *                   no decodifica el ``type``: el consumidor decide.
 */
import { onBeforeUnmount, ref } from 'vue'
import { getAccessToken } from '@/api/client'

export interface ParkingEvent {
  type: string
  payload: Record<string, unknown>
  ts: string
}

export function useParkingEvents(
  parkingId: number,
  onEvent: (event: ParkingEvent) => void,
) {
  const connected = ref(false)
  let es: EventSource | null = null

  function connect(): void {
    const token = getAccessToken()
    if (!token) {
      // Sin token, no abrimos stream. MapView sigue con su fallback
      // setInterval(30s) para mantener la vista sincronizada.
      return
    }
    es = new EventSource(
      `/api/v1/parkings/${parkingId}/events?token=${encodeURIComponent(token)}`,
    )
    es.addEventListener('ping', () => {
      connected.value = true
    })
    es.addEventListener('error', () => {
      connected.value = false
      // NO reconectamos manualmente: EventSource ya reintenta solo.
    })
    es.onmessage = (e: MessageEvent<string>) => {
      try {
        const data = JSON.parse(e.data) as ParkingEvent
        onEvent(data)
      } catch {
        // Payload corrupto o comentario keepalive mal formadoado.
        // No hacemos nada: el siguiente evento traerá datos válidos.
      }
    }
  }

  function disconnect(): void {
    if (es) {
      es.close()
      es = null
    }
    connected.value = false
  }

  connect()
  onBeforeUnmount(disconnect)

  return { connected, disconnect }
}