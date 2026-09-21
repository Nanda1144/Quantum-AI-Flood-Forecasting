/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The exact experiment configuration for the selected run — every row comes
 * from the stored result document or the job summary. The RNG seed is honestly
 * reported as not recorded by the gateway rather than a plausible-looking value.
 */

import { CalendarRange, Cpu, Layers, Settings2, SlidersHorizontal, Timer, type LucideIcon } from 'lucide-react'
import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'
import { formatDateTime, formatDuration } from '../../lib/format'

interface ExperimentConfigProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

interface ConfigRow {
  icon: LucideIcon
  label: string
  value: string
  hint?: string
}

export function ExperimentConfig({ summary, result }: ExperimentConfigProps) {
  const rows: ConfigRow[] = [
    {
      icon: Settings2,
      label: 'Problem type',
      value: summary.problemType.replace('_', ' '),
      hint: 'Instance class configured before the run',
    },
    {
      icon: SlidersHorizontal,
      label: 'Number of variables',
      value: String(summary.variablesCount ?? result.qubits ?? '—'),
      hint: 'QUBO binary variables; identical for both solvers',
    },
    {
      icon: Cpu,
      label: 'Classical solver',
      value: result.classicalComparison.method || '—',
      hint: 'Persisted classical reference solver',
    },
    {
      icon: SlidersHorizontal,
      label: 'QAOA layers (p)',
      value: String(result.layers),
    },
    {
      icon: SlidersHorizontal,
      label: 'Shots',
      value: String(result.shots),
    },
    {
      icon: Cpu,
      label: 'Backend',
      value: result.backend,
      hint: result.simulated ? 'Simulator execution' : 'Hardware execution',
    },
    {
      icon: Layers,
      label: 'Seed',
      value: 'Not recorded',
      hint: 'The gateway does not persist the RNG seed for QAOA sampling.',
    },
    {
      icon: CalendarRange,
      label: 'Experiment timestamp',
      value: formatDateTime(summary.createdAt),
    },
    {
      icon: Timer,
      label: 'Wall time',
      value: formatDuration(result.executionTimeMs),
      hint: 'Stored QAOA wall time for this run',
    },
  ]

  return (
    <section className="glass-card" aria-label="Experiment configuration">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-mist-100">
        <Settings2 size={15} className="text-ai-300" aria-hidden="true" />
        Experiment configuration
      </h2>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {rows.map(({ icon: Icon, label, value, hint }) => (
          <div key={label} className="flex items-baseline justify-between gap-3 border-b border-forest-800/60 py-1.5" title={hint}>
            <dt className="flex items-center gap-1.5 text-xs text-mist-400">
              <Icon size={12} className="text-forest-400" aria-hidden="true" />
              {label}
            </dt>
            <dd className="truncate text-right font-mono text-xs text-mist-100">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}