import { CalendarRange, Database, RefreshCw } from 'lucide-react'
import { formatDateTime } from '../../lib/format'

interface ComparisonHeaderProps {
  evaluationDatasets: string[]
  evaluatedRange: { from: string | null; to: string | null }
  refreshing: boolean
  onRefresh: () => void
}

export function ComparisonHeader({
  evaluationDatasets,
  evaluatedRange,
  refreshing,
  onRefresh,
}: ComparisonHeaderProps) {
  const datasetLabel =
    evaluationDatasets.length === 0
      ? 'No evaluation campaign recorded'
      : evaluationDatasets.length === 1
        ? evaluationDatasets[0]
        : `${evaluationDatasets[0]} +${evaluationDatasets.length - 1} more`
  const windowLabel =
    evaluatedRange.from && evaluatedRange.to
      ? `${formatDateTime(evaluatedRange.from)} → ${formatTimeOnly(evaluatedRange.to)}`
      : 'No scored evaluations yet'

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-mist-50">Model Comparison</h1>
        <p className="mt-1 text-sm text-mist-400">AI Forecasting Model Evaluation</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-mist-300">
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800/70 px-2.5 py-1">
            <Database size={13} aria-hidden="true" />
            <span title={evaluationDatasets.join('\n')}>{datasetLabel}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-forest-600 bg-forest-800/70 px-2.5 py-1">
            <CalendarRange size={13} aria-hidden="true" />
            {windowLabel}
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        aria-label="Refresh model comparison data"
        className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800 px-3.5 py-2 text-xs font-semibold transition-colors hover:border-emerald-500/60 hover:text-emerald-300 focus-visible:outline-2 focus-visible:outline-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={refreshing}
      >
        <RefreshCw size={14} aria-hidden="true" className={refreshing ? 'animate-spin' : ''} />
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </button>
    </header>
  )
}

function formatTimeOnly(iso: string): string {
  return formatDateTime(iso).split(',')[0] ?? formatDateTime(iso)
}