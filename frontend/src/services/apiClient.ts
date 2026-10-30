import { ref } from 'vue'
import { Capacitor } from '@capacitor/core'

/**
 * Reactive auth session state.
 */
export const isAuthenticated = ref<boolean>(
  typeof window !== 'undefined' && Boolean(localStorage.getItem('token'))
)

export const currentAuthEmail = ref<string | null>(
  typeof window !== 'undefined' ? localStorage.getItem('user_email') : null
)

/**
 * Resolve base API URL, supporting Capacitor native platforms and Vite environment variables.
 */
export function getBaseApiUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl) {
    return envUrl.replace(/\/+$/, '')
  }
  if (Capacitor.isNativePlatform()) {
    return 'http://localhost:8000'
  }
  return ''
}

/**
 * Resolve a full URL for relative API paths.
 */
export function resolveApiUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  const base = getBaseApiUrl()
  const cleanPath = path.startsWith('/') ? path : `/${path}`
  return base ? `${base}${cleanPath}` : cleanPath
}

/**
 * Completely clear the user session from storage and update reactive auth state.
 */
export function clearAuthSession(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user_email')
  isAuthenticated.value = false
  currentAuthEmail.value = null
  window.dispatchEvent(new CustomEvent('notesight:auth-changed', { detail: { authenticated: false } }))
}

/**
 * Set the user session in storage and update reactive state.
 */
export function setAuthSession(token: string, refreshToken?: string | null, email?: string | null): void {
  if (typeof window === 'undefined') return
  localStorage.setItem('token', token)
  if (refreshToken) {
    localStorage.setItem('refresh_token', refreshToken)
  }
  if (email) {
    localStorage.setItem('user_email', email)
    currentAuthEmail.value = email
  }
  isAuthenticated.value = true
  window.dispatchEvent(new CustomEvent('notesight:auth-changed', { detail: { authenticated: true } }))
}

/**
 * Safely parse a JWT payload without external libraries.
 */
export function decodeJwtPayload(token: string): Record<string, any> | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
    return JSON.parse(jsonPayload)
  } catch {
    return null
  }
}

/**
 * Check whether a JWT token is expired or will expire within threshold seconds.
 */
export function isTokenExpiringSoon(token: string, thresholdSeconds: number = 30): boolean {
  const payload = decodeJwtPayload(token)
  if (!payload || !payload.exp) return true
  const currentTimeSec = Math.floor(Date.now() / 1000)
  return payload.exp <= currentTimeSec + thresholdSeconds
}

// Single-flight promise mutex for refresh token rotation
let activeRefreshPromise: Promise<string | null> | null = null

/**
 * Execute a single-flight Refresh Token Rotation (RTR).
 * Exchanging the stored refresh_token for a fresh access_token & new refresh_token.
 */
export async function refreshAuthToken(): Promise<string | null> {
  if (activeRefreshPromise) {
    return activeRefreshPromise
  }

  const storedRefreshToken = typeof window !== 'undefined' ? localStorage.getItem('refresh_token') : null
  if (!storedRefreshToken) {
    clearAuthSession()
    return null
  }

  activeRefreshPromise = (async () => {
    try {
      const url = resolveApiUrl('/api/refresh-token')
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: storedRefreshToken }),
      })

      if (!response.ok) {
        clearAuthSession()
        return null
      }

      const data = await response.json()
      if (data && data.access_token) {
        setAuthSession(data.access_token, data.refresh_token)
        return data.access_token as string
      }

      clearAuthSession()
      return null
    } catch (err) {
      console.warn('[apiClient] Refresh token network error:', err)
      return null
    } finally {
      activeRefreshPromise = null
    }
  })()

  return activeRefreshPromise
}

/**
 * Centralized API Fetch client with automatic Authorization header injection,
 * single-flight Refresh Token Rotation (RTR) on 401, and unified session cleanup.
 */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let resolvedUrl: string | Request = input as any
  if (typeof input === 'string') {
    resolvedUrl = resolveApiUrl(input)
  } else if (input instanceof URL) {
    resolvedUrl = input.toString()
  }

  const headers = new Headers(init?.headers || {})
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const modifiedInit: RequestInit = {
    ...init,
    headers,
  }

  let response: Response
  try {
    response = await fetch(resolvedUrl, modifiedInit)
  } catch (netErr) {
    throw netErr
  }

  // Intercept 401 Unauthorized for token rotation
  if (response.status === 401) {
    const refreshToken = typeof window !== 'undefined' ? localStorage.getItem('refresh_token') : null
    if (refreshToken) {
      const newToken = await refreshAuthToken()
      if (newToken) {
        // Retry the original request transparently with the freshly rotated token
        const retryHeaders = new Headers(init?.headers || {})
        retryHeaders.set('Authorization', `Bearer ${newToken}`)
        return fetch(resolvedUrl, {
          ...init,
          headers: retryHeaders,
        })
      }
    }

    // Refresh failed or no refresh token: purge session
    clearAuthSession()
  }

  return response
}
