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
 * Every number here comes verbatim from the gateway's benchmark document
 * (types/benchmark.ts), which the backend assembles from STORED measurements:
 * objective, runtime, constraint violations, approximation ratio (with its
 * basis and invalid reason) and the experiment configuration (incl. the
 * persisted QAOA seed). Nothing is recomputed or invented here — the ratio is
 * the stored ratio, the seed is the stored seed, and a classical-only fallback
 * run is surfaced through `quantum.missingReason = 'CLASSICAL_ONLY_RUN'`.
 *
 * The verdict never claims a universal speedup: it reports how this one
 * experiment compares against its persisted classical reference, and it marks
 * invalid / fallback runs so they are never presented as evidence of quantum
 * advantage.
 */

import type { ApproximationRatioInfo, BenchmarkDocument, BenchmarkListEntry } from '../types/benchmark'
import { formatDuration } from './format'

export type BenchmarkVerdict =
  | 'no_result' // job not completed or no measurable outcome
  | 'no_quantum' // the quantum path did not run (classical-only fallback)
  | 'invalid' // constraints violated — the outcome is not a comparable solution
  | 'quantum_better' // QAOA objective > classical reference objective
  | 'equal' // QAOA objective ≈ classical reference objective
  | 'classical_better' // QAOA objective < classical reference objective

export interface BenchmarkInterpretation {
  verdict: BenchmarkVerdict
  headline: string
  tone: 'emerald' | 'amber' | 'forest' | 'critical'
  lines: string[]
}

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

export const EPS = 1e-6

/** A benchmark document on which a comparison can be rendered. */
export function isCompleteRun(document: BenchmarkDocument): boolean {
  return document.status === 'completed' && document.completedAt !== null
}

/**
 * True when the run produced no real quantum measurement (classical-only
 * fallback). The backend marks this on the measured document — never inferred
 * from UI labels.
 */
export function isClassicalOnly(document: BenchmarkDocument): boolean {
  return (
    document.quantum.missingReason === 'CLASSICAL_ONLY_RUN' ||
    document.quantum.backend === 'classical' ||
    document.quantum.executionMode === 'classical'
  )
}

/**
 * Wall time of the quantum path as recorded by the gateway: the executor's own
 * runtime when it was persisted, otherwise the run's pipeline total (which
 * includes the reference solve — labelled separately in the UI).
 */
export function quantumRuntimeMs(document: BenchmarkDocument): number | null {
  return document.quantum.runtimeMs ?? document.quantum.pipelineRuntimeMs
}

/** Label for the quantum-path wall time. Labels executor vs pipeline honestly. */
export function quantumRuntimeLabel(document: BenchmarkDocument): string {
  if (document.quantum.runtimeMs !== null) return formatDuration(document.quantum.runtimeMs)
  if (document.quantum.pipelineRuntimeMs !== null) return `≈ ${formatDuration(document.quantum.pipelineRuntimeMs)} (pipeline)`
  return '—'
}

/**
 * The stored approximation ratio — returned verbatim (basis, feasibility and
 * invalid reason included). Never recomputed client-side.
 */
