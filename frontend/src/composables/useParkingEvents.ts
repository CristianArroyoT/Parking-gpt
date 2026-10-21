/**
 * Composable SSE: suscripción reactiva al stream de eventos del parking.
 *
 * Sprint O2 (2026-07-06): se consume el endpoint
 * ``GET /api/v1/parkings/{id}/events`` y se reacciona a los eventos
 * publicados en Redis pub/sub por ``event_bus.publish``.
 *
 * T-17 (2026-10-21): el composable se generaliza para que **varias vistas**
 * puedan suscribirse (mapa del gestor, vista en vivo del operador y vista de
 * calibración).
 *
 * ── Por qué ``fetch`` + ``ReadableStream`` y no ``EventSource`` ──────────
 *
 * El endpoint de eventos declara dos dependencias de autenticación:
 *
 *     _user = Depends(get_current_user_or_query_token)   # acepta ?token=
 *     _ctx  = Depends(parking_context)                   # SÓLO header
 *
 * ``parking_context`` depende de ``get_current_user`` (header-only), así que
 * una petición que sólo lleve ``?token=...`` recibe un **401**. Y
 * ``EventSource`` no puede mandar la cabecera ``Authorization``. Es decir:
 * con ``EventSource`` el stream nunca abre y la vista se queda siempre en el
 * polling de respaldo. Por eso el composable usa ``fetch`` +
 * ``ReadableStream``, que sí puede mandar ``Authorization: Bearer`` (y de
 * paso no mete el JWT en la URL, donde queda en los logs de los proxies).
 *
 * Verificado contra el backend en marcha (2026-10-21):
 *
 *     GET /api/v1/parkings/11/events?token=<jwt>       -> 401
 *     GET /api/v1/parkings/11/events  (Bearer <jwt>)    -> 200 + "event: ping"
 *
 * ── Comportamiento ─────────────────────────────────────────────────────
 *
 * - ``parkingId`` acepta un ``number`` o un ``ref``/``computed``/getter.
 *   Cuando el identificador cambia se aborta el stream anterior y se abre
 *   uno nuevo (sin dejar conexiones huérfanas).
 * - ``connected`` es un ``ref`` realmente reactivo: el indicador "En vivo"
 *   se enciende con el ``ping`` inicial que manda el backend.
 * - **Reintento con backoff exponencial**: ``fetch`` NO reconecta solo
 *   (a diferencia de ``EventSource``), así que si el stream se corta
 *   (backend reiniciado, proxy que devuelve 502, token caducado) hay que
 *   reconectar a mano: 1s → 2s → 4s → 8s → 16s → 30s (tope).
 * - Si el servidor responde 401 (el access token tiene TTL 15 min) se
 *   "sondea" la API con ``http`` para que el interceptor de axios refresque
 *   el token antes de reintentar.
 * - Cierre explícito en ``onBeforeUnmount`` (cambio de vista) con
 *   ``AbortController``: se aborta la petición en vuelo y se cancela el
 *   temporizador de reintento, de modo que no quedan conexiones abiertas
 *   ni timers vivos tras navegar.
 *
 * @param parkingId  ID de la sucursal a la que suscribirse. Puede ser un
 *                   número fijo o una fuente reactiva.
 * @param onEvent    Callback por cada evento recibido. El composable
 *                   no decodifica el ``type``: el consumidor decide.
 * @param options    ``reconnect`` (por defecto ``true``) permite desactivar
 *                   el reintento manual; ``probeBeforeReconnect`` (por
 *                   defecto ``true``) permite desactivar el sondeo previo.
 */
import {
  getCurrentInstance,
  onBeforeUnmount,
  ref,
  toValue,
  watch,
  type MaybeRefOrGetter,
} from 'vue'
import { getAccessToken, http } from '@/api/client'

export interface ParkingEvent {
  type: string
  payload: Record<string, unknown>
  ts: string
}

/**
 * Tipos de evento que publica el backend.
 * Espejo de ``backend/app/services/event_bus.py::EventType``.
 */
export const ParkingEventType = {
  TICKET_CREATED: 'ticket_created',
  TICKET_CLOSED: 'ticket_closed',
  TICKET_CANCELLED: 'ticket_cancelled',
  SPACE_BROKEN_CHANGED: 'space_broken_changed',
  CAMERA_HEALTH_CHANGED: 'camera_health_changed',
} as const

export type ParkingEventTypeName =
  (typeof ParkingEventType)[keyof typeof ParkingEventType]

/** Delay base del backoff de reconexión (ms). */
export const RECONNECT_BASE_MS = 1_000
/** Tope del backoff de reconexión (ms). */
export const RECONNECT_MAX_MS = 30_000

/**
 * Función pura: delay del siguiente reintento según el intento (0-based).
 * 1s → 2s → 4s → 8s → 16s → 30s (tope).
 *
 * @param attempt  Número de intentos fallidos ya realizados.
 */
export function nextReconnectDelay(attempt: number): number {
  if (!Number.isFinite(attempt) || attempt <= 0) return RECONNECT_BASE_MS
  const delay = RECONNECT_BASE_MS * 2 ** attempt
  return Math.min(delay, RECONNECT_MAX_MS)
}

/** Error interno: el servidor respondió con un status HTTP no-2xx. */
class SseHttpError extends Error {
  readonly status: number
  constructor(status: number) {
    super(`El stream SSE respondió con HTTP ${status}`)
    this.status = status
  }
}

export interface ParkingEventsOptions {
  /** Reintento manual cuando el stream se corta. */
  reconnect?: boolean
  /** Sondear la API antes de reconectar (refresca el access token). */
  probeBeforeReconnect?: boolean
}

