/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { OptimizationResult, QuantumJobSummary } from '../../types/optimization'
import { formatDuration } from '../../lib/format'
import { formatScore } from '../../lib/quantum'

interface ResultSummaryCardsProps {
  summary: QuantumJobSummary
  result: OptimizationResult
}

function KPI({ label, value, accent = 'text-mist-100', hint }: { label: string; value: string; accent?: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-forest-700/60 bg-forest-800/40 px-3 py-2.5" title={hint}>
      <p className="text-[11px] uppercase tracking-wide text-mist-500">{label}</p>
      <p className={`mt-1 truncate font-mono text-sm ${accent}`}>{value}</p>
    </div>
  )
}

export function ResultSummaryCards({ summary, result }: ResultSummaryCardsProps) {
  const violations = result.constraintViolations.length
  const approximation = summary.resultSummary.approximationQuality
  const classical = result.classicalComparison
  // Same predicate the executor uses: a job produced quantum outcomes only when
  // its executors returned measurement counts. Classical-only fallbacks store
  // no counts, so the quantum KPI is honestly blanked for those runs.
  const quantumRan = result.measurementCounts.length > 0

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <KPI label="Selected locations" value={String(result.selectedLocations.length)} accent="text-emerald-300" />
      <KPI label="Objective value" value={formatScore(result.objectiveValue)} accent="text-emerald-300" hint="Weighted utility captured by the decoded selection." />
      <KPI
        label="Constraint violations"
        value={String(violations)}
        accent={violations > 0 ? 'text-critical-400' : 'text-emerald-300'}
      />
      <KPI label="Runtime" value={formatDuration(result.executionTimeMs)} />
      <KPI
        label="Quantum objective"
        value={formatScore(quantumRan ? result.objectiveValue : null)}
        hint={
          quantumRan
            ? 'Objective returned by the quantum path.'
            : 'Classical-only job — no quantum execution produced this result, so no quantum objective is recorded.'
        }
      />
      <KPI label="Classical objective" value={formatScore(classical.objectiveValue)} hint={`Reference solver: ${classical.method || '—'}`} />
      <KPI
        label="Approximation quality"
        value={approximation === null ? '—' : formatScore(approximation)}
        accent="text-ai-300"
        hint="Stored min(1, quantum ÷ classical) quality score. Not a speedup claim."
      />
      <KPI label="Classical runtime" value={formatDuration(classical.executionTimeMs)} />
      <KPI
        label="Solution bitstring"
        value={result.bitstring || '—'}
        accent="text-ai-300"
        hint={result.bitstring ? `Decoded solution bitstring: ${result.bitstring}` : 'No bitstring was recorded for this job.'}
      />
      <KPI label="Qubits" value={String(result.qubits)} hint="Qubits configured for the job." />
    </div>
  )
}
