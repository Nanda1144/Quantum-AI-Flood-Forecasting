/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum-optimization domain types for the Nanda orchestration backend.
 *
 * The backend orchestrates the 15-step optimization pipeline: it validates,
 * federates inputs (forecast / GIS candidates / resource constraints), builds
 * and serves QUBOs, executes the classical reference solver, drives QAOA
 * through the quantum FastAPI service, decodes and validates the outcome,
 * compares against the classical benchmark, and persists the result.
 *
 * Field names mirror the frontend contract (`frontend/src/types/optimization.ts`)
 * so the HTTP adapter renders responses without translation.
 */

export type OptimizationProblemType = 'sensor_placement' | 'resource_allocation'

/** Execution modes understood by both the backend and the quantum service. */
export type QuantumExecutionMode = 'simulator' | 'aer' | 'ibm_hardware'

/** Requested runtime mode as sent by the frontend (two-way split on backend). */
export type FrontendExecutionMode = 'simulator' | 'hardware'

export type QuantumBackend =
  | 'qflare_simulator_statevector'
  | 'aer_simulator_statevector'
  | 'aer_simulator_matrix_product_state'
  | 'ibm_brisbane'
  | 'ibm_kyiv'

export type RiskProfile = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type ObjectiveKey =
  | 'risk'
  | 'populationCoverage'
  | 'infrastructureCoverage'
  | 'communication'
  | 'cost'
  | 'redundancy'

export type ObjectiveWeights = Record<ObjectiveKey, number>

export type CoverageMetric = 'population' | 'infrastructure'

export interface CoverageRequirement {
  metric: CoverageMetric
  minFraction: number
  origin: string
}

/** A candidate from the GIS module — all metrics are validated floats in [0,1]. */
export interface CandidateLocation {
  id: string
  name: string
  zone: string
  latitude: number
  longitude: number
  floodRisk: number
  populationExposure: number
  infrastructureCriticality: number
  communicationScore: number
  sensorCostK: number
  coverageRadiusKm: number
}

export interface ResourceConstraintsInput {
  maxSensors: number
  budgetK: number | null
  coverageRequirements: CoverageRequirement[]
}

/** Validated request into the orchestration pipeline (frontend OptimizeRequest). */
export interface RunOptimizationRequest {
  problemType: OptimizationProblemType
  candidateCount: number
  maxSensors: number
  budgetK: number | null
  forecastReference: string
  riskProfile?: RiskProfile
  executionMode: FrontendExecutionMode
  hardwareEnabled: boolean
  backend: QuantumBackend
  shots: number
  layers: number
  weights: ObjectiveWeights
  normalizeWeights: boolean
  coverageRequirements: CoverageRequirement[]
  candidateLocationsReference?: string
}

/**
 * Fallback behaviour when the configured quantum execution path fails. This is
 * the configured safety valve so a hardware failure never takes the system
 * down (see backend/README.md "Fallback policy").
 */
export type FallbackPolicy = 'retry_simulator' | 'classical_only' | 'error'

export type OptimizationJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'timed_out'

/**
 * Result validation state. Three distinct states so an INVALID result is never
 * conflated with a VALIDATED one:
 *   valid               the pipeline verdict accepted the decoded solution
 *   invalid             the pipeline verdict rejected the decoded solution
 *   pending_validation  persisted but not yet validated (never a recommendation)
 */
export type ValidationStatus = 'valid' | 'invalid' | 'pending_validation'

/** The 15 canonical pipeline steps (spec: PIPELINE). */
export type PipelineStepId =
  | 'validate_request'
  | 'retrieve_forecast'
  | 'retrieve_candidates'
  | 'retrieve_constraints'
  | 'normalize_features'
  | 'build_objective'
  | 'apply_constraints_penalties'
  | 'construct_qubo'
  | 'classical_benchmark'
  | 'execute_qaoa'
  | 'decode_bitstring'
  | 'validate_constraints'
  | 'compare_results'
  | 'persist_result'
  | 'return_response'

export type StepStatus = 'pending' | 'running' | 'done' | 'failed'

