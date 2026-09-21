/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum vs Classical benchmark reasoning — pure, shared by the page, the
 * summary cards, the metric table, the interpretation panel and the exports.
 *
 * Every number here comes verbatim from `OptimizationResult.classicalComparison`
 * and the job's stored `resultSummary`; nothing is invented. The verdict never
 * claims a universal speedup — it only reports how this one experiment compares
 * against the persisted classical reference, and it marks invalid / fallback
 * runs so they are never presented as evidence of quantum advantage.
 */

import type { OptimizationResult, QuantumJobSummary } from '../types/optimization'
import { formatDuration } from './format'

export type BenchmarkVerdict =
  | 'no_result' // job not completed or no result document
  | 'no_quantum' // the quantum path did not run (classical-only fallback)
  | 'invalid' // constraints violated — the outcome is not a comparable solution
  | 'quantum_better' // QAOA objective > classical reference objective
  | 'equal' // QAOA objective ≈ classical reference objective
  | 'classical_better' // QAOA objective < classical reference objective

export interface BenchmarkMetricRow {
  metric: string
  classical: string
  qaoa: string
  note?: string
}

export interface BenchmarkSummaryStats {
  problemSize: string
  classicalSolver: string
  quantumAlgorithm: string
  classicalObjective: string
  quantumObjective: string
  classicalRuntime: string
  quantumRuntime: string
  constraintViolations: string
}

export interface BenchmarkInterpretation {
  verdict: BenchmarkVerdict
  headline: string
  tone: 'emerald' | 'amber' | 'forest' | 'critical'
  lines: string[]
}

export const EPS = 1e-6

/** A run the benchmark page may render: completed with a stored result. */
export function isCompleteRun(summary: QuantumJobSummary): boolean {
  return summary.status === 'completed' && summary.resultSummary.objectiveValue !== null
}

/** True when the job produced no real quantum measurement (classical fallback). */
export function isClassicalOnly(summary: QuantumJobSummary): boolean {
  return summary.backendUsed === 'classical' || summary.executionModeUsed === 'classical'
}

