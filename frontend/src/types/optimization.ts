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
  validationSummary: string
  qubo: QuboDocument
  measurementCounts: MeasurementCount[]
  energyHistory: EnergyPoint[]
  classicalComparison: ClassicalComparison
}

export type QuantumModalKind = 'qubo' | 'qaoa-job' | 'classical' | 'final-result' | 'export'

/** Pipeline events streamed to the UI while a job runs. */
export interface PipelineUpdate {
  stageId: PipelineStageId
  status: StageStatus
  error?: string
}