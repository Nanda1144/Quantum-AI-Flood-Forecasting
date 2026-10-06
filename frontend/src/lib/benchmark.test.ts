/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests pin the honest-benchmark rules: equal outcomes are
 * reported as equal, a worse QAOA objective is reported as worse, constraint
 * violations mark the result invalid for comparison, a classical-only fallback
 * is never presented as a quantum measurement, the stored seed / basis / ratio
 * are surfaced verbatim, and the exported report always carries
 * `quantumAdvantageClaimed: false`.
 */

import { describe, expect, it } from 'vitest'
import type { BenchmarkDocument, BenchmarkQaoaBlock, BenchmarkReproducibility } from '../types/benchmark'
import {
  benchmarkRows,
  benchmarkSummaryStats,
  buildBenchmarkCsv,
  buildBenchmarkReport,
  EPS,
  interpretBenchmark,
  isClassicalOnly,
  isCompleteRun,
  quantumRuntimeLabel,
  quantumRuntimeMs,
} from './benchmark'

function qaoaBlock(overrides: Partial<BenchmarkQaoaBlock> = {}): BenchmarkQaoaBlock {
  return {
    layers: 2,
    shots: 1024,
    backend: 'aer_simulator_statevector',
    angles: null,
    anglesNote: 'The executor does not expose variational |θ⟩ angles.',
    ...overrides,
  }
}

function reproducibility(overrides: Partial<BenchmarkReproducibility> = {}): BenchmarkReproducibility {
  return {
    seed: 424_242,
    seedNote: 'Stored write-once seed (FNV-1a of jobId + reference + candidate count).',
    qaoa: qaoaBlock(),
    problem: {
      type: 'sensor_placement',
      candidateCount: 4,
      maxSensors: 2,
      budgetK: null,
      weights: {
        risk: 0.3,
        populationCoverage: 0.2,
        infrastructureCoverage: 0.15,
        communication: 0.1,
        cost: 0.15,
        redundancy: 0.1,
      },
      normalizeWeights: true,
      coverageRequirements: [],
      forecastReference: 'FC-2026-09',
      candidateReference: 'GIS-2026-09',
      variablesCount: 4,
    },
    solver: {
      fallbackPolicy: 'retry_simulator',
      fallbackApplied: false,
      fallbackReason: null,
      classicalSolver: 'exhaustive',
    },
    ...overrides,
  }
}

function document(overrides: Partial<BenchmarkDocument> = {}): BenchmarkDocument {
  const base: BenchmarkDocument = {
    jobId: 'QOP-BENCH-001',
    status: 'completed',
    problem: {
      type: 'sensor_placement',
      size: { candidates: 4, variables: 4, selected: 2, constraints: 5 },
    },
    classical: {
      solver: 'exhaustive',
      method: 'exhaustive',
      optimal: true,
      objectiveValue: 0.6,
      runtimeMs: 200,
      selectedCount: 2,
      gapVsQuantum: null,
      missingReason: null,
    },
    quantum: {
      algorithm: 'QAOA',
      objectiveValue: 0.8,
      runtimeMs: 150,
      runtimeSource: 'quantum_results.runtime_ms',
      pipelineRuntimeMs: 400,
      backend: 'aer_simulator_statevector',
      executionMode: 'aer',
      simulated: true,
      qubits: 4,
      shots: 1024,
      layers: 2,
      bitstring: '1010',
      missingReason: null,
    },
    constraintViolations: [],
    validation: { status: 'valid', summary: 'All constraints satisfied' },
    approximationRatio: {
      value: 1.3333,
      basis: 'exact_optimal',
      direction: 'maximize',
      feasible: true,
      invalidReason: null,
      note: 'Ratio = quantum/optimal under MAXIMISATION.',
    },
    reproducibility: reproducibility(),
    completedAt: '2026-09-22T10:00:00.000Z',
    quantumAdvantageClaimed: false,
    disclaimer: 'No quantum speedup is claimed.',
  }
  return {
    ...base,
    ...overrides,
    problem: overrides.problem ?? base.problem,
    classical: { ...base.classical, ...overrides.classical },
    quantum: { ...base.quantum, ...overrides.quantum },
    constraintViolations: overrides.constraintViolations ?? base.constraintViolations,
    validation: { ...base.validation, ...overrides.validation },
    approximationRatio: { ...base.approximationRatio, ...overrides.approximationRatio },
    reproducibility: overrides.reproducibility ?? base.reproducibility,
  }
}