/**
 * Parsea un frame SSE (bloque separado por líneas en blanco) y devuelve el
 * evento o ``null`` si el frame no trae datos (p. ej. el comentario
 * ``:keepalive`` que manda el backend cada 30 s).
 *
 * Función pura y exportada para poder testearla sin navegador.
 */
export function parseSseFrame(
  frame: string,
): { event: string; data: string } | null {
  const dataLines: string[] = []
  let eventName = 'message'
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'data') dataLines.push(value)
    else if (field === 'event') eventName = value
  }
  if (!dataLines.length) return null
  return { event: eventName, data: dataLines.join('\n') }
}

export function useParkingEvents(
  parkingId: MaybeRefOrGetter<number | null | undefined>,
  onEvent: (event: ParkingEvent) => void,
  options: ParkingEventsOptions = {},
) {
  const connected = ref(false)
  const reconnecting = ref(false)
  const lastError = ref<string | null>(null)

  let controller: AbortController | null = null
  let retryTimer: number | null = null
  let attempt = 0
  let stopped = false
  /** Generación del stream en vuelo: ignora los frames de streams viejos. */
  let generation = 0

  function clearRetryTimer(): void {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  /** Aborta el stream en vuelo (si lo hay) sin tocar el estado de reintentos. */
  function closeStream(): void {
    if (controller) {
      controller.abort()
      controller = null
    }
    connected.value = false
  }

  function handleFrame(frame: string): void {
    const parsed = parseSseFrame(frame)
    if (!parsed) return
    if (parsed.event === 'ping') {
      // Confirmación de conexión del backend.
      connected.value = true
      reconnecting.value = false
      lastError.value = null
      attempt = 0
      return
    }
    let event: ParkingEvent
    try {
      event = JSON.parse(parsed.data) as ParkingEvent
    } catch {
      // Payload corrupto: se ignora, el siguiente evento traerá datos válidos.
      return
    }
    if (!event || typeof event.type !== 'string') return
    onEvent(event)
  }

  /** Lee el cuerpo del stream y va cortando frames SSE completos. */
  async function readStream(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    myGeneration: number,
  ): Promise<void> {
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      if (myGeneration !== generation) return
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        handleFrame(buffer.slice(0, sep))
        buffer = buffer.slice(sep + 2)
        sep = buffer.indexOf('\n\n')
      }
    }
  }

  /**
   * Sondea la API para que el interceptor de axios refresque el access
   * token caducado. Si el sondeo falla se ignora: ``connect()`` decide si
   * puede abrir el stream.
   */
  async function probeToken(): Promise<void> {
    try {
      await http.get('/parkings')
    } catch {
      // Sin efecto: si no queda token tras el sondeo, ``connect`` no abre nada.
    }
  }

  async function connect(): Promise<void> {
    const id = toValue(parkingId)
    if (id === null || id === undefined) return
    const token = getAccessToken()
    if (!token) {
      // Sin token no abrimos stream: la vista mantiene su fallback de
      // polling y el interceptor de axios ya habrá refrescado el token en
      // la próxima petición normal.
      connected.value = false
      return
    }

    clearRetryTimer()
    closeStream()
    reconnecting.value = false

    const myGeneration = ++generation
    const ctrl = new AbortController()
    controller = ctrl

    try {
      const res = await fetch(`/api/v1/parkings/${id}/events`, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'text/event-stream',
        },
        signal: ctrl.signal,
      })
      if (!res.ok) {
        throw new SseHttpError(res.status)
      }
      const reader = res.body?.getReader()
      if (!reader) {
        throw new Error('El navegador no expone el cuerpo del stream')
      }
      connected.value = true
      lastError.value = null
      attempt = 0
      await readStream(reader, myGeneration)
      // El servidor cerró el stream: reconectamos (fetch no lo hace solo).
      if (!stopped && myGeneration === generation) {
        lastError.value = 'El servidor cerró el stream de eventos'
        scheduleReconnect()
      }
    } catch (err: unknown) {
      if (ctrl.signal.aborted) return // cierre intencionado
      connected.value = false
      if (err instanceof SseHttpError) {
        lastError.value = err.message
        if (err.status === 401) {
          // Token caducado: el sondeo deja que axios lo refresque.
          await probeToken()
        }
      } else {
        lastError.value = err instanceof Error ? err.message : 'Error desconocido'
      }
      if (!stopped) scheduleReconnect()
    }
  }

  function scheduleReconnect(): void {
    if (stopped || options.reconnect === false) return
    if (retryTimer !== null) return
    reconnecting.value = true
    const delay = nextReconnectDelay(attempt)
    attempt += 1
    retryTimer = window.setTimeout(() => {
      retryTimer = null
      void connect()
    }, delay)
  }

  /** Cierra la suscripción y cancela cualquier reintento pendiente. */
  function disconnect(): void {
    stopped = true
    clearRetryTimer()
    generation += 1
    closeStream()
    reconnecting.value = false
    attempt = 0
  }

  // Re-suscribe cuando cambia la sucursal (cambio de parking en el
  // selector del operador o del gestor).
  watch(
    () => toValue(parkingId),
    (newId, oldId) => {
      if (newId === oldId) return
      stopped = false
      attempt = 0
      clearRetryTimer()
      generation += 1
      closeStream()
      void connect()
    },
  )

  void connect()

  // Si el composable se usa dentro de un componente, cerramos la conexión
  // al desmontarlo (cambio de vista). Si se usa fuera (p. ej. dentro de un
  // ``watch``), ``getCurrentInstance()`` devuelve ``null`` y el consumidor
  // es el responsable de llamar a ``disconnect()``.
  if (getCurrentInstance()) {
    onBeforeUnmount(disconnect)
  }

  return { connected, reconnecting, lastError, disconnect }
}