export function approximationRatio(document: BenchmarkDocument): ApproximationRatioInfo {
  return document.approximationRatio
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
export function benchmarkSummaryStats(document: BenchmarkDocument): BenchmarkSummaryStats {
  const validated = document.constraintViolations.length === 0
  return {
    problemSize: `${document.problem.size.variables ?? document.problem.size.candidates} variables`,
    classicalSolver: document.classical.method || '—',
    quantumAlgorithm: document.quantum.algorithm || 'QAOA',
    classicalObjective: percent(document.classical.objectiveValue),
    quantumObjective: percent(document.quantum.objectiveValue),
    classicalRuntime: formatDuration(document.classical.runtimeMs ?? undefined),
    quantumRuntime: quantumRuntimeLabel(document),
    constraintViolations: validated ? '0' : `${document.constraintViolations.length} (invalid)`,
  }
}

/** The seven-metric comparison table (Metric | Classical | QAOA). */
export function benchmarkRows(document: BenchmarkDocument): BenchmarkMetricRow[] {
  const ratio = document.approximationRatio
  const feasible = document.constraintViolations.length === 0
  const problemSize = document.problem.size.variables ?? document.problem.size.candidates
  const qaoaObjective = isClassicalOnly(document) ? null : document.quantum.objectiveValue

  return [
    {
      metric: 'Objective value',
      classical: percent(document.classical.objectiveValue),
      qaoa: percent(qaoaObjective ?? document.quantum.objectiveValue),
      note: isClassicalOnly(document)
        ? "This run produced no quantum measurement — the QAOA cell shows the classical reference's stored value for completeness only."
        : 'Fraction of the weighted utility captured by each solver (higher is better).',
    },
    {
      metric: 'Runtime',
      classical: formatDuration(document.classical.runtimeMs ?? undefined),
      qaoa: quantumRuntimeLabel(document),
      note: document.quantum.runtimeMs !== null
        ? `Executor wall time (${document.quantum.runtimeSource ?? 'quantum_results.runtime_ms'}). QoS is not a like-for-like speedup comparison.`
        : 'No executor runtime was persisted; the QAOA cell shows the run’s pipeline total (includes the reference solve). Not a speedup comparison.',
    },
    {
      metric: 'Constraint violations',
      classical: '—',
      qaoa: String(document.constraintViolations.length),
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
      qaoa: ratio.value !== null ? number(ratio.value) : '—',
      note: ratio.note,
    },
    {
      metric: 'Reproducibility',
      classical: `Deterministic (${document.classical.method})`,
      qaoa: `Shot-sampled (${document.quantum.shots}) · seed ${document.reproducibility.seed}`,
      note: document.reproducibility.seedNote,
    },
    {
      metric: 'Problem size',
      classical: `${problemSize} variables`,
      qaoa: `${document.quantum.qubits ?? problemSize} qubits`,
      note: 'Both solvers ran the identical instance — the size is shared.',
    },
  ]
}

/**
 * Verdict + factual narrative. Rules (pledge): never claim a universal quantum
 * advantage; equal → say equal; worse → say worse; runtime worse → say so;
 * constraint violations → mark the result invalid for comparison; a
 * classical-only fallback run is never presented as a quantum measurement.
 */
export function interpretBenchmark(document: BenchmarkDocument): BenchmarkInterpretation {
  if (!isCompleteRun(document)) {
    return {
      verdict: 'no_result',
      headline: 'No completed result to compare',
      tone: 'forest',
      lines: [
        `This job is '${document.status}' — the gateway has no completed benchmark document for it. The comparison appears once the run reaches a terminal state.`,
      ],
    }
  }

  if (isClassicalOnly(document)) {
    return {
      verdict: 'no_quantum',
      headline: 'No quantum measurement — classical-only outcome',
      tone: 'amber',
      lines: [
        `This run's outcome is the stored classical reference (${document.classical.method}). The quantum path did not run${
          document.reproducibility.solver.fallbackReason ? `: ${document.reproducibility.solver.fallbackReason}` : ''
        }, so there is no QAOA objective to compare.`,
        `Fallback policy: ${document.reproducibility.solver.fallbackPolicy}.`,
      ],
    }
  }

  if (document.constraintViolations.length > 0 || document.validation.status === 'invalid') {
    return {
      verdict: 'invalid',
      headline: 'Constraints violated — result marked invalid',
      tone: 'critical',
      lines: [
        `The QAOA decode reported ${document.constraintViolations.length} constraint violation(s): ${
          document.validation.summary ||
          document.constraintViolations.map((violation) => violation.message).join('; ') ||
          'no detail recorded'
        }.`,
        `An infeasible solution is not directly comparable to the feasible classical reference (${document.classical.method}). The objective and ratio below are shown for transparency only — this is not a valid benchmark.`,
      ],
    }
  }

  if (document.quantum.objectiveValue === null || document.classical.objectiveValue === null) {
    return {
      verdict: 'no_result',
      headline: 'Benchmark cannot be computed for this configuration',
      tone: 'forest',
      lines: [
        document.approximationRatio.invalidReason
          ? `The gateway recorded no comparable objective: ${document.approximationRatio.invalidReason}.`
          : 'The gateway recorded neither a quantum nor a classical objective for this run.',
        document.approximationRatio.note,
      ],
    }
  }

  const diff = document.quantum.objectiveValue - document.classical.objectiveValue
  const ratio = document.approximationRatio.value
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
    `QAOA achieved ${percent(document.quantum.objectiveValue)} against the classical reference's ${percent(document.classical.objectiveValue)}${
      deltaPct !== null ? ` (≈ ${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%)` : ''
    }. ` +
      `${verdict === 'equal' ? 'The two solvers reached the same objective under this experiment.' : 'This is one experiment on this instance and backend — no universal quantum advantage is claimed.'}` +
      (document.approximationRatio.basis === 'greedy_reference'
        ? ' The reference is the heuristic (greedy) solver, so the ratio records how QAOA fared against that heuristic — not a claim of optimality.'
        : ''),
  )

  const qaoaMs = quantumRuntimeMs(document)
  if (qaoaMs !== null && document.classical.runtimeMs !== null) {
    if (qaoaMs > document.classical.runtimeMs * 1.05) {
      lines.push(
        document.quantum.runtimeMs !== null
          ? `Quantum executor wall time was longer than the reference solve: QAOA ${formatDuration(qaoaMs)} vs classical ${formatDuration(document.classical.runtimeMs)}.`
          : `The package's pipeline wall time was longer than the reference solve: QAOA path ${formatDuration(qaoaMs)} vs classical ${formatDuration(document.classical.runtimeMs)}. No speedup is claimed.`,
      )
    } else if (qaoaMs < document.classical.runtimeMs * 0.95) {
      lines.push(
        `Recorded wall time: QAOA ${formatDuration(qaoaMs)} vs classical ${formatDuration(document.classical.runtimeMs)}. ` +
          `These are single-run measurements on different implementations — no speedup is claimed.`,
      )
    } else {
      lines.push(
        `Comparable recorded wall time: QAOA ${formatDuration(qaoaMs)} vs classical ${formatDuration(document.classical.runtimeMs)}.`,
      )
    }
  } else {
    lines.push(
      `Recorded wall times: QAOA ${formatDuration(qaoaMs ?? undefined)} vs classical ${formatDuration(document.classical.runtimeMs ?? undefined)}. No speedup is claimed.`,
    )
  }

  lines.push(
    `Comparison is against the persisted classical reference (${document.classical.method}) for this exact experiment. No universal quantum advantage is claimed.`,
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
  /** The stored benchmark document, verbatim (seed, basis, ratio, measurements). */
  document: BenchmarkDocument
  interpretation: BenchmarkInterpretation
  quantumAdvantageClaimed: false
  benchmarkDisclaimer: string
}

export function buildBenchmarkReport(document: BenchmarkDocument): BenchmarkReport {
  return {
    report: 'quantum-vs-classical-benchmark',
    version: 1,
    exportedAt: new Date().toISOString(),
    document,
    interpretation: interpretBenchmark(document),
    quantumAdvantageClaimed: false,
    benchmarkDisclaimer:
      'No quantum speedup is claimed. The quantum path and a classical reference solver both ran the identical instance; this report is one experiment, not a general benchmark.',
  }
}

function csvCell(value: string | number | boolean | null): string {
  const text = value === null || value === undefined ? '' : String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

export function buildBenchmarkCsv(document: BenchmarkDocument): string {
  const report = buildBenchmarkReport(document)
  const rows: string[] = []
  rows.push(csvCell('report'), csvCell(report.report))
  rows.push(csvCell('exportedAt'), csvCell(report.exportedAt))
  rows.push(csvCell('jobId'), csvCell(document.jobId))
  rows.push(csvCell('status'), csvCell(document.status))
  rows.push(csvCell('problemType'), csvCell(document.problem.type))
  rows.push(csvCell('algorithm'), csvCell(document.quantum.algorithm))
  rows.push(csvCell('classicalSolver'), csvCell(document.classical.method))
  rows.push(csvCell('referenceOptimal'), csvCell(document.classical.optimal))
  rows.push(csvCell('approximationBasis'), csvCell(document.approximationRatio.basis ?? ''))
  rows.push(csvCell('approximationRatio'), csvCell(document.approximationRatio.value ?? document.approximationRatio.invalidReason ?? ''))
  rows.push(csvCell('seed'), csvCell(document.reproducibility.seed))
  rows.push(csvCell('layers'), csvCell(document.quantum.layers))
  rows.push(csvCell('shots'), csvCell(document.quantum.shots))
  rows.push(csvCell('backend'), csvCell(document.quantum.backend))
  rows.push(csvCell('executionMode'), csvCell(document.quantum.executionMode))
  rows.push(csvCell('simulated'), csvCell(document.quantum.simulated))
  rows.push(csvCell('fallbackApplied'), csvCell(document.reproducibility.solver.fallbackApplied))
  rows.push(csvCell('fallbackReason'), csvCell(document.reproducibility.solver.fallbackReason ?? ''))
  rows.push(csvCell('classicalObjective'), csvCell(document.classical.objectiveValue ?? ''))
  rows.push(csvCell('quantumObjective'), csvCell(document.quantum.objectiveValue ?? ''))
  rows.push(csvCell('constraintViolationCount'), csvCell(document.constraintViolations.length))
  rows.push(csvCell('validated'), csvCell(document.validation.status))
  rows.push(csvCell('verdict'), csvCell(report.interpretation.verdict))
  rows.push(csvCell('headline'), csvCell(report.interpretation.headline))
  rows.push('')
  rows.push(csvCell('metric'), csvCell('classical'), csvCell('qaoa'))
  for (const row of benchmarkRows(document)) {
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

export function isLedgerEntryComplete(entry: BenchmarkListEntry): boolean {
  return entry.status === 'completed' && entry.completedAt !== null
}