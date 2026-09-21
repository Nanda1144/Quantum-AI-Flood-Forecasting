/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { AIAnalyticsDashboard } from './pages/AIAnalyticsDashboard'
import { QuantumOptimization } from './pages/QuantumOptimization'
import { ModelComparison } from './pages/ModelComparison'
import { QuboVisualization } from './pages/QuboVisualization'
import { QuantumJobStatus } from './pages/QuantumJobStatus'
import { QuantumBenchmark } from './pages/QuantumBenchmark'
import { OptimizationResult } from './pages/OptimizationResult'
import { LoginScreen } from './components/auth/LoginScreen'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { BrainCircuit, GitCompare, LogOut, Rocket, Scale, type LucideIcon } from 'lucide-react'

function NavLink({ to, children, icon: Icon }: { to: string; children: React.ReactNode; icon: LucideIcon }) {
  const location = useLocation()
  const active = location.pathname === to
  return (
    <Link
      to={to}
      className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors ${
        active
          ? 'border border-emerald-500/50 bg-emerald-500/15 text-emerald-300'
          : 'text-mist-300 hover:border hover:border-forest-600 hover:text-mist-50'
      }`}
    >
      <Icon size={14} aria-hidden />
      {children}
    </Link>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  const { session, logout } = useAuth()
  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-50 border-b border-forest-700/60 bg-forest-900/90 backdrop-blur-lg" aria-label="Main navigation">
        <div className="mx-auto flex max-w-[1440px] items-center gap-1 px-4 py-2.5 sm:px-6 lg:px-10">
          <span className="mr-3 text-sm font-bold tracking-tight text-emerald-400">Q-FLARE</span>
          <NavLink to="/" icon={BrainCircuit}>AI Analytics</NavLink>
          <NavLink to="/model-comparison" icon={GitCompare}>Model Comparison</NavLink>
          <NavLink to="/quantum-optimization" icon={Rocket}>Quantum Optimization</NavLink>
          <NavLink to="/quantum-benchmark" icon={Scale}>Quantum Benchmark</NavLink>

          <div className="ml-auto flex items-center gap-3">
            {session && (
              <span className="hidden items-center gap-1.5 text-xs text-mist-300 sm:flex" title={`Signed in as ${session.user.username}`}>
                <span className="rounded-md border border-forest-600 bg-forest-800 px-2 py-1 font-mono text-[11px] text-emerald-300">
                  {session.user.username}
                </span>
                <span className="rounded border border-forest-700 bg-forest-850 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-mist-500">
                  {session.user.role}
                </span>
              </span>
            )}
            <button
              type="button"
              onClick={logout}
              className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 px-3 py-2 text-xs font-semibold text-mist-300 transition-colors hover:border-critical-500/60 hover:text-critical-400"
            >
              <LogOut size={13} aria-hidden="true" />
              Sign out
            </button>
          </div>
        </div>
      </nav>
      {children}
    </div>
  )
}

/**
 * Protected dashboard shell. Existing backend authentication controls access:
 * unauthenticated users see the login screen; authenticated sessions render
 * the dashboard routes. Authentication only gates access — model data flows
 * independently through the backend registry API.
 */
function Shell() {
  const { session } = useAuth()
  if (!session) return <LoginScreen />
  return (
    <Layout>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<AIAnalyticsDashboard />} />
          <Route path="/model-comparison" element={<ModelComparison />} />
          <Route path="/quantum-optimization" element={<QuantumOptimization />} />
          <Route path="/quantum-benchmark" element={<QuantumBenchmark />} />
          <Route path="/qubo-visualization/:jobId" element={<QuboVisualization />} />
          <Route path="/quantum/jobs/:jobId" element={<QuantumJobStatus />} />
          <Route path="/optimization/:id/result" element={<OptimizationResult />} />
        </Routes>
      </ErrorBoundary>
    </Layout>
  )
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <Shell />
      </BrowserRouter>
    </AuthProvider>
  )
}