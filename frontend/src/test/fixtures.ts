/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These fixtures are realistic test data for the frontend suite only —
 * they are never shipped as production predictions and make no claim about the
 * real forecasting model's output.
 */

import type {
  AISnapshot,
  AIServiceHealth,
  ModelComparisonResult,
  ModelComparisonRow,
  RiskAnalytics,
} from '../types/ai'
import type { CandidateLocation, OptimizationResult, QuboFormulation } from '../types/optimization'
import type { QuantumJobSummary } from '../types/optimization'

export function buildRiskAnalytics(overrides: Partial<RiskAnalytics> = {}): RiskAnalytics {
  return {
    riskTrend: [
      { timestamp: '2026-09-20T08:00:00.000Z', value: 0.5 },
      { timestamp: '2026-09-20T10:00:00.000Z', value: 0.6 },
      { timestamp: '2026-09-20T12:00:00.000Z', value: 0.74 },
    ],
    probabilityTrend: [
      { timestamp: '2026-09-20T08:00:00.000Z', value: 0.6 },
      { timestamp: '2026-09-20T10:00:00.000Z', value: 0.66 },
      { timestamp: '2026-09-20T12:00:00.000Z', value: 0.74 },
    ],
    distribution: [
      { riskLevel: 'LOW', count: 12 },
      { riskLevel: 'HIGH', count: 4 },
    ],
    summary: { high: 4, medium: 6, low: 12, critical: 1 },
    overallTrend: 'up',
    ...overrides,
  }
}

export function buildSystemHealth(overrides: Partial<AIServiceHealth> = {}): AIServiceHealth {
  return {
    status: 'online',
    apiLatencyMs: 42,
    lastSuccessfulPrediction: '2026-09-21T08:00:00.000Z',
    dataFreshness: '90s',
    ...overrides,
  }
}

export function buildSnapshot(overrides: Partial<AISnapshot> = {}): AISnapshot {
  return {
    forecast: {
      forecastId: 'FC-20260921-0001',
      floodProbability: 0.74,
      riskLevel: 'HIGH',
      predictedWaterLevel: 7.82,
      forecastHorizon: '24h',
      modelId: 'MODEL001',
      modelVersion: 'v1.14.0',
      createdAt: '2026-09-21T08:00:00.000Z',
      priority: 'high',
    },
    forecastSeries: [
      { timestamp: '2026-09-20T08:00:00.000Z', predictedWaterLevel: 7.4, observedWaterLevel: 7.1, floodProbability: 0.6 },
      { timestamp: '2026-09-20T10:00:00.000Z', predictedWaterLevel: 7.6, observedWaterLevel: 7.3, floodProbability: 0.66 },
      { timestamp: '2026-09-20T12:00:00.000Z', predictedWaterLevel: 7.82, observedWaterLevel: 7.5, floodProbability: 0.74 },
    ],
    thresholds: { thresholdLevel: 8.0, label: 'Flood stage reference' },
    riskAnalytics: buildRiskAnalytics(),
    activeModel: {
      modelId: 'MODEL001',
      name: 'GRU FloodNet Ensemble',
      version: 'v1.14.0',
      algorithm: 'Gated Recurrent Unit ensemble + Bayesian calibration',
      lastTrainedAt: '2026-09-18T08:00:00.000Z',
      lastEvaluatedAt: '2026-09-21T06:00:00.000Z',
      status: 'ready',
      metrics: { rmse: 0.231, mae: 0.174, nse: 0.912, accuracy: 0.894 },
    },
    recentPredictions: [
      { forecastId: 'FC-20260921-0001', timestamp: '2026-09-21T08:00:00.000Z', probability: 0.74, riskLevel: 'HIGH', waterLevel: 7.82, modelId: 'MODEL001', status: 'completed' },
    ],
    optimizationReadiness: {
      forecastId: 'FC-20260921-0001',
      riskScore: 0.74,
      priority: 'high',
      candidateLocationsAvailable: true,
      resourceConstraintsAvailable: true,
      ready: true,
    },
    systemHealth: buildSystemHealth(),
    updatedAt: '2026-09-21T08:01:00.000Z',
    ...overrides,
  }
}

export function buildComparisonRows(overrides: Partial<ModelComparisonRow> & { name: string }): ModelComparisonRow {
  return {
    modelId: overrides.modelId ?? `cid-${overrides.name}`,
    name: overrides.name,
    version: overrides.version ?? 'v1.0',
    algorithm: overrides.algorithm ?? 'GRU',
    status: overrides.status ?? 'active',
    dataset: 'dev://comparison/training/panama-basin-2026',
    artifactReference: '',
    metrics: overrides.metrics ?? { rmse: 0.4, mae: 0.3, r2: 0.9 },
    evaluatedAt: overrides.evaluatedAt ?? '2026-08-01T10:00:00.000Z',
    evaluationDataset: 'dev://comparison/eval/gatun-basin-2026',
    ...(overrides.trainingTimeMs !== undefined && { trainingTimeMs: overrides.trainingTimeMs }),
    ...(overrides.inferenceTimeMs !== undefined && { inferenceTimeMs: overrides.inferenceTimeMs }),
  }
}

