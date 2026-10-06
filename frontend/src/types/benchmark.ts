/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum vs Classical benchmark contract — a verbatim mirror of the backend
 * document served by `[GET|POST] /api/optimization/:id/benchmark` and the rows
 * served by `GET /api/optimization/benchmarks` / `GET /api/benchmarks`.
 *
 * Every value is a **stored measurement**; the UI only formats and explains it.
 * Field names mirror the backend contract so nothing is re-derived or invented
 * here. A classical-only fallback run is marked through `quantum.missingReason`
 * (`CLASSICAL_ONLY_RUN`) — never as a quantum measurement.
 */

import type {
  ConstraintViolation,
  CoverageRequirement,
  FallbackPolicy,
  ObjectiveWeights,
  OptimizationProblemType,
  QuantumExecutionMode,
  QuantumJobStatus,
  QuantumRunBackend,
} from './optimization'

export type BenchmarkObjectiveDirection = 'maximize'

export type ApproximationBasis = 'exact_optimal' | 'greedy_reference'

/**
 * Direction-aware approximation ratio — never a blind division. `value` is the
 * ratio or null; `invalidReason` explains why a null ratio is null.
 */
export interface ApproximationRatioInfo {
  value: number | null
  basis: ApproximationBasis | null
  direction: BenchmarkObjectiveDirection
  /** False when the quantum solution violated constraints (ratio is to an infeasible outcome). */
  feasible: boolean
  invalidReason: string | null
  note: string
}

export interface BenchmarkProblemBlock {
  type: OptimizationProblemType
  size: {
    candidates: number
    variables: number | null
    selected: number
    constraints: number
  }
}

export interface BenchmarkClassicalBlock {
  solver: string
  method: string
  /** True only when the reference is the brute-force optimum (ground truth). */
  optimal: boolean
  objectiveValue: number | null
  runtimeMs: number | null
  selectedCount: number | null
  gapVsQuantum: number | null
  missingReason: string | null
}

export interface BenchmarkQuantumBlock {
  algorithm: string
  objectiveValue: number | null
  /** Executor wall time (`quantum_results.runtime_ms`), never the pipeline total. */
  runtimeMs: number | null
  runtimeSource: string | null
  pipelineRuntimeMs: number | null
  backend: QuantumRunBackend
  executionMode: QuantumExecutionMode | 'classical'
  simulated: boolean | null
  qubits: number | null
  shots: number
  layers: number
  bitstring: string | null
  missingReason: string | null
}

export interface BenchmarkQaoaBlock {
  layers: number
  shots: number
  backend: string
  angles: number[] | null
  anglesNote: string
}

export interface BenchmarkReproducibility {
  /** Deterministic seed actually passed to the QAOA driver (see seedNote). */
  seed: number
  seedNote: string
  qaoa: BenchmarkQaoaBlock
  problem: {
    type: OptimizationProblemType
    candidateCount: number
    maxSensors: number
    budgetK: number | null
    weights: ObjectiveWeights
    normalizeWeights: boolean
    coverageRequirements: CoverageRequirement[]
    forecastReference: string
    candidateReference: string | null
    variablesCount: number | null
  }
  solver: {
    fallbackPolicy: FallbackPolicy
    fallbackApplied: boolean
    fallbackReason: string | null
    classicalSolver: string
  }
}

/** The full benchmark document returned by `[GET|POST] /api/optimization/:id/benchmark`. */
export interface BenchmarkDocument {
  jobId: string
  status: QuantumJobStatus
  problem: BenchmarkProblemBlock
  classical: BenchmarkClassicalBlock
  quantum: BenchmarkQuantumBlock
  constraintViolations: ConstraintViolation[]
  validation: { status: 'valid' | 'invalid' | null; summary: string | null }
  approximationRatio: ApproximationRatioInfo
  reproducibility: BenchmarkReproducibility
  completedAt: string | null
  quantumAdvantageClaimed: false
  disclaimer: string
}

/** Aggregated row returned by `GET /api/benchmarks` (summary — not the full document). */
export interface BenchmarkListEntry {
  jobId: string
  problemType: OptimizationProblemType
  algorithm: string
  executionMode: QuantumExecutionMode | 'classical'
  backend: QuantumRunBackend
  status: QuantumJobStatus
  createdAt: string
  completedAt: string | null
  classical: { solver: string; optimal: boolean; objectiveValue: number | null; runtimeMs: number | null }
  quantum: { objectiveValue: number | null; runtimeMs: number | null }
  approximationRatio: { value: number | null; basis: ApproximationBasis | null; invalidReason: string | null }
  constraintViolationCount: number | null
  validated: boolean | null
}