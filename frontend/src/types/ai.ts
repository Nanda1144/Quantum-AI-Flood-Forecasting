/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type ModelStatus = 'ready' | 'training' | 'degraded' | 'offline'

export type ServiceStatus = 'online' | 'degraded' | 'offline' | 'unavailable'

export type TrendDirection = 'up' | 'down' | 'flat'

export interface AIServiceHealth {
  status: ServiceStatus
  apiLatencyMs: number | null
  lastSuccessfulPrediction: string | null
  dataFreshness: string | null
}

export interface ForecastPoint {
  /** ISO timestamp for the point */
  timestamp: string
  /** Predicted water level in metres */
  predictedWaterLevel: number
  /** Observed / historical water level when available */
  observedWaterLevel?: number
  /** Flood probability 0..1 */
  floodProbability: number
}

export interface ThresholdLevels {
  /** Reference / alert threshold in metres, when provided by upstream */
  thresholdLevel?: number
  label?: string
}

export interface Forecast {
  forecastId: string
  floodProbability: number
  riskLevel: RiskLevel
  predictedWaterLevel: number
  forecastHorizon: string
  modelId: string
  modelVersion: string
  createdAt: string
  priority: 'low' | 'medium' | 'high' | 'critical'
}

export interface TrendPoint {
  timestamp: string
  value: number
}

export interface RiskDistribution {
  count: number
  riskLevel: RiskLevel
}

export interface RiskAnalytics {
  riskTrend: TrendPoint[]
  probabilityTrend: TrendPoint[]
  distribution: RiskDistribution[]
  summary: {
    high: number
    medium: number
    low: number
    critical: number
  }
  overallTrend: TrendDirection
}

export interface ModelMetrics {
  rmse?: number
  mae?: number
  nse?: number
  accuracy?: number
}

export interface ModelInfo {
  modelId: string
  name: string
  version: string
  algorithm: string
  lastTrainedAt: string
  lastEvaluatedAt: string
  status: ModelStatus
  metrics: ModelMetrics
  /**
   * True when the backend assembled this record from the forecast because the
   * model registry had no matching row — never mistaken for registry data.
   */
  derived?: boolean
}

export interface RecentPrediction {
  forecastId: string
  timestamp: string
  probability: number
  riskLevel: RiskLevel
  waterLevel: number
  modelId: string
  status: 'completed' | 'pending' | 'failed'
}

export interface OptimizationReadiness {
  forecastId: string
  riskScore: number
  priority: 'low' | 'medium' | 'high' | 'critical'
  candidateLocationsAvailable: boolean
  resourceConstraintsAvailable: boolean
  ready: boolean
}

export interface AISnapshot {
  forecast: Forecast
  forecastSeries: ForecastPoint[]
  thresholds: ThresholdLevels
  riskAnalytics: RiskAnalytics
  activeModel: ModelInfo
  recentPredictions: RecentPrediction[]
  optimizationReadiness: OptimizationReadiness
  systemHealth: AIServiceHealth
  updatedAt: string
}

export interface APIError {
  code: string
  message: string
  details?: unknown
}

export interface FetchState<T> {
  data: T | null
  loading: boolean
  error: APIError | null
  stale: boolean
  refetch: () => void
}

/* ------------------------------------------------------------------ */
/* Model comparison (registry-backed, backend-driven metrics)          */
/* ------------------------------------------------------------------ */

/** Deployment lifecycle of a registry version (model_versions.status). */
export type RegistryStatus = 'active' | 'retired' | 'development'

export type ComparisonSortKey = 'name' | 'evaluatedAt' | 'mae' | 'rmse' | 'r2' | 'inferenceTime'

/**
 * Every score the registry stores per version. Regression models populate
 * rmse/mae/r2/nse; classification models populate the 0..1 scores. The frontend
 * NEVER calculates metrics — it displays exactly what the backend returns.
 */
export interface ComparisonMetricScores {
  rmse?: number
  mae?: number
  r2?: number
  nse?: number
  accuracy?: number
  precision?: number
  recall?: number
  f1?: number
}

export interface ModelComparisonRow {
  /** Stable registry id (model_versions.id). */
  modelId: string
  name: string
  version: string
  algorithm: string
  status: RegistryStatus
  /** Training dataset lineage (dataset_reference). */
  dataset: string
  /** Stored artifact path when the version has one, else ''. */
  artifactReference: string
  /** Latest evaluation scores for this version (possibly empty). */
  metrics: ComparisonMetricScores
  /** Training wall-time in ms, when recorded. */
  trainingTimeMs?: number
  /** Per-sample inference latency in ms, when recorded. */
  inferenceTimeMs?: number
  /** Latest evaluation timestamp ('' when the version was never evaluated). */
  evaluatedAt: string
  /** Evaluation campaign lineage. */
  evaluationDataset: string
}

export interface ModelComparisonResult {
  items: ModelComparisonRow[]
  /** Min/max evaluatedAt across returned items; null when nothing is scored. */
  evaluatedRange: { from: string | null; to: string | null }
  /** Distinct evaluation campaigns touched by the returned items. */
  evaluationDatasets: string[]
}

export interface ModelComparisonQuery {
  sort?: ComparisonSortKey
  direction?: 'asc' | 'desc'
  from?: string
  to?: string
  status?: RegistryStatus
}

/** One historical evaluation run for a model version (GET /api/ai/models/:id/metrics). */
export interface ModelMetricsHistoryItem {
  metrics: ComparisonMetricScores
  trainingTimeMs?: number
  inferenceTimeMs?: number
  evaluatedAt: string
  evaluationDataset: string
}