export function buildComparisonResult(rows: ModelComparisonRow[]): ModelComparisonResult {
  const evaluated = rows.map((row) => row.evaluatedAt).filter(Boolean).sort()
  return {
    items: rows,
    evaluatedRange: { from: evaluated[0] ?? null, to: evaluated[evaluated.length - 1] ?? null },
    evaluationDatasets: [...new Set(rows.map((row) => row.evaluationDataset).filter(Boolean))],
  }
}

export function buildQuboFormulation(overrides: Partial<QuboFormulation> = {}): QuboFormulation {
  const variables = ['SIT-001', 'SIT-002', 'SIT-003', 'SIT-004']
  const quadratic = [
    [0, -0.4, 0, 0],
    [0, 0, -0.25, 0],
    [0, 0, 0, -0.18],
    [0, 0, 0, 0],
  ]
  return {
    jobId: 'QOP-20260921-0001',
    problemType: 'sensor_placement',
    algorithm: 'qaoa',
    status: 'completed',
    createdAt: '2026-09-21T08:00:00.000Z',
    available: 'valid',
    storage: 'inline',
    inline: true,
    variableCount: variables.length,
    variables,
    expression: '1.2·x₀ + 0.9·x₁ − 0.4·x₀x₁ − 0.25·x₁x₂ + P·(Σxᵢ − 3)²',
    // Stored doc convention: N rows × 2N columns (quadratic row ‖ linear vector).
    matrix: quadratic.map((row) => [...row, 0.5, 0.4, 0.3, 0.2]),
    artifactReference: null,
    offset: 0,
    linear: [1.2, 0.9, 0.6, 0.4],
    quadratic,
    penaltyScale: 4.0,
    summary: {
      variables: variables.length,
      linearTerms: 4,
      quadraticTerms: 3,
      constraints: 1,
      penaltyStrength: 4.0,
    },
    constraints: [
      {
        key: 'sensor_limit',
        name: 'Sensor budget',
        configuredLimit: 3,
        penalty: 4.0,
        penaltyKind: 'qubo',
        status: 'satisfied',
        detail: 'At most 3 sensor sites selected in the decoded bitstring.',
      },
    ],
    penalties: [
      { key: 'cardinality', name: 'Cardinality', formula: 'P·(Σxᵢ − M)²', scale: 4.0, detail: 'Enforces exactly M=3 sensors.' },
    ],
    objective: {
      target: 'minimize',
      expression: 'Σ cᵢxᵢ − Σ Qᵢⱼxᵢxⱼ',
      explanation: 'Minimize weighted sensor cost while rewarding pairwise coverage overlap.',
    },
    variablesDetail: variables.map((id, index) => ({
      index,
      id,
      candidateId: id,
      name: `Sensor site ${index + 1}`,
      zone: 'Panama Basin',
      semantic: 'population',
      selected: index < 3,
    })),
    bitstring: '1110',
    selectedVariableIds: ['SIT-001', 'SIT-002', 'SIT-003'],
    hasResult: true,
    validationStatus: 'valid',
    validationSummary: 'QUBO constraints satisfied by the selected solution.',
    ...overrides,
  }
}

/**
 * Realistic gateway job summary for the Quantum Job Status page tests. Field
 * names mirror the backend contract verbatim — the tests prove the page renders
 * exactly what the payload carries and polls only while a job is live.
 */
export function buildQuantumJobSummary(overrides: Partial<QuantumJobSummary> = {}): QuantumJobSummary {
  return {
    id: 'QOP-20260921-0001',
    jobId: 'QOP-20260921-0001',
    status: 'completed',
    problemType: 'sensor_placement',
    algorithm: 'qaoa',
    executionMode: 'simulator',
    executionModeUsed: 'simulator',
    backend: 'qflare_simulator_statevector',
    backendUsed: 'qflare_simulator_statevector',
    fallbackPolicy: 'retry_simulator',
    fallbackApplied: false,
    fallbackReason: null,
    qubitCount: 4,
    validationStatus: null,
    validationSummary: null,
    resultSummary: {
      objectiveValue: 0.61,
      selectedCount: 3,
      executionTimeMs: 3.5,
      gapVsQuantum: 0,
      classicalObjectiveValue: 0.7,
      classicalRuntimeMs: 12,
      approximationQuality: 0.8714,
      validated: true,
      constraintViolationCount: 0,
    },
    owner: 'operator',
    createdAt: '2026-09-21T08:00:00.000Z',
    startedAt: '2026-09-21T08:00:01.000Z',
    completedAt: '2026-09-21T08:00:05.000Z',
    forecastReference: 'FC-20260921-0001',
    candidateReference: null,
    inputReference: 'ai://forecasts/FC-20260921-0001',
    variablesCount: 4,
    constraints: { maxSensors: 3, budgetK: null, coverageRequirements: [] },
    objectiveConfiguration: {
      weights: {
        risk: 0.2,
        populationCoverage: 0.2,
        infrastructureCoverage: 0.2,
        communication: 0.2,
        cost: 0.1,
        redundancy: 0.1,
      },
      normalizeWeights: true,
      layers: 2,
      shots: 1024,
    },
    quboStorage: 'inline',
    quboArtifactReference: null,
    errorMessage: null,
    deletedAt: null,
    deletedBy: null,
    deleteReason: null,
    ...overrides,
  }
}

