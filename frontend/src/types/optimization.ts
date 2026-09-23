/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum Optimization domain contract.
 *
 * The frontend talks to a pluggable adapter (see `services/optimization/`):
 *  - `mock` adapter  — development-only, clearly isolated behind the
 *    `VITE_USE_MOCK_DATA` flag; simulates the whole pipeline deterministically.
 *  - `http` adapter  — production path that calls real gateway/quantum-service
 *    APIs (endpoints documented in the adapter file).
 *
 * Inputs are always provided by external modules: forecast data by the AI
 * /Navya's forecasting service, candidate locations + coverage by the GIS
 * /Jahnavi module, resource constraints by the planning/Thoshish module.
 * None of those systems are built inside this page.
 */

export type OptimizationProblemType = 'sensor_placement' | 'resource_allocation'

export type ExecutionMode = 'simulator' | 'hardware'

/** Quantum backend identifiers surfaced by the executor. */
export type QuantumBackend =
  | 'aer_simulator_statevector'
  | 'aer_simulator_matrix_product_state'
  | 'ibm_brisbane'
  | 'ibm_kyiv'

export type RiskProfile = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type AdapterMode = 'mock' | 'http'

/** Weight axes available for the objective. Keys are stable problem agnostic ids. */
export type ObjectiveKey =
  | 'risk'
  | 'populationCoverage'
  | 'infrastructureCoverage'
  | 'communication'
  | 'cost'
  | 'redundancy'

export type ObjectiveWeights = Record<ObjectiveKey, number>

export interface ObjectiveCategory {
  /** Weights that multiply GIS/asset data (higher = favour those assets). */
  kind: 'data' | 'resource'
}

export interface ObjectiveMeta {
  key: ObjectiveKey
  label: string
  description: string
  min: number
  max: number
}

export interface ProblemTypeSpec {
  id: OptimizationProblemType
  label: string
  description: string
  /** False for problems the UI can configure but the executor does not support yet. */
  enabled: boolean
  planned?: string
  objectiveWeights: ObjectiveKey[]
}

/**
 * One candidate sensor location from the GIS module (Jahnavi). All fields are
 * already validated float metrics in [0, 1]; the optimizer only consumes them.
 */
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

export interface CoverageRequirement {
  metric: 'population' | 'infrastructure'
  minFraction: number
  origin: string
}

/**
 * Resource constraints consumed by the optimizer. They originate from the
 * planning module (Thoshish) and/or the operator's Step 1 configuration.
 */
export interface ResourceConstraints {
  maxSensors: number
  budgetK: number | null
  coverageRequirements: CoverageRequirement[]
  notes: string[]
}

export interface ProviderProvenance {
  candidateLocations: string
  resourceConstraints: string
  forecast: string
}

/** Federated inputs assembled by the adapter from the other platform modules. */
export interface OptimizationInputs {
  candidates: CandidateLocation[]
  constraints: ResourceConstraints
  forecast: { forecastId: string; riskScore: number; priority: RiskProfile } | null
  providedBy: ProviderProvenance
}

/** The inputs slice the page receives from the adapter (shape shared by mock + http). */
export interface OptimizationInputsResult {
  candidates: CandidateLocation[]
  constraints: ResourceConstraints
  forecastRef: string | null
  providedBy: ProviderProvenance
}

/** Everything the page collects across Step 1–4 that the executor needs. */
export interface OptimizeRequest {
  problemType: OptimizationProblemType
  candidateCount: number
  maxSensors: number
  budgetK: number | null
  forecastReference: string
  riskProfile: RiskProfile
  executionMode: ExecutionMode
  hardwareEnabled: boolean
  backend: QuantumBackend
  shots: number
  layers: number
  weights: ObjectiveWeights
  normalizeWeights: boolean
  coverageRequirements: CoverageRequirement[]
}

export type PipelineStageId =
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

export type StageStatus = 'pending' | 'running' | 'done' | 'failed'

