import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { AIAnalyticsDashboard } from './pages/AIAnalyticsDashboard'
import { QuantumOptimization } from './pages/QuantumOptimization'
import { ModelComparison } from './pages/ModelComparison'
import { BrainCircuit, GitCompare, Rocket, type LucideIcon } from 'lucide-react'

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
  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-50 border-b border-forest-700/60 bg-forest-900/90 backdrop-blur-lg" aria-label="Main navigation">
        <div className="mx-auto flex max-w-[1440px] items-center gap-1 px-4 py-2.5 sm:px-6 lg:px-10">
          <span className="mr-3 text-sm font-bold tracking-tight text-emerald-400">Q-FLARE</span>
          <NavLink to="/" icon={BrainCircuit}>AI Analytics</NavLink>
          <NavLink to="/model-comparison" icon={GitCompare}>Model Comparison</NavLink>
          <NavLink to="/quantum-optimization" icon={Rocket}>Quantum Optimization</NavLink>
        </div>
      </nav>
      {children}
    </div>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<AIAnalyticsDashboard />} />
          <Route path="/model-comparison" element={<ModelComparison />} />
          <Route path="/quantum-optimization" element={<QuantumOptimization />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}