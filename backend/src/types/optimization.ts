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

export type ValidationStatus = 'valid' | 'invalid'

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
  qubo: QuboDocument
  measurementCounts: MeasurementCount[]
  energyHistory: EnergyPoint[]
  classicalComparison: ClassicalComparison
  /** No quantum speedup is ever claimed — the benchmark above is always stored. */
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
    constraintViolationCount: number | null
  }
  owner: string
  createdAt: string
  startedAt: string | null
  completedAt: string | null
}