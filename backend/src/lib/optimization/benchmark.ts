/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Benchmark document assembly (migration-free, pure).
 *
 * The benchmark is always built from STORED measurements — the pipeline ran the
 * classical reference (`classical.ts`) and persisted both outcomes with the job,
 * so nothing is re-executed or re-measured here. The document is the raw
 * experiment record; the frontend, not this module, explains the result.
 *
 * Approximation ratio rules (never a blind division):
 *   - objective direction is MAXIMISE (weighted utility — see `classical.ts`).
 *   - ratio = quantum / reference only when reference > 0 AND quantum ≥ 0;
 *     a non-positive reference makes the division mathematically meaningless.
 *   - the ratio is NOT clamped: against a heuristic (`greedy`) reference a
 *     quantum outcome may exceed 1.0, and that raw value is recorded honestly.
 *   - the basis names the reference: `exact_optimal` (brute force) or
 *     `greedy_reference` (heuristic) — the two are never conflated.
 *   - an infeasible quantum solution still records its raw ratio, but
 *     `feasible: false` and the validation block say so.
 */

import { seedFrom } from '../../services/deterministic.ts'
import type {
  ApproximationRatioInfo,
  BenchmarkClassicalBlock,
  BenchmarkDocument,
  BenchmarkListEntry,
  BenchmarkObjectiveDirection,
  BenchmarkQuantumBlock,
  BenchmarkReproducibility,
  ClassicalComparison,
  OptimizationJob,
  OptimizationResult,
} from '../../types/optimization.ts'

export const OBJECTIVE_DIRECTION: BenchmarkObjectiveDirection = 'maximize'

export interface QuantumExecutionInput {
  /** Whether the outcome came from a real quantum execution (modeUsed ≠ classical). */
  ran: boolean
  /** Executor wall time from the persistence layer, when available. */
  runtimeMs: number | null
  /** Where `runtimeMs` came from (e.g. `quantum_results.runtime_ms`). */
  runtimeSource: string | null
}

/**
 * Direction-aware approximation ratio.
 *
 * `referenceMethod` is the classical solver that produced the reference:
 * `exhaustive` → the exact optimum (basis `exact_optimal`), anything else →
 * a heuristic reference (basis `greedy_reference`).
 */
export function computeApproximationRatio(
  referenceObjective: number | null,
  quantumObjective: number | null,
  referenceMethod: string | null,
  feasible: boolean,
): ApproximationRatioInfo {
  const basis: ApproximationRatioInfo['basis'] =
    referenceMethod === 'exhaustive' ? 'exact_optimal' : referenceMethod ? 'greedy_reference' : null

  let value: number | null = null
  let invalidReason: string | null = null

  if (referenceObjective === null) {
    invalidReason = 'MISSING_CLASSICAL_REFERENCE'
  } else if (quantumObjective === null) {
    invalidReason = 'MISSING_QUANTUM_OBJECTIVE'
  } else if (referenceObjective <= 0) {
    invalidReason = 'OBJECTIVE_NOT_POSITIVE'
  } else if (quantumObjective < 0) {
    invalidReason = 'QUANTUM_OBJECTIVE_NEGATIVE'
  } else {
    value = Number((quantumObjective / referenceObjective).toFixed(4))
  }

  const note =
    invalidReason !== null
      ? ratioInvalidNote(invalidReason, basis)
      : basis === 'exact_optimal'
        ? 'Ratio = quantum/optimal under MAXIMISATION. Feasible quantum solutions cannot exceed 1.0 against the brute-force optimum.'
        : 'Ratio = quantum/greedy reference under MAXIMISATION. A value above 1.0 means the quantum outcome beat the heuristic reference — it is NOT a claim of optimality.'

  return {
    value,
    basis,
    direction: OBJECTIVE_DIRECTION,
    feasible,
    invalidReason,
    note: feasible ? note : `${note} The quantum solution violated constraints, so this ratio compares an INFEASIBLE outcome.`,
  }
}

