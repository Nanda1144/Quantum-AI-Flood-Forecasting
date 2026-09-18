/**
 * Contract consumed from the AI FastAPI service (`../ai-service`).
 *
 * Navya owns the forecasting models. She implements the FastAPI routes and may
 * swap XGBoost/LSTM/GRU freely; the backend depends only on the payload shapes
 * below. Field names are snake_case (as returned by the FastAPI contract).
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type ModelStatus = 'ready' | 'training' | 'degraded' | 'offline'
export type PredictionStatus = 'completed' | 'pending' | 'failed'
export type TrendDirection = 'up' | 'down' | 'flat'

export interface ForecastContract {
  forecast_id: string
  flood_probability: number
  risk_level: RiskLevel
  predicted_water_level: number
  forecast_horizon: string
  model_id: string
  model_version: string
  prediction_timestamp: string
  status: PredictionStatus
}

export interface ForecastPointContract {
  timestamp: string
  predicted_water_level: number
  observed_water_level?: number
  flood_probability: number
}

export interface SeriesContract {
  points: ForecastPointContract[]
}

export interface TrendPointContract {
  timestamp: string
  value: number
}

export interface RiskDistributionContract {
  risk_level: RiskLevel
  count: number
}

export interface RiskAnalyticsContract {
  risk_trend: TrendPointContract[]
  probability_trend: TrendPointContract[]
  distribution: RiskDistributionContract[]
  summary: { high: number; medium: number; low: number; critical: number }
  overall_trend: TrendDirection
}

export interface ModelMetricsContract {
  rmse?: number
  mae?: number
  nse?: number
  accuracy?: number
}

export interface ModelInfoContract {
  model_id: string
  name: string
  version: string
  algorithm: string
  status: ModelStatus
  last_trained_at: string
  last_evaluated_at: string
  metrics: ModelMetricsContract
}

/**
 * Deployment lifecycle of a registry version. Backed by the
 * `model_versions.status` CHECK constraint (see database/migrations/002).
 */
export type RegistryStatus = 'active' | 'retired' | 'development'

export type ComparisonSortKey = 'name' | 'evaluatedAt' | 'mae' | 'rmse' | 'r2' | 'inferenceTime'

/**
 * Every score the registry stores per version. Regression models populate
 * rmse/mae/r2/nse; classification models populate the 0..1 scores. The backend
 * returns exactly what was stored — nothing is derived.
 */
export interface ModelComparisonMetricScores {
  rmse?: number
  mae?: number
  r2?: number
  nse?: number
  accuracy?: number
  precision?: number
  recall?: number
  f1?: number
}

export interface ModelComparisonRowContract {
  /** Stable registry id (`model_versions.id`). */
  modelId: string
  name: string
  version: string
  algorithm: string
  status: RegistryStatus
  /** Training dataset lineage (`dataset_reference`). */
  dataset: string
  /** Stored artifact path when the version has one, else ''. */
  artifactReference: string
  /** Latest evaluation scores for this version (possibly empty). */
  metrics: ModelComparisonMetricScores
  /** Training wall-time in ms, when recorded. */
  trainingTimeMs?: number
  /** Per-sample inference latency in ms, when recorded. */
  inferenceTimeMs?: number
  /** Latest evaluation timestamp ('' when the version was never evaluated). */
  evaluatedAt: string
  /** Evaluation campaign lineage. */
  evaluationDataset: string
  /** Lifecycle timestamps for the full metadata view (model detail). */
  trainingStartedAt?: string | null
  trainingCompletedAt?: string | null
  deployedAt?: string | null
  createdAt?: string
  updatedAt?: string
}

export interface ModelComparisonResultContract {
  items: ModelComparisonRowContract[]
  /** Min/max `evaluatedAt` across returned items; null when nothing is scored. */
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

/**
 * One historical metric row for a registry version
 * (`GET /api/ai/models/:id/metrics`). Exactly the stored columns — nothing
 * derived.
 */
export interface ModelMetricsHistoryItemContract {
  metrics: ModelComparisonMetricScores
  trainingTimeMs?: number
  inferenceTimeMs?: number
  /** Evaluation campaign lineage for this run. */
  evaluationDataset: string
  /** When this evaluation ran (ISO). */
  evaluatedAt: string
}

/**
 * Metrics the documented model-selection policy can rank on. Not every model
 * will carry every metric — scoring is regression (rmse/mae/r2/nse) or
 * latency (inferenceTime).
 */
export type SelectionMetric = 'mae' | 'rmse' | 'r2' | 'nse' | 'inferenceTime'

/** The effective selection policy used to pick `bestModel` in a comparison. */
export interface SelectionPolicyContract {
  /** Metric ranked first. Configurable via MODEL_SELECTION_METRIC. */
  primaryMetric: SelectionMetric
  /** Whether a higher primary-metric value is better. */
  higherIsBetter: boolean
  /**
   * Ordering used to break ties on the primary metric (best first). Always
   * excludes the primary metric itself.
   */
  tieBreakers: SelectionMetric[]
  /** Comparisons with fewer scored candidates than this yield no bestModel. */
  minCandidates: number
}

/** A policy-selected "best model" from a comparison. */
export interface BestModelSelectionContract {
  modelId: string
  name: string
  version: string
  /** Metric that decided the selection (the policy's primary metric). */
  metric: SelectionMetric
  /** Value of the deciding metric for this model. */
  score: number
  /** Human-readable trace of the decision (metric, tie-breaks, exclusions). */
  rationale: string
}

export interface PredictionRecordContract {
  forecast_id: string
  timestamp: string
  probability: number
  risk_level: RiskLevel
  water_level: number
  model_id: string
  status: PredictionStatus
}

export interface AIHealthContract {
  service: string
  version: string
  engine: string
  status: 'online' | 'offline'
}

/** Envelope returned by the FastAPI service for every endpoint. */
export interface AIServiceEnvelope<T> {
  success: boolean
  data: T
  error?: { code: string; message: string }
  timestamp: string
}