describe('isCompleteRun / isClassicalOnly', () => {
  it('considers only completed runs with a stored completion time complete', () => {
    expect(isCompleteRun(document())).toBe(true)
    expect(isCompleteRun(document({ status: 'running', completedAt: null }))).toBe(false)
    expect(isCompleteRun(document({ status: 'completed', completedAt: null }))).toBe(false)
  })

  it('flags a classical-only fallback from the stored missingReason and backend', () => {
    expect(isClassicalOnly(document())).toBe(false)
    expect(
      isClassicalOnly(document({ quantum: { ...document().quantum, backend: 'classical', executionMode: 'classical', missingReason: 'CLASSICAL_ONLY_RUN' } })),
    ).toBe(true)
  })
})

describe('runtime helpers', () => {
  it('prefers the persisted executor runtime over the pipeline total', () => {
    const measured = document()
    expect(quantumRuntimeMs(measured)).toBe(150)
    expect(quantumRuntimeLabel(measured)).toBe('150 ms')
  })

  it('falls back to the pipeline total and labels it honestly when executor runtime is absent', () => {
    const pipelineOnly = document({ quantum: { ...document().quantum, runtimeMs: null, runtimeSource: null } })
    expect(quantumRuntimeMs(pipelineOnly)).toBe(400)
    const label = quantumRuntimeLabel(pipelineOnly)
    expect(label).toContain('pipeline')
  })
})

describe('benchmarkSummaryStats', () => {
  it('formats the stored objective and runtime values without inventing numbers', () => {
    const stats = benchmarkSummaryStats(document())
    expect(stats.quantumObjective).toBe('80.00%')
    expect(stats.classicalObjective).toBe('60.00%')
    expect(stats.quantumRuntime).toContain('150')
    expect(stats.constraintViolations).toBe('0')
  })

  it('marks a run with violations invalid in the summary', () => {
    const violator = document({ constraintViolations: [{ code: 'COV-01', message: 'Coverage below requirement' }] })
    const stats = benchmarkSummaryStats(violator)
    expect(stats.constraintViolations).toBe('1 (invalid)')
  })
})

