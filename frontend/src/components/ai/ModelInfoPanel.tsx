/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Boxes } from 'lucide-react'
import type { ModelInfo } from '../../types/ai'
import { SectionHeader } from '../ui/SectionHeader'
import { formatDateTime, formatRelative } from '../../lib/format'
import { modelStatusText } from '../../lib/risk'

interface ModelInfoPanelProps {
  model: ModelInfo
}

interface MetricCellProps {
  label: string
  value: number | undefined
  unit?: string
  goodWhen?: 'low' | 'high'
}

function MetricCell({ label, value, unit, goodWhen }: MetricCellProps) {
  if (value === undefined) return null
  const tone =
    goodWhen === 'low'
      ? value < 0.25
        ? 'text-emerald-300'
        : 'text-amber-400'
      : value >= 0.85
        ? 'text-emerald-300'
        : 'text-amber-400'
  return (
    <div className="rounded-lg border border-forest-600/70 bg-forest-800/60 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-mist-600">{label}</p>
      <p className={`mt-0.5 text-sm font-bold tabular-nums ${tone}`}>
        {value.toFixed(3)}
        {unit ? <span className="ml-1 text-[10px] font-medium text-mist-500">{unit}</span> : null}
      </p>
    </div>
  )
}

export function ModelInfoPanel({ model }: ModelInfoPanelProps) {
  const rows: Array<{ label: string; value: string }> = [
    { label: 'Model ID', value: model.modelId },
    { label: 'Algorithm', value: model.algorithm },
    { label: 'Version', value: model.version },
    { label: 'Last trained', value: `${formatDateTime(model.lastTrainedAt)} (${formatRelative(model.lastTrainedAt)})` },
    { label: 'Last evaluated', value: `${formatDateTime(model.lastEvaluatedAt)} (${formatRelative(model.lastEvaluatedAt)})` },
  ]

  return (
    <div className="glass-card p-5">
      <SectionHeader
        icon={Boxes}
        title="Model Information"
        description="Active flood forecasting model"
      />

      <div className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold text-mist-50">{model.name}</h3>
            <p className="mt-0.5 text-xs text-mist-500">{model.algorithm}</p>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-forest-600 bg-forest-800 px-2.5 py-1 text-xs font-semibold text-mist-200">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-emerald-400" />
            {modelStatusText(model.status)}
          </span>
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-3 border-b border-forest-700/50 pb-2">
              <dt className="text-[11px] font-medium uppercase tracking-wider text-mist-600">{row.label}</dt>
              <dd className="text-right text-xs font-semibold text-mist-100">{row.value}</dd>
            </div>
          ))}
        </dl>

        <p className="mt-4 mb-2 text-[11px] font-semibold uppercase tracking-wider text-mist-600">
          Evaluation Metrics
        </p>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <MetricCell label="RMSE" value={model.metrics.rmse} unit="m" goodWhen="low" />
          <MetricCell label="MAE" value={model.metrics.mae} unit="m" goodWhen="low" />
          <MetricCell label="NSE" value={model.metrics.nse} goodWhen="high" />
          <MetricCell label="Accuracy" value={model.metrics.accuracy} goodWhen="high" />
        </div>
        {model.derived && (
          <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
            Assembled from the forecast record — this model has no stored registry row or evaluation data.
          </p>
        )}
      </div>
    </div>
  )
}