/**
 * Stored result document served by GET /api/optimization/jobs/:id/result.
 * Field names mirror the gateway contract verbatim so the Optimization Result
 * page tests render the payload exactly as delivered.
 */
export function buildOptimizationResult(overrides: Partial<OptimizationResult> = {}): OptimizationResult {
  const jobId = 'QOP-20260921-0001'
  return {
    jobId,
    simulated: true,
    backend: 'aer_simulator_statevector',
    qubits: 4,
    shots: 1024,
    layers: 2,
    startedAt: '2026-09-21T08:00:01.000Z',
    endedAt: '2026-09-21T08:00:05.000Z',
    executionTimeMs: 3.5,
    objectiveValue: 0.61,
    objectiveBreakdown: [
      { key: 'risk', label: 'Risk', value: 0.35 },
      { key: 'populationCoverage', label: 'Population coverage', value: 0.3 },
      { key: 'infrastructureCoverage', label: 'Infrastructure coverage', value: 0.25 },
    ],
    selectedLocations: [
      { id: 'SIT-001', name: 'Sensor site 1', zone: 'Panama Basin', sensorCostK: 12, floodRisk: 0.82, populationCovered: 0.7, infrastructureCovered: 0.6 },
      { id: 'SIT-002', name: 'Sensor site 2', zone: 'Panama Basin', sensorCostK: 15, floodRisk: 0.75, populationCovered: 0.55, infrastructureCovered: 0.8 },
      { id: 'SIT-003', name: 'Sensor site 3', zone: 'Panama Basin', sensorCostK: 14, floodRisk: 0.8, populationCovered: 0.65, infrastructureCovered: 0.7 },
    ],
    coverage: null,
    constraintViolations: [],
    validationStatus: 'valid',
    validationSummary: 'QUBO constraints satisfied by the selected solution.',
    bitstring: '1110',
    qubo: {
      variableCount: 4,
      variables: ['SIT-001', 'SIT-002', 'SIT-003', 'SIT-004'],
      expression: 'Σcᵢxᵢ − ΣQᵢⱼxᵢxⱼ',
      matrix: [],
      offset: 0,
    },
    measurementCounts: [
      { bitstring: '1110', count: 728 },
      { bitstring: '1101', count: 148 },
      { bitstring: '0111', count: 148 },
    ],
    energyHistory: [
      { iteration: 1, energy: -0.52 },
      { iteration: 2, energy: -0.61 },
    ],
    classicalComparison: {
      method: 'exhaustive',
      objectiveValue: 0.7,
      selectedCount: 3,
      executionTimeMs: 12,
      gapVsQuantum: 0,
    },
    ...overrides,
  }
}

/**
 * Federated GIS candidate set matching `buildOptimizationResult`'s selection,
 * so the map and the location table render real geometry in the page tests.
 */
export function buildCandidateLocations(): CandidateLocation[] {
  return [
    { id: 'SIT-001', name: 'Sensor site 1', zone: 'Panama Basin', latitude: 9.1012, longitude: -79.4021, floodRisk: 0.82, populationExposure: 0.7, infrastructureCriticality: 0.6, communicationScore: 0.9, sensorCostK: 12, coverageRadiusKm: 4.5 },
    { id: 'SIT-002', name: 'Sensor site 2', zone: 'Panama Basin', latitude: 9.0524, longitude: -79.5104, floodRisk: 0.75, populationExposure: 0.55, infrastructureCriticality: 0.8, communicationScore: 0.8, sensorCostK: 15, coverageRadiusKm: 5.0 },
    { id: 'SIT-003', name: 'Sensor site 3', zone: 'Panama Basin', latitude: 9.1478, longitude: -79.3382, floodRisk: 0.8, populationExposure: 0.65, infrastructureCriticality: 0.7, communicationScore: 0.85, sensorCostK: 14, coverageRadiusKm: 4.2 },
    { id: 'SIT-004', name: 'Sensor site 4', zone: 'Panama Basin', latitude: 9.201, longitude: -79.445, floodRisk: 0.55, populationExposure: 0.4, infrastructureCriticality: 0.5, communicationScore: 0.7, sensorCostK: 10, coverageRadiusKm: 3.8 },
  ]
}