export type FrontendStageId =
  | 'input'
  | 'validation'
  | 'qubo'
  | 'hamiltonian'
  | 'qaoa'
  | 'measurement'
  | 'decode'
  | 'constraintValidation'
  | 'benchmark'
  | 'final'

export interface PipelineStep {
  id: PipelineStepId
  label: string
  /** Frontend stage bucket this step reports into (derives /jobs/:id/pipeline). */
  stage: FrontendStageId
  status: StepStatus
  detail: string
  startedAt?: string
  endedAt?: string
  error?: string
}

export interface QuboDocument {
  variableCount: number
  variables: string[]
  expression: string
  /** Symmetric Q-matrix rows; the last column carries the linear terms. */
  matrix: number[][]
  offset: number
}

export interface QuboBuild {
  doc: QuboDocument
  linear: number[]
  quadratic: number[][]
  penaltyScale: number
}

export interface ConstraintViolation {
  code: string
  message: string
}

export interface MeasurementCount {
  bitstring: string
  count: number
}

export interface EnergyPoint {
  iteration: number
  energy: number
}

export interface ClassicalComparison {
  method: string
  objectiveValue: number
  selectedCount: number
  executionTimeMs: number
  gapVsQuantum: number
}

export interface SelectedLocation {
  id: string
  name: string
  zone: string
  sensorCostK: number
  floodRisk: number
  populationCovered: number
  infrastructureCovered: number
}

export interface CoverageStats {
  populationCovered: number
  populationTotal: number
  infrastructureCovered: number
  infrastructureTotal: number
}

export interface ObjectiveBreakdown {
  key: ObjectiveKey
  label: string
  value: number
}

/** Full result document — shape-compatible with the frontend OptimizationResult. */
export interface OptimizationResult {
  jobId: string
  simulated: boolean
  backend: QuantumBackend
  qubits: number
  shots: number
  layers: number
  startedAt: string
  endedAt: string
  executionTimeMs: number
  objectiveValue: number
  objectiveBreakdown: ObjectiveBreakdown[]
  selectedLocations: SelectedLocation[]
  coverage: CoverageStats | null
  constraintViolations: ConstraintViolation[]
  validationStatus: ValidationStatus
  validationSummary: string
  /** Decoded solution bitstring (the persistence layer records it verbatim). */
  bitstring: string
  qubo: QuboDocument
  measurementCounts: MeasurementCount[]
  energyHistory: EnergyPoint[]
  classicalComparison: ClassicalComparison
  /** No quantum speedup is ever claimed — the benchmark above is always stored. */
  quantumAdvantageClaimed: false
  benchmarkDisclaimer: string
}

/** Stable id for each backend integrity audit over a stored result. */
export type ResultIntegrityCheckId =
  | 'result_status'
  | 'candidate_source'
  | 'bitstring_maps_to_variables'
  | 'selected_candidates_exist'
  | 'constraints_satisfied'
  | 'objective_consistent'

/** One audited integrity check — a stored result is never trusted, only checked. */
export interface ResultIntegrityCheck {
  id: ResultIntegrityCheckId
  label: string
  passed: boolean
  detail: string
}

/**
 * Backend integrity report for a stored result document.
 *
 * The database / optimization service is the source of truth: the bitstring is
 * re-decoded against the deterministic candidate set, the constraints are
 * re-validated and the objective is recomputed from stored measurements. A
 * failure does NOT delete or hide the record — the result is preserved for
 * debugging/research — but it is never presented as an operational
 * recommendation.
 */
export interface ResultIntegrityReport {
  valid: boolean
  checks: ResultIntegrityCheck[]
  /** Ids of the checks that failed (empty when valid). */
  failed: ResultIntegrityCheckId[]
  summary: string
}

/**
 * Operational-recommendation gate. A result may only be presented as an
 * operational recommendation when the job completed, the pipeline validation
 * passed AND the backend integrity audit passed. An ineligible result is still
 * returned (preserved) with `reason` explaining why it must not be acted on.
 */
export interface ResultRecommendation {
  eligible: boolean
  reason: string | null
}