export interface PipelineStage {
  id: PipelineStageId
  label: string
  detail: string
  status: StageStatus
  meta?: Record<string, string>
  error?: string
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

export interface QuboDocument {
  variableCount: number
  variables: string[]
  /** Human-readable QUBO expression, e.g. `0.41·SIT-001 + 0.02·SIT-001,SIT-002 + P·(sum - 6)²`. */
  expression: string
  /** Symmetric Q-matrix rows. */
  matrix: number[][]
  offset: number
}

export interface ClassicalComparison {
  method: string
  objectiveValue: number
  selectedCount: number
  executionTimeMs: number
  gapVsQuantum: number
}

export interface ObjectiveBreakdown {
  key: ObjectiveKey
  label: string
  value: number
}

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
  validationStatus: 'valid' | 'invalid'
  validationSummary: string | null
  /** Decoded solution bitstring reported verbatim by the executor. */
  bitstring: string
  qubo: QuboDocument
  measurementCounts: MeasurementCount[]
  energyHistory: EnergyPoint[]
  classicalComparison: ClassicalComparison
}

/* ------------------------------------------------------------------ */
/* Quantum Job Status                                                   */
/* ------------------------------------------------------------------ */

/**
 * Job states surfaced by the gateway. `queued` and `running` are live —
 * the status page polls until a terminal state (completed / failed /
 * timed_out / cancelled / invalid) is reached.
 */
export type QuantumJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'timed_out'
  | 'cancelled'
  | 'invalid'

/** Runtime modes reported by the gateway (wider than the UI's two-way split). */
export type QuantumExecutionMode = 'simulator' | 'aer' | 'ibm_hardware'

/** Mode the job actually ran in — `classical` after a classical-only fallback. */
export type ExecutionModeUsed = QuantumExecutionMode | 'classical'

/** Backend ids the gateway may report (UI selectable set + executor extras + classical). */
export type QuantumRunBackend = QuantumBackend | 'qflare_simulator_statevector' | 'classical'

export type FallbackPolicy = 'retry_simulator' | 'classical_only' | 'error'

/** Resolved constraint set the gateway preserved with a job. */
export interface ResolvedConstraints {
  maxSensors: number
  budgetK: number | null
  coverageRequirements: CoverageRequirement[]
}

/** Objective configuration the gateway preserved with a job. */
export interface ObjectiveConfiguration {
  weights: ObjectiveWeights
  normalizeWeights: boolean
  layers: number
  shots: number
}

/**
 * Job summary served by GET /api/optimization/:id — the status page's primary
 * source of truth. Field names mirror the backend contract verbatim, so the
 * page renders the gateway's data without re-deriving anything.
 */
export interface QuantumJobSummary {
  id: string
  jobId: string
  status: QuantumJobStatus
  problemType: OptimizationProblemType
  algorithm: string
  executionMode: QuantumExecutionMode
  executionModeUsed: ExecutionModeUsed
  backend: QuantumRunBackend
  backendUsed: QuantumRunBackend
  fallbackPolicy: FallbackPolicy
  fallbackApplied: boolean
  fallbackReason: string | null
  qubitCount: number | null
  validationStatus: 'valid' | 'invalid' | null
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
     * min(1, quantum/classical) on the optimized objective — the gateway's
     * approximation quality. Higher is better, never exceeds 1. Null when there
     * is no classical reference. A fallback run (no real quantum result)
     * reports 1.0 with `fallbackApplied` set, which the benchmark UI labels.
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
  forecastReference: string | null
  candidateReference: string | null
  inputReference: string | null
  variablesCount: number | null
  constraints: ResolvedConstraints | null
  objectiveConfiguration: ObjectiveConfiguration | null
  quboStorage: 'inline' | 'artifact' | null
  quboArtifactReference: string | null
  errorMessage: string | null
  deletedAt: string | null
  deletedBy: string | null
  deleteReason: string | null
}

export type QuantumModalKind = 'qubo' | 'qaoa-job' | 'classical' | 'final-result' | 'export'

