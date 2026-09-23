/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Box, CircleHelp, Info } from 'lucide-react'
import type { ModelComparisonRow } from '../../types/ai'
import { formatDateTime, formatDuration, formatMetric } from '../../lib/format'
import { StatusBadge } from './StatusBadge'

interface ModelDetailPanelProps {
  model: ModelComparisonRow | null
}

const METRIC_LABELS: { key: keyof import('../../types/ai').ComparisonMetricScores; label: string }[] = [
  { key: 'rmse', label: 'RMSE' },
  { key: 'mae', label: 'MAE' },
  { key: 'r2', label: 'R²' },
  { key: 'nse', label: 'NSE' },
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'precision', label: 'Precision' },
  { key: 'recall', label: 'Recall' },
  { key: 'f1', label: 'F1' },
]

export function ModelDetailPanel({ model }: ModelDetailPanelProps) {
  const present = METRIC_LABELS.filter((entry) => typeof model?.metrics[entry.key] === 'number')

  return (
    <section className="glass-card p-5" aria-label="Model details">
      {!model ? (
        <div className="flex items-center gap-3 py-2 text-sm text-mist-500">
          <CircleHelp size={18} aria-hidden="true" className="text-mist-600" />
          Select a row or bar to inspect a model version.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex size-10 items-center justify-center rounded-lg border border-ai-500/40 bg-ai-500/10 text-ai-300">
                <Box size={18} aria-hidden="true" />
              </span>
              <div>
                <h3 className="text-base font-bold text-mist-50">{model.name}</h3>
                <p className="font-mono text-xs text-mist-400">
                  {model.version} · {model.algorithm}
                </p>
              </div>
            </div>
            <StatusBadge status={model.status} />
          </div>

          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Dataset</dt>
              <dd className="mt-1 break-all font-mono text-xs text-mist-200" title={model.dataset}>
                {model.dataset || 'Not registered'}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Evaluation dataset</dt>
              <dd className="mt-1 break-all font-mono text-xs text-mist-200" title={model.evaluationDataset}>
                {model.evaluationDataset || 'Not registered'}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Evaluated at</dt>
              <dd className="mt-1 font-mono text-xs text-mist-200">
                {model.evaluatedAt ? formatDateTime(model.evaluatedAt) : 'Never evaluated'}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Training time</dt>
              <dd className="mt-1 font-mono text-xs text-mist-200">{formatDuration(model.trainingTimeMs)}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Inference time</dt>
              <dd className="mt-1 font-mono text-xs text-mist-200">{formatDuration(model.inferenceTimeMs)}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Model artifact</dt>
              <dd className="mt-1 break-all font-mono text-xs text-mist-200" title={model.artifactReference}>
                {model.artifactReference || 'Not registered'}
              </dd>
            </div>
          </dl>

          <div>
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-mist-500">Stored metrics</h4>
            {present.length === 0 ? (
              <p className="mt-1 text-xs text-mist-600">No evaluation scores have been stored for this version.</p>
            ) : (
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {present.map((entry) => (
                  <div key={entry.key} className="rounded-lg border border-forest-700/70 bg-forest-900/50 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wider text-mist-500">{entry.label}</p>
                    <p className="mt-0.5 font-mono text-sm font-bold text-emerald-300">
                      {formatMetric(model.metrics[entry.key])}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <p className="flex items-start gap-2 rounded-lg border border-forest-700/60 bg-forest-900/40 px-3 py-2 text-[11px] text-mist-500">
            <Info size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-emerald-500" />
            Deployment status is managed by the model registry and training pipeline. Promoting a version to
            production requires administrator authorization server-side — this view is read-only.
          </p>
        </div>
      )}
    </section>
  )
}