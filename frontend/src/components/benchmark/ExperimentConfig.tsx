/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * The exact experiment configuration for the selected run — every row comes
 * from the stored benchmark document (the pipeline's write-once snapshot). The
 * RNG seed is honestly reported as recorded (when the pipeline stored it) or
 * as not recorded, never as a plausible-looking value.
 */

import { CalendarRange, Cpu, Layers, Settings2, SlidersHorizontal, Timer, type LucideIcon } from 'lucide-react'
import type { BenchmarkDocument } from '../../types/benchmark'
import { quantumRuntimeLabel } from '../../lib/benchmark'
import { formatDateTime } from '../../lib/format'

interface ExperimentConfigProps {
  document: BenchmarkDocument
}

interface ConfigRow {
  icon: LucideIcon
  label: string
  value: string
  hint?: string
}

export function ExperimentConfig({ document }: ExperimentConfigProps) {
  const repro = document.reproducibility
  const seed = repro.seed
  const seedNote =
    seed !== null
      ? 'Stored QAOA RNG seed as captured by the pipeline (reproducibility snapshot).'
      : 'The gateway did not capture an RNG seed for this run — reported honestly rather than invented.'

  const rows: ConfigRow[] = [
    {
      icon: Settings2,
      label: 'Problem type',
      value: repro.problem.type.replace('_', ' '),
      hint: 'Instance class configured before the run',
    },
    {
      icon: SlidersHorizontal,
      label: 'Number of variables',
      value: String(document.problem.size.variables),
      hint: 'QUBO binary variables; identical for both solvers',
    },
    {
      icon: Cpu,
      label: 'Classical solver',
      value: document.classical.method,
      hint: 'Persisted classical reference solver',
    },
    {
      icon: SlidersHorizontal,
      label: 'QAOA layers (p)',
      value: String(document.quantum.layers),
    },
    {
      icon: SlidersHorizontal,
      label: 'Shots',
      value: String(document.quantum.shots),
    },
    {
      icon: Cpu,
      label: 'Backend',
      value: document.quantum.backend,
      hint:
        document.quantum.simulated === true
          ? 'Simulator execution'
          : document.quantum.simulated === false
            ? 'Non-simulator execution'
            : 'Execution detail not persisted',
    },
    {
      icon: Layers,
      label: 'Seed',
      value: seed !== null ? String(seed) : 'Not recorded',
      hint: seedNote,
    },
    {
      icon: CalendarRange,
      label: 'Experiment timestamp',
      value: formatDateTime(document.completedAt),
    },
    {
      icon: Timer,
      label: 'Wall time',
      value: quantumRuntimeLabel(document),
      hint: 'Stored QAOA executor wall time; pipeline total when not persisted',
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