function ratioInvalidNote(reason: string, basis: ApproximationRatioInfo['basis']): string {
  switch (reason) {
    case 'MISSING_CLASSICAL_REFERENCE':
      return 'No classical reference objective was recorded — nothing to divide by.'
    case 'MISSING_QUANTUM_OBJECTIVE':
      return 'No quantum outcome objective was recorded (the optimizer may not have executed).'
    case 'OBJECTIVE_NOT_POSITIVE':
      return 'Reference objective is ≤ 0 — dividing by a non-positive reference is mathematically meaningless for a MAXIMISATION ratio.'
    case 'QUANTUM_OBJECTIVE_NEGATIVE':
      return 'Quantum objective is negative — a sign-flipped quotient would misrepresent the outcome.'
    default:
      return basis === 'exact_optimal'
        ? 'Ratio cannot be computed from the recorded measurements.'
        : 'Ratio cannot be computed from the recorded heuristic comparison.'
  }
}

export interface BenchmarkAssemblyInput {
  quantumExecution: QuantumExecutionInput
  /**
   * Write-once snapshot from optimization_results (migration 007). When set,
   * its approximation-ratio fields and the QAOA seed are returned verbatim —
   * the historical record is never recomputed or overwritten. Omitted (legacy
   * rows) falls back to computing the ratio from the stored measurements.
   */
  stored?: BenchmarkStoredSnapshot | null
}

export interface BenchmarkStoredSnapshot {
  approximationRatio: number | null
  approximationBasis: 'exact_optimal' | 'greedy_reference' | null
  approximationInvalidReason: string | null
  randomSeed: number | null
}

/** Build the full benchmark document from a completed job's stored measurements. */
export function buildBenchmarkDocument(job: OptimizationJob, input: BenchmarkAssemblyInput): BenchmarkDocument {
  const result = job.result
  const comparison = classicalComparisonOf(result)
  const request = job.request

  const classical = classicalBlock(comparison)
  const quantum = quantumBlock(job, result, input.quantumExecution)
  const feasible = (result?.constraintViolations.length ?? 0) === 0

  const approximationRatio = computeApproximationRatio(
    classical.objectiveValue,
    quantum.objectiveValue,
    comparison?.method ?? null,
    feasible,
  )
  applyStoredRatio(approximationRatio, input.stored)

  return {
    jobId: job.id,
    status: job.status,
    problem: {
      type: job.problemType,
      size: {
        candidates: request.candidateCount,
        variables: job.variablesCount,
        selected: result?.selectedLocations.length ?? 0,
        constraints: constraintsCount(job),
      },
    },
    classical,
    quantum,
    constraintViolations: result?.constraintViolations ?? [],
    validation: {
      status: job.validationStatus ?? result?.validationStatus ?? null,
      summary: job.validationSummary ?? result?.validationSummary ?? null,
    },
    approximationRatio,
    reproducibility: reproducibilityBlock(job, classical.solver, input.stored?.randomSeed ?? null),
    completedAt: job.completedAt,
    quantumAdvantageClaimed: false,
    disclaimer:
      'No quantum speedup is claimed. A classical reference solver ran during the pipeline and its stored measurements are returned here verbatim.',
  }
}

/**
 * Prefer the write-once snapshot for the ratio over any recomputation. The note
 * is deterministic on (basis, invalidReason, feasible), so overriding value /
 * basis / reason keeps the note coherent.
 */
function applyStoredRatio(ratio: ApproximationRatioInfo, stored: BenchmarkStoredSnapshot | null | undefined): void {
  if (!stored) return
  if (stored.approximationRatio !== null) {
    ratio.value = stored.approximationRatio
    ratio.basis = stored.approximationBasis
    ratio.invalidReason = null
  } else if (stored.approximationInvalidReason !== null) {
    ratio.value = null
    ratio.invalidReason = stored.approximationInvalidReason
  } else if (stored.approximationBasis !== null) {
    ratio.basis = stored.approximationBasis
  }
}

/** Classic block — present whenever the pipeline recorded a classical comparison. */
export function classicalBlock(comparison: ClassicalComparison | null): BenchmarkClassicalBlock {
  if (!comparison) {
    return {
      solver: 'none',
      method: 'No classical reference recorded',
      optimal: false,
      objectiveValue: null,
      runtimeMs: null,
      selectedCount: null,
      gapVsQuantum: null,
      missingReason: 'MISSING_CLASSICAL_COMPARISON',
    }
  }
  const exhaustive = comparison.method === 'exhaustive'
  return {
    solver: exhaustive ? 'exhaustive' : comparison.method,
    method: comparison.method,
    optimal: exhaustive,
    objectiveValue: comparison.objectiveValue,
    runtimeMs: comparison.executionTimeMs,
    selectedCount: comparison.selectedCount,
    gapVsQuantum: comparison.gapVsQuantum,
    missingReason: null,
  }
}

