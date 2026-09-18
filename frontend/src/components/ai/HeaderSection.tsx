import { BrainCircuit, RefreshCw } from 'lucide-react'
import type { AIServiceHealth } from '../../types/ai'
import { StatusIndicator } from '../ui/StatusIndicator'
import { formatClock } from '../../lib/format'

interface HeaderSectionProps {
  lastUpdated: string | null
  refreshing: boolean
  onRefresh: () => void
  serviceHealth: AIServiceHealth
}

export function HeaderSection({ lastUpdated, refreshing, onRefresh, serviceHealth }: HeaderSectionProps) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3.5">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_24px_-6px_rgba(16,185,129,0.7)]">
          <BrainCircuit size={22} aria-hidden="true" />
        </span>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-mist-50">AI Analytics</h1>
            <span className="hidden sm:inline-flex">
              <StatusIndicator status={serviceHealth.status} subtle />
            </span>
          </div>
          <p className="mt-1 text-sm text-mist-500">Flood Forecasting Intelligence &amp; Optimization Readiness</p>
          <p className="mt-1 text-[11px] text-mist-600">
            Last updated {lastUpdated ? formatClock(lastUpdated) : '—'}
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800 px-3.5 py-2 text-xs font-semibold text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label={refreshing ? 'Refreshing AI analytics' : 'Refresh AI analytics'}
      >
        <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </button>
    </header>
  )
}