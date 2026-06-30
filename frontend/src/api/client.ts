/**
 * Cliente HTTP compartido. Adjunta el access token, gestiona refresh
 * automático ante 401 y expone helpers tipados por endpoint.
 *
 * Formato de tokens (Pydantic `TokenPair`):
 *   access_token:  str  (TTL 15 min)
 *   refresh_token: str  (TTL 7 días)
 *   token_type:    str  ("bearer")
 *   expires_in:    int  (segundos)
 */
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

const baseURL = import.meta.env.VITE_API_BASE
  ? `${import.meta.env.VITE_API_BASE.replace(/\/$/, '')}/api/v1`
  : '/api/v1'

export const http: AxiosInstance = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

// ── Tokens (persistidos en sessionStorage: se borran al cerrar pestaña) ──
const ACCESS_KEY = 'solidapp.access'
const REFRESH_KEY = 'solidapp.refresh'

export function setTokens(access: string, refresh: string): void {
  sessionStorage.setItem(ACCESS_KEY, access)
  sessionStorage.setItem(REFRESH_KEY, refresh)
}

export function setAccessToken(access: string): void {
  sessionStorage.setItem(ACCESS_KEY, access)
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY)
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}

// ── Interceptor: Authorization header ──────────────────────────────────
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Interceptor: refresh en 401, una sola vez por petición ─────────────
let refreshing: Promise<string | null> | null = null

async function doRefresh(): Promise<string | null> {
  const refresh = getRefreshToken()
  if (!refresh) return null
  try {
    const { data } = await axios.post<{
      access_token: string
      refresh_token: string
      expires_in: number
    }>(`${baseURL}/auth/refresh`, { refresh_token: refresh })
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch {
    clearTokens()
    return null
  }
}

http.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !original.url?.includes('/auth/')
    ) {
      original._retry = true
      refreshing = refreshing ?? doRefresh()
      const newAccess = await refreshing
      refreshing = null
      if (newAccess) {
        original.headers = original.headers ?? {}
        original.headers.Authorization = `Bearer ${newAccess}`
        return http(original)
      }
    }
    return Promise.reject(error)
  },
)

// ── Tipos compartidos (espejo de los schemas Pydantic) ─────────────────
export interface User {
  id: number
  email: string
  full_name: string
  phone: string | null
  role: 'admin' | 'gestor' | 'operador' | 'cliente'
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}