/** Pipeline events streamed to the UI while a job runs. */
export interface PipelineUpdate {
  stageId: PipelineStageId
  status: StageStatus
  error?: string
}

/* ------------------------------------------------------------------ */
/* QUBO Visualization                                                   */
/* ------------------------------------------------------------------ */

/**
 * Availability of a served formulation for the visualization page.
 * `valid` = the stored matrix is well formed (N rows × 2N columns);
 * `unavailable` = the job never produced a QUBO (queued / failed early);
 * `invalid` = the stored matrix is malformed. Always sourced from the backend.
 */
export type QuboAvailability = 'valid' | 'unavailable' | 'invalid'

export interface QuboConstraintRow {
  key: string
  name: string
  configuredLimit: number
  /** QUBO penalty weight, or null when the constraint is not an explicit QUBO term. */
  penalty: number | null
  penaltyKind: 'qubo' | 'post_decode' | null
  status: 'satisfied' | 'violated' | 'unknown'
  detail: string
}

export interface QuboPenaltyTerm {
  key: string
  name: string
  formula: string
  scale: number | null
  detail: string
}

export interface QuboVariableDetail {
  index: number
  id: string
  candidateId: string
  name: string | null
  zone: string | null
  selected: boolean
  semantic: string
}

/**
 * Full formulation served by GET /api/optimization/jobs/:id/qubo. The backend
 * is the single source of truth: every number rendered on the visualization
 * page (matrix, linear/quadratic, penalty scale, bitstring) is carried in this
 * payload — nothing is re-derived from the matrix in React.
 */
export interface QuboFormulation {
  jobId: string
  problemType: OptimizationProblemType
  algorithm: string
  status: string
  createdAt: string
  available: QuboAvailability
  storage: 'inline' | 'artifact' | null
  inline: boolean
  variableCount: number | null
  variables: string[]
  /** Human-readable QUBO expression. */
  expression: string
  /** Stored doc matrix: N rows × 2N columns (quadratic row ‖ linear vector). */
  matrix: number[][]
  artifactReference: string | null
  offset: number
  /** Served linear vector (authoritative, length N) or null when no build. */
  linear: number[] | null
  /** Served quadratic part (N×N) or null when no build. Stored as an upper-triangular half — Q[j][i]=0 for j<i, mirroring Q[i][j] by the symmetric QUBO convention — so it is rendered exactly as served, never re-mirrored in React. */
  quadratic: number[][] | null
  penaltyScale: number | null
  summary: {
    variables: number | null
    linearTerms: number | null
    quadraticTerms: number | null
    constraints: number | null
    penaltyStrength: number | null
  }
  constraints: QuboConstraintRow[]
  penalties: QuboPenaltyTerm[]
  objective: {
    target: 'minimize'
    expression: string
    explanation: string
  }
  variablesDetail: QuboVariableDetail[]
  bitstring: string | null
  selectedVariableIds: string[]
  hasResult: boolean
  validationStatus: string | null
  validationSummary: string | null
}

/* ------------------------------------------------------------------ */
/* Optimization Result page                                            */
/* ------------------------------------------------------------------ */

/**
 * Federated inputs served by `GET /api/optimization/inputs` — the GIS
 * candidate sites (with coordinates) plus the planning constraints. Used to
 * place the selected subset on the map and to fill the location table; the
 * decision document itself never carries geometry.
 */
export interface OptimizationInputsPayload {
  candidates: CandidateLocation[]
  constraints: ResourceConstraints
  providedBy: ProviderProvenance
}

/**
 * Backend-generated, auditable result document served by
 * `GET /api/optimization/jobs/:id/export`. The page downloads this verbatim —
 * the export is never reconstructed in React. `quantumAdvantageClaimed` is
 * always `false` and the disclaimer travels with the file.
 */
export interface OptimizationExportDocument {
  jobId: string
  exportedAt: string
  status: QuantumJobStatus
  summary: QuantumJobSummary
  result: OptimizationResult | null
  quantumAdvantageClaimed: false
  benchmarkDisclaimer: string
}