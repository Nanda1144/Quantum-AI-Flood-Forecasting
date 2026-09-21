/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Thin frontend client for the EXISTING backend authentication system
 * (`POST /api/auth/login`, JWT Bearer middleware — see backend/src/routes/
 * auth.routes.ts and backend/src/middleware/authorize.ts). This module does
 * NOT implement a new auth system: it consumes the backend's issued JWT,
 * persists it for the tab session, and attaches it to API requests.
 */

/** Session storage keeps the token out of the URL and clears on tab close. */
const TOKEN_KEY = 'qflare.auth.token'
const USER_KEY = 'qflare.auth.user'

export type AuthRole = 'admin' | 'operator' | 'viewer'

/** Principal returned by the existing backend login endpoint. */
export interface AuthUser {
  username: string
  role: AuthRole
}

/** A stored frontend session bound to the backend-issued token. */
export interface AuthSession {
  token: string
  user: AuthUser
}

export interface AuthLoginResponse {
  token: string
  user: AuthUser
}

export function getStoredSession(): AuthSession | null {
  try {
    const token = sessionStorage.getItem(TOKEN_KEY)
    const rawUser = sessionStorage.getItem(USER_KEY)
    if (!token || !rawUser) return null
    const user = JSON.parse(rawUser) as AuthUser
    if (!user || typeof user.username !== 'string') return null
    return { token, user }
  } catch {
    return null
  }
}

export function storeSession(session: AuthSession): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, session.token)
    sessionStorage.setItem(USER_KEY, JSON.stringify(session.user))
  } catch {
    /* storage unavailable (private mode) — session simply won't persist */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
  } catch {
    /* storage unavailable */
  }
}

/** Adds `Authorization: Bearer <token>` when a token is stored. */
export function authHeaders(): Record<string, string> {
  const session = getStoredSession()
  if (!session?.token) return {}
  return { Authorization: `Bearer ${session.token}` }
}

let unauthorizedHandler: (() => void) | null = null

/** Registers a handler invoked when any API client observes a 401 response. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

/** Called by API clients when the backend rejects with 401 (token invalid/expired). */
export function notifyUnauthorized(): void {
  clearSession()
  unauthorizedHandler?.()
}

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * Logs in against the existing backend endpoint and returns the issued JWT +
 * principal. Throws a descriptive Error on any failure.
 */
export async function apiLogin(username: string, password: string): Promise<AuthLoginResponse> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!response.ok) {
      let message = `Login failed with status ${response.status}`
      try {
        const body = (await response.json()) as { error?: { message?: string } }
        if (body?.error?.message) message = body.error.message
      } catch {
        /* non-JSON error body, keep defaults */
      }
      throw new Error(message)
    }
    const payload = (await response.json()) as { data?: unknown } & Record<string, unknown>
    const data = (payload.data ?? payload) as Partial<AuthLoginResponse>
    if (!data.token || !data.user?.username || !isValidRole(data.user.role)) {
      throw new Error('Login response was malformed')
    }
    return { token: data.token, user: { username: data.user.username, role: data.user.role } }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Login request timed out')
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}

function isValidRole(role: unknown): role is AuthRole {
  return role === 'admin' || role === 'operator' || role === 'viewer'
}