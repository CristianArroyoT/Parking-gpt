/**
 * Estado de autenticación compartido por toda la app.
 * - `user` es el perfil actual (UserRead del backend).
 * - El email se persiste en sessionStorage para sobrevivir recargas;
 *   los tokens viven en `api/client.ts` por seguridad.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  http, setTokens, clearTokens, getRefreshToken,
  type User, type LoginResponse,
} from '@/api/client'

const EMAIL_KEY = 'solidapp.email'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const email = ref<string | null>(sessionStorage.getItem(EMAIL_KEY))
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const role = computed(() => user.value?.role ?? null)

  async function login(emailInput: string, password: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const { data } = await http.post<LoginResponse>('/auth/login', {
        email: emailInput,
        password,
      })
      setTokens(data.access_token, data.refresh_token)
      email.value = emailInput
      sessionStorage.setItem(EMAIL_KEY, emailInput)
      await fetchMe()
    } catch (err: unknown) {
      const msg = extractError(err, 'Credenciales inválidas')
      error.value = msg
      throw new Error(msg)
    } finally {
      loading.value = false
    }
  }

  async function fetchMe(): Promise<void> {
    try {
      const { data } = await http.get<User>('/users/me')
      user.value = data
    } catch {
      // /users/me no existe aún: el store queda sin perfil pero autenticado
      // (los tokens siguen siendo válidos). El guard del router acepta esto.
    }
  }

  async function logout(): Promise<void> {
    // T-110: se manda el refresh_token para que el backend lo
    // blackliste TAMBIEN. Medido el 2026-10-23 contra la API real: sin
    // el, el refresh capturado seguia sirviendo (200) y permitia rotar
    // access tokens nuevos durante 7 dias (el TTL del refresh). El
    // backend solo blacklistea el refresh si viene en el body.
    const refresh = getRefreshToken()
    try {
      await http.post('/auth/logout', { refresh_token: refresh })
    } catch {
      /* el logout nunca debe romper el cliente */
    }
    clearTokens()
    sessionStorage.removeItem(EMAIL_KEY)
    user.value = null
    email.value = null
  }

  // Sprint R5-sidebar (2026-07-06): cambio de clave del usuario
  // autenticado desde el dropdown del sidebar. NO invalida tokens
  // existentes (el usuario puede cerrar todas las sesiones con
  // /auth/logout/all si lo desea).
  async function changeMyPassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    try {
      await http.patch('/users/me/password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
    } catch (err: unknown) {
      const msg = extractError(err, 'No se pudo cambiar la contraseña')
      throw new Error(msg)
    }
  }

  // T-110: el interceptor avisa (con un evento) de que la sesion ya no
  // se puede renovar. Aqui se limpia el estado para que el guard del
  // router mande a /login, en vez de dejar al operador en una pagina
  // muerta donde cada llamada da 401 sin mensaje.
  if (typeof window !== 'undefined') {
    window.addEventListener('solidapp:sesion-caducada', () => {
      user.value = null
      email.value = null
      sessionStorage.removeItem(EMAIL_KEY)
    })
  }

  async function restore(): Promise<void> {
    if (!email.value) return
    await fetchMe()
  }

  return {
    user, email, loading, error,
    isAuthenticated, role,
    login, logout, changeMyPassword, restore,
  }
})

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}