/** Exact experiment configuration preserved with a result (never fabricated). */
export interface ResultExperimentMetadata {
  problemType: OptimizationProblemType
  algorithm: string
  executionMode: QuantumExecutionMode
  executionModeUsed: QuantumExecutionMode | 'classical'
  backend: QuantumBackend
  backendUsed: QuantumBackend | 'classical'
  qubits: number | null
  shots: number
  layers: number
  fallbackPolicy: FallbackPolicy
  fallbackApplied: boolean
  fallbackReason: string | null
  owner: string
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  forecastReference: string | null
  candidateReference: string | null
  inputReference: string | null
  variablesCount: number | null
  constraints: ResolvedConstraints | null
  objectiveConfiguration: ObjectiveConfiguration | null
  /** Reproducibility block duplicated from the benchmark document (same seed). */
  reproducibility: BenchmarkReproducibility
}

/**
 * The final, integrity-audited result read model served by
 * `GET /api/optimization/:id/result` (and the legacy `/jobs/:id/result`).
 *
 * Extends the persisted `OptimizationResult` verbatim — the stored measurements
 * are always returned as recorded — and adds the backend audit, the
 * recommendation gate, the quantum comparison and the experiment metadata.
 */
export interface OptimizationResultDocument extends OptimizationResult {
  integrity: ResultIntegrityReport
  recommendation: ResultRecommendation
  quantumComparison: BenchmarkQuantumBlock
  approximationRatio: ApproximationRatioInfo
  experiment: ResultExperimentMetadata
}

/** `GET /api/optimization/:id` — job summary plus the audited result, when one exists. */
export interface OptimizationJobDetail extends OptimizationJobSummary {
  /** Integrity-audited result document; null until the pipeline persists one. */
  result: OptimizationResultDocument | null
}

/** Structured, auditable export document (`GET /api/optimization/:id/export`). */
export interface OptimizationExportDocument {
  jobId: string
  exportedAt: string
  status: OptimizationJobStatus
  summary: OptimizationJobSummary
  result: OptimizationResultDocument | null
  integrity: ResultIntegrityReport | null
  recommendation: ResultRecommendation | null
  experiment: ResultExperimentMetadata | null
  quantumAdvantageClaimed: false
  benchmarkDisclaimer: string
}

/** Persisted optimization job — the operational record written to PostgreSQL. */
export interface OptimizationJob {
  id: string
  owner: string
  status: OptimizationJobStatus
  problemType: OptimizationProblemType
  request: RunOptimizationRequest
  fallbackPolicy: FallbackPolicy
  algorithm: string
  /** Requested execution mode (pre-fallback). */
  executionMode: QuantumExecutionMode
  /** Mode actually used; may differ when a fallback kicked in. */
  executionModeUsed: QuantumExecutionMode | 'classical'
  backend: QuantumBackend
  backendUsed: QuantumBackend | 'classical'
  fallbackApplied: boolean
  fallbackReason: string | null
  qubitCount: number | null
  steps: PipelineStep[]
  qubo: QuboBuild | null
  classical: ClassicalComparison | null
  result: OptimizationResult | null
  validationStatus: ValidationStatus | null
  validationSummary: string | null
  error: { code: string; message: string; details?: unknown } | null
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  /** Persistence-layer configuration references (exact experiment config). */
  forecastReference: string | null
  candidateReference: string | null
  inputReference: string | null
  variablesCount: number | null
  constraints: ResolvedConstraints | null
  objectiveConfiguration: ObjectiveConfiguration | null
  errorMessage: string | null
  /** QUBO matrix placement: inline JSONB (small demonstrative) or artifact reference (large). */
  quboStorage: QuboStorage
  quboArtifactReference: string | null
  /** Authorized soft-delete trail (completed results are never hard-deleted). */
  deletedAt: string | null
  deletedBy: string | null
  deleteReason: string | null
}