describe('interpretBenchmark verdicts (honest, never a speedup claim)', () => {
  it('quantum_better — QAOA exceeded the reference', () => {
    const insight = interpretBenchmark(document())
    expect(insight.verdict).toBe('quantum_better')
    expect(insight.headline).toContain('exceeded')
    expect(insight.lines.some((line) => line.includes('No universal quantum advantage is claimed'))).toBe(true)
  })

  it('equal — equal objectives are reported as equal, within EPS', () => {
    const tie = document({
      classical: { ...document().classical, objectiveValue: 0.8 },
      approximationRatio: { ...document().approximationRatio, value: 1 },
    })
    const insight = interpretBenchmark(tie)
    expect(insight.verdict).toBe('equal')
    expect(insight.headline).toContain('matched')
    const withinEps = document({
      classical: { ...document().classical, objectiveValue: 0.8 },
      quantum: { ...document().quantum, objectiveValue: 0.8 - EPS / 2 },
      approximationRatio: { ...document().approximationRatio, value: 1 },
    })
    expect(interpretBenchmark(withinEps).verdict).toBe('equal')
  })

  it('classical_better — a lower QAOA objective is reported as worse', () => {
    const worse = document({ classical: { ...document().classical, objectiveValue: 0.9 } })
    const insight = interpretBenchmark(worse)
    expect(insight.verdict).toBe('classical_better')
    expect(insight.headline).toContain('lower objective')
  })

  it('invalid — constraint violations mark the outcome invalid for comparison', () => {
    const violator = document({
      constraintViolations: [{ code: 'COV-01', message: 'Coverage below requirement' }],
      validation: { status: 'invalid', summary: null },
    })
    const insight = interpretBenchmark(violator)
    expect(insight.verdict).toBe('invalid')
    expect(insight.lines.some((line) => line.includes('Coverage below requirement'))).toBe(true)
    expect(insight.lines.some((line) => line.toLowerCase().includes('not a valid benchmark'))).toBe(true)
  })

  it('no_quantum — a classical-only fallback is never presented as a quantum result', () => {
    const fallback = document({
      quantum: {
        ...document().quantum,
        objectiveValue: null,
        runtimeMs: null,
        backend: 'classical',
        executionMode: 'classical',
        missingReason: 'CLASSICAL_ONLY_RUN',
      },
      reproducibility: reproducibility({ solver: { fallbackPolicy: 'classical_only', fallbackApplied: true, fallbackReason: 'Hardware unavailable', classicalSolver: 'exhaustive' } }),
    })
    const insight = interpretBenchmark(fallback)
    expect(insight.verdict).toBe('no_quantum')
    expect(insight.headline).toContain('No quantum measurement')
  })

  it('no_result — a non-completed job has no comparison', () => {
    const running = document({ status: 'queued', completedAt: null })
    const insight = interpretBenchmark(running)
    expect(insight.verdict).toBe('no_result')
    expect(insight.headline).toContain('No completed result')
  })

  it('no_result — missing objectives yield an honest configuration error, using the stored invalid reason', () => {
    const unmeasurable = document({
      quantum: { ...document().quantum, objectiveValue: null },
      approximationRatio: { ...document().approximationRatio, value: null, invalidReason: 'MISSING_QUANTUM_OBJECTIVE' },
    })
    const insight = interpretBenchmark(unmeasurable)
    expect(insight.verdict).toBe('no_result')
    expect(insight.headline).toContain('cannot be computed')
    expect(insight.lines.some((line) => line.includes('MISSING_QUANTUM_OBJECTIVE'))).toBe(true)
  })

  it('calls out a longer recorded QAOA wall time without claiming a speedup', () => {
    const slow = document({ classical: { ...document().classical, runtimeMs: 100 } })
    const insight = interpretBenchmark(slow)
    expect(insight.lines.some((line) => line.toLowerCase().includes('longer'))).toBe(true)
  })
})

describe('benchmarkRows', () => {
  it('renders the seven comparison rows with the stored seed and ratio surfaced verbatim', () => {
    const rows = benchmarkRows(document())
    expect(rows).toHaveLength(7)
    const ratioRow = rows.find((row) => row.metric === 'Approximation ratio')!
    expect(ratioRow.qaoa).toBe('1.333')
    expect(ratioRow.classical).toBe('1.000')
    const reproducibilityRow = rows.find((row) => row.metric === 'Reproducibility')!
    expect(reproducibilityRow.qaoa).toContain('seed 424242')
    const runtimeRow = rows.find((row) => row.metric === 'Runtime')!
    expect(runtimeRow.qaoa).toContain('150 ms')
  })

  it('the QAOA objective cell is a dash and a note when the run was classical-only', () => {
    const fallback = document({
      quantum: {
        ...document().quantum,
        objectiveValue: null,
        runtimeMs: null,
        pipelineRuntimeMs: null,
        backend: 'classical',
        executionMode: 'classical',
        missingReason: 'CLASSICAL_ONLY_RUN',
      },
    })
    const objectiveRow = benchmarkRows(fallback).find((row) => row.metric === 'Objective value')!
    expect(objectiveRow.qaoa).toBe('—')
    expect(objectiveRow.note).toContain('no quantum measurement')
  })
})

describe('exports (report + CSV)', () => {
  it('the report embeds the document verbatim and never claims an advantage', () => {
    const report = buildBenchmarkReport(document())
    expect(report.report).toBe('quantum-vs-classical-benchmark')
    expect(report.quantumAdvantageClaimed).toBe(false)
    expect(report.document.jobId).toBe('QOP-BENCH-001')
    expect(report.document.approximationRatio.value).toBe(1.3333)
  })

  it('the CSV exposes the seed, basis, verdict and metric table', () => {
    const csv = buildBenchmarkCsv(document())
    expect(csv).toContain('QOP-BENCH-001')
    expect(csv).toContain('424242')
    expect(csv).toContain('exact_optimal')
    expect(csv).toContain('1.3333')
    expect(csv).toContain('quantum_better')
    expect(csv).toContain('Objective value')
  })
})