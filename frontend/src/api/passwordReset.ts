/**
 * Cliente HTTP del flujo de recuperación de contraseña (T-22).
 *
 * Endpoints (backend `app/api/v1/password_reset.py`):
 *   - `POST /api/v1/auth/forgot-password` → pide el enlace por correo.
 *     La respuesta es SIEMPRE la misma exista o no la cuenta (responder
 *     distinto revelaría qué emails están registrados → enumeración de
 *     cuentas), así que aquí no se decide nada con el `detail`.
 *   - `POST /api/v1/auth/reset-password` → cambia la contraseña con el
 *     token de un solo uso que llega en el enlace del correo.
 *
 * Ninguno de los dos exige sesión: son las dos únicas llamadas públicas
 * de la API aparte del login.
 */
import { http } from './client'

/** Respuesta uniforme de ambos endpoints: `{"detail": "..."}`. */
export interface MessageResponse {
  detail: string
}

/** Pide un enlace de restablecimiento. No revela si el email existe. */
export async function requestPasswordReset(email: string): Promise<MessageResponse> {
  const r = await http.post<MessageResponse>('/auth/forgot-password', { email })
  return r.data
}

/** Cambia la contraseña con el token recibido por correo. */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<MessageResponse> {
  const r = await http.post<MessageResponse>('/auth/reset-password', {
    token,
    new_password: newPassword,
  })
  return r.data
}