export interface OptimizationJobSummary {
  id: string
  /** Alias of `id` — the job key the frontend adapter and `/jobs/:id` reads use. */
  jobId: string
  status: OptimizationJobStatus
  problemType: OptimizationProblemType
  algorithm: string
  executionMode: QuantumExecutionMode
  executionModeUsed: QuantumExecutionMode | 'classical'
  backend: QuantumBackend
  backendUsed: QuantumBackend | 'classical'
  fallbackPolicy: FallbackPolicy
  fallbackApplied: boolean
  fallbackReason: string | null
  qubitCount: number | null
  validationStatus: ValidationStatus | null
  validationSummary: string | null
  resultSummary: {
    objectiveValue: number | null
    selectedCount: number | null
    executionTimeMs: number | null
    gapVsQuantum: number | null
    /** Reference objective from the persisted classical run (null = none). */
    classicalObjectiveValue: number | null
    /** Reference wall time from the persisted classical run (null = none). */
    classicalRuntimeMs: number | null
    /**
     * min(1, quantum/classical) on the optimized objective — the stored
     * approximation quality. Higher is better and it never exceeds 1. Null when
     * there is no classical reference. A fallback run (no real quantum result)
     * reports 1.0 with `fallbackApplied` set, which UIs must label.
     */
    approximationQuality: number | null
    /** Whether the run's constraints validated (null = no result). */
    validated: boolean | null
    constraintViolationCount: number | null
  }
  owner: string
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  /** Persistence layer (migration 004) — exact experiment configuration. */
  forecastReference: string | null
  candidateReference: string | null
  inputReference: string | null
  variablesCount: number | null
  constraints: ResolvedConstraints | null
  objectiveConfiguration: ObjectiveConfiguration | null
  quboStorage: QuboStorage | null
  quboArtifactReference: string | null
  errorMessage: string | null
  deletedAt: string | null
  deletedBy: string | null
  deleteReason: string | null
}

/** Resolved constraint set preserved with a job (exact experiment config). */
export interface ResolvedConstraints {
  maxSensors: number
  budgetK: number | null
  coverageRequirements: CoverageRequirement[]
}

/** Objective configuration preserved with a job (exact experiment config). */
export interface ObjectiveConfiguration {
  weights: ObjectiveWeights
  normalizeWeights: boolean
  layers: number
  shots: number
}

/** Where the QUBO matrix lives: inline JSONB or the artifact store (by reference). */
export type QuboStorage = 'inline' | 'artifact'

/**
 * The persisted validation verdict (migration 008) — a compact, honest record
 * of why a result is valid/invalid, stored alongside the status itself.
 */
export interface ResultValidationDetails {
  status: ValidationStatus
  summary: string | null
  violationCount: number
  violations: ConstraintViolation[]
}

/**
 * Explanation metadata (migration 008) — how the objective decomposes, so the
 * score is explainable from the row without recomputation.
 */
export interface ResultExplanationMetadata {
  objectiveBreakdown: ObjectiveBreakdown[]
  coverage: CoverageStats | null
  quantumAdvantageClaimed: false
}

/**
 * Normalized result row — the `optimization_results` persistence record.
 * One row per completed job; stores location IDs, never GIS geometry.
 */
export interface OptimizationResultRecord {
  id: string
  optimizationJobId: string
  bitstring: string | null
  selectedLocationIds: string[]
  objectiveValue: number
  constraintViolations: ConstraintViolation[]
  validationStatus: ValidationStatus
  runtimeMs: number
  classicalObjective: number | null
  quantumObjective: number | null
  approximationQuality: number | null
  /** Classical benchmark reference (migration 007) — write-once snapshot. */
  classicalSolver: 'exhaustive' | 'greedy' | null
  classicalRuntimeMs: number | null
  /**
   * Direction-aware quantum/reference ratio, persisted once at pipeline
   * completion (never overwritten, never recomputed over a stored row).
   */
  approximationRatio: number | null
  /** Basis the stored ratio is interpreted against. */
  approximationBasis: 'exact_optimal' | 'greedy_reference' | null
  /** Why no ratio exists (NULL when a ratio IS stored). */
  approximationInvalidReason:
    | 'MISSING_CLASSICAL_REFERENCE'
    | 'MISSING_QUANTUM_OBJECTIVE'
    | 'OBJECTIVE_NOT_POSITIVE'
    | 'QUANTUM_OBJECTIVE_NEGATIVE'
    | null
  /** Seed actually passed to the QAOA driver for this job. */
  randomSeed: number | null
  /** When the verdict was recorded (migration 008); NULL while pending. */
  validationTimestamp: string | null
  /** The persisted validation verdict (migration 008). */
  validationDetails: ResultValidationDetails | null
  /** Objective-explanation metadata (migration 008). */
  explanationMetadata: ResultExplanationMetadata | null
  createdAt: string
}

