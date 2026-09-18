import { ArrowRight, ChevronRight, CheckCircle2, XCircle } from 'lucide-react'
import type { OptimizationReadiness, RiskLevel } from '../../types/ai'
import { riskStyle } from '../../lib/risk'
import { useNavigate } from 'react-router-dom'

interface OptimizationBridgeProps {
  readiness: OptimizationReadiness
  riskLevel: RiskLevel
}

export function OptimizationBridge({ readiness, riskLevel }: OptimizationBridgeProps) {
  const navigate = useNavigate()
  const risk = riskStyle(riskLevel)

  const handleUseForecast = () => {
    navigate('/quantum-optimization', {
      state: { forecastId: readiness.forecastId, riskScore: readiness.riskScore, priority: readiness.priority },
    })
  }

  const checklist = [
    {
      label: 'Candidate locations loaded',
      ok: readiness.candidateLocationsAvailable,
    },
    {
      label: 'Resource constraints defined',
      ok: readiness.resourceConstraintsAvailable,
    },
    {
      label: 'Forecast data ready',
      ok: readiness.ready,
    },
  ]

  return (
    <section
      className={`relative overflow-hidden rounded-2xl border ${risk.border} bg-gradient-to-br from-forest-800/90 via-forest-850/90 to-forest-900/90 p-6`}
      aria-label="Optimization readiness bridge"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(500px_200px_at_80%_0%,rgba(16,185,129,0.18),transparent)]" />

      <div className="relative z-10 flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <span className="inline-flex size-10 items-center justify-center rounded-xl border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_24px_-6px_rgba(16,185,129,0.6)]">
              <ArrowRight size={20} aria-hidden="true" />
            </span>
            <div>
              <h3 className="text-lg font-bold text-mist-50">Ready for Optimization</h3>
              <p className="text-xs text-mist-500">Current forecast can be used for quantum sensor placement optimization</p>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-x-10 gap-y-3 sm:grid-cols-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-mist-600">Forecast ID</p>
              <p className="mt-0.5 font-mono text-sm font-bold text-mist-50">{readiness.forecastId}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-mist-600">Risk Score</p>
              <p className="mt-0.5 font-mono text-sm font-bold text-mist-50">
                {Math.round(readiness.riskScore * 100)}%
                <span className="ml-2 inline-flex items-center gap-1 text-[11px] font-medium">
                  <span className={`size-1.5 rounded-full ${risk.dot}`} aria-hidden="true" />
                  <span className={risk.text}>{riskLevel.toUpperCase()}</span>
                </span>
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-mist-600">Priority</p>
              <p className="mt-0.5 font-mono text-sm font-bold uppercase text-mist-50">{readiness.priority}</p>
            </div>
          </div>

          <ul className="mt-5 flex flex-wrap gap-x-6 gap-y-2" role="list">
            {checklist.map((item) => (
              <li key={item.label} className="inline-flex items-center gap-1.5 text-xs text-mist-300">
                {item.ok ? (
                  <CheckCircle2 size={14} className="text-emerald-300" aria-hidden="true" />
                ) : (
                  <XCircle size={14} className="text-critical-400" aria-hidden="true" />
                )}
                <span aria-label={`${item.label}: ${item.ok ? 'ready' : 'not ready'}`}>{item.label}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="shrink-0">
          <button
            type="button"
            onClick={handleUseForecast}
            className="group inline-flex items-center gap-2.5 rounded-xl border border-emerald-500/50 bg-emerald-500/15 px-5 py-3 text-sm font-bold text-emerald-300 shadow-[0_0_28px_-8px_rgba(16,185,129,0.5)] transition-all hover:border-emerald-400 hover:bg-emerald-500/20 hover:shadow-[0_0_32px_-6px_rgba(16,185,129,0.65)] focus-visible:outline-2 focus-visible:outline-emerald-400"
            aria-label="Use this forecast to start quantum optimization"
          >
            Use Forecast for Optimization
            <ChevronRight size={18} className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>
  )
}