function quantumBlock(job: OptimizationJob, result: OptimizationResult | null, input: QuantumExecutionInput): BenchmarkQuantumBlock {
  const { ran, runtimeMs, runtimeSource } = input
  const classical = !ran
  const hadQuantumOutcome = ran && result !== null
  return {
    algorithm: job.algorithm,
    objectiveValue: hadQuantumOutcome ? result!.objectiveValue : null,
    runtimeMs,
    runtimeSource: runtimeMs !== null ? runtimeSource : null,
    pipelineRuntimeMs: result?.executionTimeMs ?? null,
    backend: hadQuantumOutcome ? job.backendUsed : 'classical',
    executionMode: hadQuantumOutcome ? job.executionModeUsed : 'classical',
    simulated: result && hadQuantumOutcome ? result.simulated : null,
    qubits: result?.qubits ?? null,
    shots: job.request.shots,
    layers: job.request.layers,
    bitstring: result?.bitstring ?? null,
    missingReason: classical
      ? 'CLASSICAL_ONLY_RUN'
      : runtimeMs === null
        ? 'EXECUTOR_RUNTIME_NOT_PERSISTED'
        : null,
  }
}

function reproducibilityBlock(job: OptimizationJob, classicalSolver: string, storedSeed: number | null): BenchmarkReproducibility {
  const request = job.request
  // The persisted write-once seed is authoritative; recomputation is only the
  // legacy fallback for rows recorded before migration 007.
  const seed = storedSeed ?? seedFrom([job.id, request.forecastReference, request.candidateCount])
  return {
    seed,
    seedNote:
      'Deterministic seed actually passed to the QAOA driver — FNV-1a hash of (jobId, forecast reference, candidate count). Same formula as the executing orchestrator. Persisted write-once with the result.',
    qaoa: {
      layers: request.layers,
      shots: request.shots,
      backend: request.backend,
      angles: null,
      anglesNote: 'The executor does not expose variational |θ⟩ angles; layers p and shots are the recorded QAOA parameters.',
    },
    problem: {
      type: request.problemType,
      candidateCount: request.candidateCount,
      maxSensors: request.maxSensors,
      budgetK: request.budgetK,
      weights: request.weights,
      normalizeWeights: request.normalizeWeights,
      coverageRequirements: request.coverageRequirements,
      forecastReference: request.forecastReference,
      candidateReference: job.candidateReference ?? request.candidateLocationsReference ?? null,
      variablesCount: job.variablesCount,
    },
    solver: {
      fallbackPolicy: job.fallbackPolicy,
      fallbackApplied: job.fallbackApplied,
      fallbackReason: job.fallbackReason,
      classicalSolver,
    },
  }
}

/** Aggregated row for the benchmark list endpoint (no per-job executor reads). */
export function benchmarkListEntry(job: OptimizationJob): BenchmarkListEntry {
  const result = job.result
  const comparison = classicalComparisonOf(result)
  const classicalObjective = comparison?.objectiveValue ?? null
  const quantumObjective = result?.objectiveValue ?? null
  const ratio = computeApproximationRatio(
    classicalObjective,
    quantumObjective,
    comparison?.method ?? null,
    (result?.constraintViolations.length ?? 0) === 0,
  )
  return {
    jobId: job.id,
    problemType: job.problemType,
    algorithm: job.algorithm,
    executionMode: job.executionModeUsed,
    backend: job.backendUsed,
    status: job.status,
    createdAt: job.createdAt,
    completedAt: job.completedAt,
    classical: {
      solver: comparison?.method ?? 'none',
      optimal: comparison?.method === 'exhaustive',
      objectiveValue: classicalObjective,
      runtimeMs: comparison?.executionTimeMs ?? null,
    },
    quantum: {
      objectiveValue: quantumObjective,
      runtimeMs: null,
    },
    approximationRatio: { value: ratio.value, basis: ratio.basis, invalidReason: ratio.invalidReason },
    constraintViolationCount: result?.constraintViolations.length ?? null,
    validated: result ? result.validationStatus === 'valid' : null,
  }
}

function classicalComparisonOf(result: OptimizationResult | null): ClassicalComparison | null {
  if (!result) return null
  return result.classicalComparison ?? null
}

function constraintsCount(job: OptimizationJob): number {
  const resolved = job.constraints?.coverageRequirements ?? job.request.coverageRequirements ?? []
  return resolved.length + (job.request.budgetK !== null ? 2 : 1)
}