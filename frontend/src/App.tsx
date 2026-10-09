/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or
 * fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { AIAnalyticsDashboard } from './pages/AIAnalyticsDashboard'
import { ForecastingDashboard } from './pages/ForecastingDashboard'
import { QuantumOptimization } from './pages/QuantumOptimization'
import { ModelComparison } from './pages/ModelComparison'
import { QuboVisualization } from './pages/QuboVisualization'
import { QuantumJobStatus } from './pages/QuantumJobStatus'
import { QuantumBenchmark } from './pages/QuantumBenchmark'
import { OptimizationResult } from './pages/OptimizationResult'
import { GISDashboard } from './pages/GISDashboard'
import { IoTDashboard } from './pages/IoTDashboard'
import { ResponsePlanningDashboard } from './pages/ResponsePlanningDashboard'
import { LoginScreen } from './components/auth/LoginScreen'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthProvider } from './auth/AuthContext'
import { BrainCircuit, CloudRain, GitCompare, Globe, Rocket, Scale, Shield, Wifi, type LucideIcon } from 'lucide-react'

function NavLink({ to, children, icon: Icon }: { to: string; children: React.ReactNode; icon: LucideIcon }) {
  const location = useLocation()
  const active = location.pathname === to
  return (
    <Link
      to={to}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
        active
          ? 'border border-emerald-400 bg-emerald-400/10 text-emerald-400 shadow-sm font-bold'
          : 'text-mist-300 hover:border hover:border-forest-600 hover:bg-forest-800 hover:text-mist-50'
      }`}
    >
      <Icon size={14} aria-hidden />
      {children}
    </Link>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      {/* Official Government Flag & Mission Header Bar */}
      <div className="border-b border-forest-600 bg-forest-800 px-4 py-1 text-[11px] text-mist-300">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-bold tracking-wide text-emerald-500">🏛️ NATIONAL QUANTUM MISSION</span>
            <span className="text-forest-500">•</span>
            <span className="font-medium text-mist-300">Central Water Commission (CWC) | Ministry of Jal Shakti</span>
          </div>
          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-0.5 text-[10px] font-bold text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"></span> DIRECT ACCESS COMMAND
            </span>
            <span className="text-mist-500 font-mono text-[10px]">ALL FEATURES UNLOCKED</span>
          </div>
        </div>
      </div>

      {/* Main Navigation Bar with All Feature Tabs */}
      <nav className="sticky top-0 z-50 border-b border-forest-700 bg-forest-900/95 shadow-sm backdrop-blur-lg" aria-label="Main navigation">
        <div className="mx-auto flex max-w-[1440px] items-center gap-1 px-4 py-2 sm:px-6 lg:px-8">
          <Link to="/" className="mr-3 flex items-center gap-2 no-underline">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10 font-bold text-emerald-400 border border-emerald-500/20 text-sm">
              🌊
            </span>
            <span className="text-base font-extrabold tracking-tight text-emerald-400">Q-FLARE</span>
          </Link>

          <div className="flex flex-wrap items-center gap-1">
            <NavLink to="/" icon={BrainCircuit}>AI Analytics</NavLink>
            <NavLink to="/forecasting" icon={CloudRain}>Flood Forecasting</NavLink>
            <NavLink to="/gis" icon={Globe}>GIS Spatial</NavLink>
            <NavLink to="/iot" icon={Wifi}>IoT Telemetry</NavLink>
            <NavLink to="/response" icon={Shield}>Response Planning</NavLink>
            <NavLink to="/model-comparison" icon={GitCompare}>Model Comparison</NavLink>
            <NavLink to="/quantum-optimization" icon={Rocket}>Quantum Optimization</NavLink>
            <NavLink to="/quantum-benchmark" icon={Scale}>Quantum Benchmark</NavLink>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 text-xs text-mist-300 sm:flex">
              <span className="rounded-md border border-forest-600 bg-forest-850 px-2.5 py-0.5 font-mono text-[11px] font-medium text-emerald-400">
                Officer Station
              </span>
              <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                ADMIN
              </span>
            </span>
          </div>
        </div>
      </nav>
      {children}
    </div>
  )
}

/**
 * Direct Command Center Shell.
 * Login requirement removed: all options and features are immediately accessible.
 */
function Shell() {
  return (
    <Layout>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<AIAnalyticsDashboard />} />
          <Route path="/forecasting" element={<ForecastingDashboard />} />
          <Route path="/gis" element={<GISDashboard />} />
          <Route path="/iot" element={<IoTDashboard />} />
          <Route path="/response" element={<ResponsePlanningDashboard />} />
          <Route path="/model-comparison" element={<ModelComparison />} />
          <Route path="/quantum-optimization" element={<QuantumOptimization />} />
          <Route path="/quantum-benchmark" element={<QuantumBenchmark />} />
          <Route path="/qubo-visualization/:jobId" element={<QuboVisualization />} />
          <Route path="/quantum/jobs/:jobId" element={<QuantumJobStatus />} />
          <Route path="/optimization/:id/result" element={<OptimizationResult />} />
          <Route path="/login" element={<LoginScreen />} />
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