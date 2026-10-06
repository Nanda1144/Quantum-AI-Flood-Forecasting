/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  apiLogin,
  clearSession,
  getStoredSession,
  setUnauthorizedHandler,
  storeSession,
  type AuthSession,
} from '../services/authService'

interface AuthContextValue {
  /** Active session, or null when signed out. */
  session: AuthSession | null
  loggingIn: boolean
  error: string | null
  /** Logs in via the existing backend endpoint. Returns false when rejected. */
  login: (username: string, password: string) => Promise<boolean>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => getStoredSession())
  const [loggingIn, setLoggingIn] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setSession(null)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  const login = useMemo(
    () =>
      async (username: string, password: string): Promise<boolean> => {
        setError(null)
        setLoggingIn(true)
        try {
          const { token, user } = await apiLogin(username.trim(), password)
          storeSession({ token, user })
          setSession({ token, user })
          return true
        } catch (loginError) {
          setError(loginError instanceof Error ? loginError.message : 'Login failed')
          return false
        } finally {
          setLoggingIn(false)
        }
      },
    [],
  )

  const logout = useMemo(
    () => () => {
      clearSession()
      setSession(null)
      setError(null)
    },
    [],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ session, loggingIn, error, login, logout }),
    [session, loggingIn, error, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// oxlint-disable-next-line react/only-export-components -- context hook export pattern is intentional
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within an AuthProvider')
  return value
}