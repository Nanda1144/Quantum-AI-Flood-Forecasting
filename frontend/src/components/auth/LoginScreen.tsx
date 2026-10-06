/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useState, type FormEvent } from 'react'
import { BrainCircuit, Eye, EyeOff, KeyRound, LogIn, User } from 'lucide-react'
import { QuantumCircuitBackground } from '../quantum/QuantumCircuitBackground'
import { useAuth } from '../../auth/AuthContext'

const inputClasses =
  'w-full rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2.5 pr-9 text-sm text-mist-50 placeholder:text-mist-600 focus:border-emerald-500/70 focus:outline-none'

/**
 * Frontend login UI. Consumes the platform's existing authentication
 * (POST /api/auth/login) — this component adds no new auth logic, it only
 * collects credentials and renders the result of the existing backend login.
 */
export function LoginScreen() {
  const { login, loggingIn, error } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password || loggingIn) return
    await login(username, password)
  }

  return (
    <div className="relative min-h-screen">
      <QuantumCircuitBackground />
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="glass-card glass-card--glow px-7 py-8">
            <div className="mb-6 flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-xl border border-emerald-500/40 bg-emerald-500/15 text-emerald-400">
                <BrainCircuit size={22} aria-hidden="true" />
              </span>
              <div>
                <p className="text-lg font-bold tracking-tight text-emerald-400">Q-FLARE</p>
                <p className="text-[11px] uppercase tracking-widest text-mist-500">
                  AI Flood Forecasting
                </p>
              </div>
            </div>

            <h1 className="text-lg font-semibold text-mist-50">Sign in</h1>
            <p className="mt-1 text-xs text-mist-500">
              The dashboard is protected — every platform API requires an authenticated session.
            </p>

            <form onSubmit={handleSubmit} className="mt-5 space-y-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-mist-300">Username</span>
                <span className="relative block">
                  <User size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-mist-600" />
                  <input
                    type="text"
                    name="username"
                    autoComplete="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="e.g. operator"
                    className={`${inputClasses} pl-9`}
                    required
                  />
                </span>
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-mist-300">Password</span>
                <span className="relative block">
                  <KeyRound size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-mist-600" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="••••••••"
                    className={`${inputClasses} pl-9`}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((visible) => !visible)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-mist-500 transition-colors hover:text-mist-100"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
                  </button>
                </span>
              </label>

              {error && (
                <p role="alert" className="rounded-lg border border-critical-500/40 bg-critical-500/10 px-3 py-2 text-xs text-critical-400">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loggingIn || !username.trim() || !password}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-4 py-2.5 text-sm font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loggingIn ? (
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" aria-hidden="true" />
                ) : (
                  <LogIn size={15} aria-hidden="true" />
                )}
                {loggingIn ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </div>

          <p className="mt-4 text-center text-[11px] text-mist-600">
            Demo users — operator / qflare-operator · admin / qflare-admin · viewer / qflare-viewer.
          </p>
        </div>
      </div>
    </div>
  )
}