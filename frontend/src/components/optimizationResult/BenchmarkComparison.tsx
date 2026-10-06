/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Scale } from 'lucide-react'
import { GlassCard } from '../ui/GlassCard'
import { SectionHeader } from '../ui/SectionHeader'
import { formatDuration } from '../../lib/format'
import { formatScore } from '../../lib/quantum'
import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'

const EPS = 1e-6

interface BenchmarkComparisonProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

function verdict(result: OptimizationResult): string {
  const diff = result.objectiveValue - result.classicalComparison.objectiveValue
  if (diff > EPS) return 'The quantum path returned a higher objective than the classical reference on this run.'
  if (diff < -EPS) return 'The classical reference returned a higher objective than the quantum path on this run.'
  return 'The two paths reached the same objective on this run.'
}

export function BenchmarkComparison({ summary, result }: BenchmarkComparisonProps) {
  const classical = result.classicalComparison
  const approximation = summary.resultSummary.approximationQuality

  const rows: { metric: string; quantum: string; classicalValue: string; note: string }[] = [
    {
      metric: 'Objective value',
      quantum: formatScore(result.objectiveValue),
      classicalValue: formatScore(classical.objectiveValue),
      note: 'Fraction of the weighted utility captured by each solver (higher is better).',
    },
    {
      metric: 'Runtime',
      quantum: formatDuration(result.executionTimeMs),
      classicalValue: formatDuration(classical.executionTimeMs),
      note: 'Stored wall time. Different implementations — not a like-for-like speedup comparison.',
    },
    {
      metric: 'Approximation quality',
      quantum: approximation === null ? '—' : formatScore(approximation),
      classicalValue: '1.00 (reference)',
      note: 'Stored min(1, quantum ÷ classical). Below 1.00 the reference captured more utility.',
    },
    {
      metric: 'Selected locations',
      quantum: String(result.selectedLocations.length),
      classicalValue: String(classical.selectedCount),
      note: 'Sites chosen by each solver for the same instance.',
    },
    {
      metric: 'Constraint violations',
      quantum: String(result.constraintViolations.length),
      classicalValue: '—',
      note: 'Violations are recorded for the decoded quantum selection only.',
    },
  ]

  return (
    <GlassCard>
      <SectionHeader
        icon={Scale}
        title="Quantum vs classical benchmark"
        description={`Stored comparison against the ${classical.method || 'classical'} reference that ran the identical instance`}
      />

      <div className="mt-4 overflow-x-auto rounded-lg border border-forest-600">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead>
            <tr className="border-b border-forest-600 bg-forest-800/60 text-mist-500">
              <th className="px-3 py-2 font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium text-ai-300">Quantum</th>
              <th className="px-3 py-2 text-right font-medium">Classical reference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric} className="border-b border-forest-700/50 last:border-0" title={row.note}>
                <td className="px-3 py-2 text-mist-300">{row.metric}</td>
                <td className="px-3 py-2 text-right font-mono text-ai-300">{row.quantum}</td>
                <td className="px-3 py-2 text-right font-mono text-mist-300">{row.classicalValue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-mist-300">{verdict(result)}</p>
      <p className="mt-1 text-[11px] text-mist-600">
        This is one experiment on one instance and backend. No quantum speedup or universal advantage is claimed; every figure is
        stored with the job.
      </p>
    </GlassCard>
  )
}