/** Write-once audit entry backing the delete-protection guarantee. */
export interface OptimizationJobAuditEntry {
  id: number
  optimizationJobId: string
  action: string
  actor: string
  reason: string | null
  createdAt: string
}

/** How a QUBO is persisted relative to the database (migration 005). */
export type QuboStorageMode = 'inline' | 'artifact'

/**
 * QUBO metadata audit record (`optimization_qubo_metadata`, migration 005).
 * One row per job — `quboId` is always `<optimizationJobId>-Q1`.
 *
 * Small prototype/research problems inline the full plain-JSON representation
 * so the experiment can be reproduced and audited directly. Larger problems
 * store only a reference + sha-256 checksum + matrix dimensions + storage
 * location + summary metadata; the matrix cells themselves live outside the
 * database and are never embedded. Raw Python/Qiskit objects are never
 * persisted. These guarantee "enough information to reproduce and audit".
 */
export interface QuboMetadata {
  quboId: string
  optimizationJobId: string
  storageMode: QuboStorageMode
  variableCount: number
  /** Inline representation (small problems) — plain JSON, never Qiskit objects. */
  matrix?: number[][]
  linearTerms?: number[]
  quadraticTerms?: number[][]
  penaltyConfiguration?: { penaltyScale: number; offset: number }
  objectiveExpression?: string
  /** Artifact representation (large problems) — reference only, never embedded. */
  artifactReference?: string
  checksum?: string
  matrixDimensions?: { variables: number; rowCount: number; columnCount: number }
  storageLocation?: string
  metadata?: Record<string, unknown>
  createdAt?: string
}

/**
 * Lifecycle status of a persisted quantum submission (migrations 006 + 009).
 *
 * The full terminal set mirrors the quantum service's state machine:
 * `queued -> running -> completed | failed | cancelled | invalid` where
 * `invalid` marks a submission whose measured bitstring did not match the
 * declared binary variables (INVALID_EXECUTION_RESULT). Migration 009 widened
 * the `quantum_jobs.status` CHECK to admit `invalid`.
 */
export type QuantumJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'invalid'

/**
 * Persisted quantum submission record (`quantum_jobs`, migration 006).
 *
 * One row per REAL quantum-service job; `id` is the service's own job id.
 * `executionMode`/`backend` are the mode + backend of THAT submission, so the
 * simulator/hardware distinction survives fallback ladders — a retried job
 * records one honest failed row (aer/ibm_hardware) and one completed row
 * (simulator). Only configuration scalars and statuses are stored: never
 * credentials, never raw circuit objects.
 */
export interface QuantumJobRecord {
  id: string
  optimizationJobId: string
  algorithm: string
  backend: QuantumBackend
  executionMode: QuantumExecutionMode
  qubits: number | null
  shots: number
  layers: number
  status: QuantumJobStatus
  submittedAt: string
  startedAt: string | null
  completedAt: string | null
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
}

/**
 * Normalized quantum result row (`quantum_results`, migration 006).
 *
 * One row per completed quantum job (`id` is always `<quantumJobId>-R1`).
 * `counts` is plain JSON (bitstring → count); heavy circuit/metadata payloads
 * are referenced through `rawMetadataReference`, never embedded.
 */
export interface QuantumResultRecord {
  id: string
  quantumJobId: string
  bitstring: string | null
  counts: Record<string, number>
  objectiveValue: number | null
  runtimeMs: number
  rawMetadataReference: string | null
  createdAt: string
}

// ────────────────────────────────────────────────────────────────────────────
// Benchmark API contract.
//
// The classical reference is ALWAYS the ground truth the quantum outcome is
// compared against: never the other way around, and no speedup is ever claimed
// here. The API returns raw stored measurements; the frontend explains them.
// ────────────────────────────────────────────────────────────────────────────