function percent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function number(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

/** The eight summary cards the page header renders. */
export function benchmarkSummaryStats(summary: QuantumJobSummary, result: OptimizationResult): BenchmarkSummaryStats {
  const classical = result.classicalComparison
  const validated = result.constraintViolations.length === 0
  return {
    problemSize: summary.variablesCount !== null && summary.variablesCount !== undefined
      ? `${summary.variablesCount} variables`
      : `${result.qubits} qubits`,
    classicalSolver: classical.method || '—',
    quantumAlgorithm: summary.algorithm || 'QAOA',
    classicalObjective: percent(classical.objectiveValue),
    quantumObjective: percent(result.objectiveValue),
    classicalRuntime: formatDuration(classical.executionTimeMs),
    quantumRuntime: formatDuration(result.executionTimeMs),
    constraintViolations: validated
      ? '0'
      : `${result.constraintViolations.length} (invalid)`,
  }
}

/** Approximation ratio vs the classical reference: QAOA/classical, ≤1 means at or below the reference. */
export function approximationRatio(result: OptimizationResult): number | null {
  const classical = result.classicalComparison.objectiveValue
  if (!Number.isFinite(classical) || classical <= EPS) return null
  return result.objectiveValue / classical
}

/** The seven-metric comparison table (Metric | Classical | QAOA). */
export function benchmarkRows(summary: QuantumJobSummary, result: OptimizationResult): BenchmarkMetricRow[] {
  const classical = result.classicalComparison
  const ratio = approximationRatio(result)
  const feasible = result.constraintViolations.length === 0
  const problemSize = summary.variablesCount ?? result.qubits

  return [
    {
      metric: 'Objective value',
      classical: percent(classical.objectiveValue),
      qaoa: percent(result.objectiveValue),
      note: 'Fraction of the weighted utility captured by each solver (higher is better).',
    },
    {
      metric: 'Runtime',
      classical: formatDuration(classical.executionTimeMs),
      qaoa: formatDuration(result.executionTimeMs),
      note: 'Stored wall time. QAOA and the reference run on different implementations — not a like-for-like speedup comparison.',
    },
    {
      metric: 'Constraint violations',
      classical: '—',
      qaoa: String(result.constraintViolations.length),
      note: 'The reference solver outcome is feasible by construction; the gateway records violations only for the QAOA decode.',
    },
    {
      metric: 'Solution quality',
      classical: 'Reference (feasible)',
      qaoa: feasible ? 'Valid' : 'Invalid',
      note: feasible ? undefined : 'An invalid QAOA outcome is not a comparable solution — see the interpretation panel.',
    },
    {
      metric: 'Approximation ratio',
      classical: '1.000',
      qaoa: ratio !== null ? number(ratio) : '—',
      note: 'QAOA objective ÷ classical objective. Below 1.000 the reference found a better solution; it never implies a general speedup.',
    },
    {
      metric: 'Reproducibility',
      classical: `Deterministic (${classical.method})`,
      qaoa: `Shot-sampled (${result.shots} shots) · seed not recorded`,
      note: 'QAOA outcomes are measurement samples; the gateway does not persist the RNG seed.',
    },
    {
      metric: 'Problem size',
      classical: `${problemSize} variables`,
      qaoa: `${problemSize} qubits`,
      note: 'Both solvers ran the identical instance — the size is shared.',
    },
  ]
}

/**
 * Verdict + factual narrative. Rules (pledge): never claim a universal quantum
 * advantage; equal → say equal; worse → say worse; runtime worse → say so;
 * constraint violations → mark the result invalid for comparison.
 */
export function interpretBenchmark(summary: QuantumJobSummary, result: OptimizationResult): BenchmarkInterpretation {
  const classical = result.classicalComparison

  if (!isCompleteRun(summary)) {
    return {
      verdict: 'no_result',
      headline: 'No completed result to compare',
      tone: 'forest',
      lines: [
        `This job is '${summary.status}' — there is no stored result document yet. The comparison appears once the run reaches a terminal state.`,
      ],
    }
  }

  if (isClassicalOnly(summary)) {
    return {
      verdict: 'no_quantum',
      headline: 'No quantum measurement — classical-only outcome',
      tone: 'amber',
      lines: [
        `This run's outcome is the stored classical reference (${classical.method}). The quantum path did not complete${
          summary.fallbackReason ? `: ${summary.fallbackReason}` : ''
        }, so there is no QAOA objective to compare.`,
        `Fallback policy: ${summary.fallbackPolicy}.`,
      ],
    }
  }

  if (result.constraintViolations.length > 0 || result.validationStatus === 'invalid') {
    return {
      verdict: 'invalid',
      headline: 'Constraints violated — result marked invalid',
      tone: 'critical',
      lines: [
        `The QAOA decode reported ${result.constraintViolations.length} constraint violation(s): ${result.validationSummary || result.constraintViolations.map((v) => v.message).join('; ') || 'no detail recorded'}.`,
        `An infeasible solution is not directly comparable to the feasible classical reference (${classical.method}). The objective and ratio below are shown for transparency only — this is not a valid benchmark.`,
      ],
    }
  }

  const diff = result.objectiveValue - classical.objectiveValue
  const ratio = approximationRatio(result)
  const deltaPct = ratio !== null ? (ratio - 1) * 100 : null

  let verdict: BenchmarkVerdict
  let headline: string
  const tone: BenchmarkInterpretation['tone'] = diff > EPS ? 'emerald' : 'forest'
  if (diff > EPS) {
    verdict = 'quantum_better'
    headline = 'QAOA exceeded the classical reference on this run'
  } else if (diff < -EPS) {
    verdict = 'classical_better'
    headline = 'QAOA achieved a lower objective than the classical reference'
  } else {
    verdict = 'equal'
    headline = 'QAOA matched the classical reference on this run'
  }

  const lines: string[] = []
  lines.push(
    `QAOA achieved ${percent(result.objectiveValue)} against the classical reference's ${percent(classical.objectiveValue)}${
      deltaPct !== null ? ` (≈ ${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%)` : ''
    }. ` +
      `${verdict === 'equal' ? 'The two solvers reached the same objective under this experiment.' : 'This is one experiment on this instance and backend — no universal quantum advantage is claimed.'}`,
  )

  if (result.executionTimeMs > classical.executionTimeMs * 1.05) {
    lines.push(
      `Wall time was longer on the quantum path: QAOA ${formatDuration(result.executionTimeMs)} vs classical ${formatDuration(classical.executionTimeMs)}.`,
    )
  } else if (result.executionTimeMs < classical.executionTimeMs * 0.95) {
    lines.push(
      `Wall time recorded: QAOA ${formatDuration(result.executionTimeMs)} vs classical ${formatDuration(classical.executionTimeMs)}. ` +
        `These are single-run measurements on different implementations — no speedup is claimed.`,
    )
  } else {
    lines.push(`Comparable wall time: QAOA ${formatDuration(result.executionTimeMs)} vs classical ${formatDuration(classical.executionTimeMs)}.`)
  }

  lines.push(
    `Comparison is against the persisted classical reference (${classical.method}) for this exact experiment. No universal quantum advantage is claimed.`,
  )
  return { verdict, headline, tone, lines }
}

/* ------------------------------------------------------------------ */
/* Exports — the researcher's JSON experiment report + CSV table        */
/* ------------------------------------------------------------------ */

export interface BenchmarkReport {
  report: 'quantum-vs-classical-benchmark'
  version: 1
  exportedAt: string
  jobId: string
  createdAt: string | null
  completedAt: string | null
  owner: string
  problemType: string
  backendUsed: string
  executionModeUsed: string
  fallbackApplied: boolean
  fallbackReason: string | null
  experimentConfiguration: {
    problemType: string
    variables: number | null
    classicalSolver: string | null
    layers: number | null
    shots: number | null
    backend: string | null
    simulated: boolean | null
    startedAt: string | null
    endedAt: string | null
    /** The gateway does not persist the RNG seed (honest null). */
    seed: null
  }
  metrics: BenchmarkMetricRow[]
  interpretation: BenchmarkInterpretation
  quantumAdvantageClaimed: false
  benchmarkDisclaimer: string
  result: OptimizationResult
}

export function buildBenchmarkReport(summary: QuantumJobSummary, result: OptimizationResult): BenchmarkReport {
  return {
    report: 'quantum-vs-classical-benchmark',
    version: 1,
    exportedAt: new Date().toISOString(),
    jobId: summary.jobId,
    createdAt: summary.createdAt,
    completedAt: summary.completedAt,
    owner: summary.owner,
    problemType: summary.problemType,
    backendUsed: summary.backendUsed,
    executionModeUsed: summary.executionModeUsed,
    fallbackApplied: summary.fallbackApplied,
    fallbackReason: summary.fallbackReason,
    experimentConfiguration: {
      problemType: summary.problemType,
      variables: summary.variablesCount ?? result.qubits ?? null,
      classicalSolver: result.classicalComparison.method,
      layers: result.layers,
      shots: result.shots,
      backend: result.backend,
      simulated: result.simulated,
      startedAt: result.startedAt,
      endedAt: result.endedAt,
      seed: null,
    },
    metrics: benchmarkRows(summary, result),
    interpretation: interpretBenchmark(summary, result),
    quantumAdvantageClaimed: false,
    benchmarkDisclaimer:
      'No quantum speedup is claimed. The quantum path and a classical reference solver both ran the identical instance; this report is one experiment, not a general benchmark.',
    result,
  }
}

function csvCell(value: string | number): string {
  const text = String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

export function buildBenchmarkCsv(summary: QuantumJobSummary, result: OptimizationResult): string {
  const report = buildBenchmarkReport(summary, result)
  const rows: string[] = []
  rows.push(csvCell('report'), csvCell(report.report))
  rows.push(csvCell('exportedAt'), csvCell(report.exportedAt))
  rows.push(csvCell('jobId'), csvCell(report.jobId))
  rows.push(csvCell('problemType'), csvCell(report.problemType))
  rows.push(csvCell('variables'), csvCell(report.experimentConfiguration.variables ?? ''))
  rows.push(csvCell('classicalSolver'), csvCell(report.experimentConfiguration.classicalSolver ?? ''))
  rows.push(csvCell('layers'), csvCell(report.experimentConfiguration.layers ?? ''))
  rows.push(csvCell('shots'), csvCell(report.experimentConfiguration.shots ?? ''))
  rows.push(csvCell('backend'), csvCell(report.experimentConfiguration.backend ?? ''))
  rows.push(csvCell('fallbackApplied'), csvCell(String(report.fallbackApplied)))
  rows.push(csvCell('verdict'), csvCell(report.interpretation.verdict))
  rows.push(csvCell('headline'), csvCell(report.interpretation.headline))
  rows.push('')
  rows.push(csvCell('metric'), csvCell('classical'), csvCell('qaoa'))
  for (const row of report.metrics) {
    rows.push(csvCell(row.metric), csvCell(row.classical), csvCell(row.qaoa))
  }
  return rows.join('\r\n')
}

/** Trigger a client-side file download from a data URI (mirrors existing pages). */
export function downloadFile(name: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}