/**
 * Objective direction of the sensor-placement benchmark. Weighted utility is
 * MAXIMISED, so the approximation ratio is quantum/optimal — and dividing is
 * only valid when both objectives are positive. Ratios are never clamped:
 * against a heuristic (greedy) reference a quantum outcome may legitimately
 * exceed 1.0, and that raw value is what the experiment recorded.
 */
export type BenchmarkObjectiveDirection = 'maximize'

/** Direction-aware approximation ratio — never a blind division. */
export interface ApproximationRatioInfo {
  /** The ratio, or null when the division is mathematically invalid. */
  value: number | null
  /** What the reference really is: exact optimum vs heuristic reference. */
  basis: 'exact_optimal' | 'greedy_reference' | null
  direction: BenchmarkObjectiveDirection
  /** False when the quantum solution violated constraints (ratio is to an infeasible outcome). */
  feasible: boolean
  /** Stable reason when `value` is null (e.g. OBJECTIVE_NOT_POSITIVE). */
  invalidReason: string | null
  /** Human explanation of what the number does and does not mean. */
  note: string
}

export interface BenchmarkProblemBlock {
  type: OptimizationProblemType
  size: {
    /** Candidate sites considered (the raw problem size). */
    candidates: number
    /** QUBO variables (may differ from candidates when the model augments them). */
    variables: number | null
    /** Sensors deployed by the quantum outcome. */
    selected: number
    /** Number of constraints configured for the experiment. */
    constraints: number
  }
}

export interface BenchmarkClassicalBlock {
  /** Stable solver id: `exhaustive` (brute-force exact) or `greedy`. */
  solver: string
  /** Human label for the solver used. */
  method: string
  /** True only when the reference is the brute-force optimum (ground truth). */
  optimal: boolean
  objectiveValue: number | null
  runtimeMs: number | null
  selectedCount: number | null
  gapVsQuantum: number | null
  /** Why the reference is absent, when it is. */
  missingReason: string | null
}

export interface BenchmarkQuantumBlock {
  algorithm: string
  /** Objective of the decoded quantum outcome, when a quantum run happened. */
  objectiveValue: number | null
  /** Executor wall time (`quantum_results.runtime_ms`), never the pipeline total. */
  runtimeMs: number | null
  /** Where `runtimeMs` came from, or null when it was not persisted. */
  runtimeSource: string | null
  /** End-to-end pipeline wall time, labelled as such — not quantum execution time. */
  pipelineRuntimeMs: number | null
  backend: QuantumBackend | 'classical'
  executionMode: QuantumExecutionMode | 'classical'
  simulated: boolean | null
  qubits: number | null
  shots: number
  layers: number
  bitstring: string | null
  /** Why the quantum outcome is absent, when it is. */
  missingReason: string | null
}

export interface BenchmarkReproducibility {
  /** Deterministic seed actually passed to the QAOA driver (see seedNote). */
  seed: number
  seedNote: string
  qaoa: {
    layers: number
    shots: number
    backend: QuantumBackend
    /** Variational angles are not exposed by the executor — always null. */
    angles: number[] | null
    anglesNote: string
  }
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
  status: OptimizationJobStatus
  problem: BenchmarkProblemBlock
  classical: BenchmarkClassicalBlock
  quantum: BenchmarkQuantumBlock
  constraintViolations: ConstraintViolation[]
  validation: { status: ValidationStatus | null; summary: string | null }
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
  backend: QuantumBackend | 'classical'
  status: OptimizationJobStatus
  createdAt: string
  completedAt: string | null
  classical: { solver: string; optimal: boolean; objectiveValue: number | null; runtimeMs: number | null }
  quantum: { objectiveValue: number | null; runtimeMs: number | null }
  approximationRatio: { value: number | null; basis: 'exact_optimal' | 'greedy_reference' | null; invalidReason: string | null }
  constraintViolationCount: number | null
  validated: boolean | null
}

/** Optional filters for `GET /api/benchmarks`. */
export interface BenchmarkListFilters {
  problemType?: OptimizationProblemType
  algorithm?: string
  executionMode?: QuantumExecutionMode
  /** Inclusive lower bound on job creation (ISO datetime). */
  from?: string
  /** Inclusive upper bound on job creation (ISO datetime). */
  to?: string
}