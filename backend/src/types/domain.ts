/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Backend domain types.
 *
 * These mirror the frontend contract (`frontend/src/types/ai.ts`) so the
 * dashboard renders directly from backend responses without translation. They
 * are assembled from the FastAPI contract (snake_case) by the service layer.
 */

import type {
  BestModelSelectionContract,
  ForecastContract,
  ModelComparisonQuery,
  ModelComparisonResultContract,
  ModelComparisonRowContract,
  ModelInfoContract,
  ModelMetricsHistoryItemContract,
  PredictionRecordContract,
  SelectionMetric,
  SelectionPolicyContract,
} from './contract.ts'

export interface Forecast {
  forecastId: string
  floodProbability: number
  riskLevel: ForecastContract['risk_level']
  predictedWaterLevel: number
  forecastHorizon: string
  modelId: string
  modelName: string
  modelVersion: string
  predictionTimestamp: string
  status: ForecastContract['status']
  priority: 'low' | 'medium' | 'high' | 'critical'
  /** When this row was stored in the backend database. */
  createdAt: string
}

export type RiskFilter = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface PredictionQuery {
  page: number
  limit: number
  from?: string
  to?: string
  risk?: RiskFilter
  modelId?: string
}

export interface Paginated<T> {
  items: T[]
  page: number
  limit: number
  total: number
  totalPages: number
}

export interface ModelInfo extends ModelInfoContract {}

export type ModelMetrics = ModelInfoContract['metrics']

export type ModelComparisonRow = ModelComparisonRowContract
export type ModelComparisonResult = ModelComparisonResultContract
export type { ModelComparisonQuery }

export type ModelMetricsHistoryItem = ModelMetricsHistoryItemContract
export type BestModelSelection = BestModelSelectionContract
export type SelectionPolicy = SelectionPolicyContract
export type { SelectionMetric }

/** Registry list query (`GET /api/ai/models`). */
export interface ModelRegistryQuery {
  status?: ModelComparisonRow['status']
  algorithm?: string
  dataset?: string
  page: number
  limit: number
}

/** Aggregated comparison of selected versions (`POST /api/ai/models/compare`). */
export interface CompareModelsResult {
  /** Each requested version, in request order, with its latest stored metrics. */
  models: ModelComparisonRow[]
  /** Policy selection; null when < minCandidates are scored on the policy metric. */
  bestModel: BestModelSelection | null
  /** The metric-selection policy that produced bestModel. */
  policy: SelectionPolicy
}

export interface OptimizationReference {
  id: string
  forecastId: string
  riskScore: number
  priority: 'low' | 'medium' | 'high' | 'critical'
  candidateLocationsAvailable: boolean
  resourceConstraintsAvailable: boolean
  ready: boolean
  createdAt: string
}

export interface SystemHealth {
  status: 'online' | 'degraded' | 'offline' | 'unavailable'
  apiLatencyMs: number | null
  lastSuccessfulPrediction: string | null
  dataFreshness: string | null
}

/**
 * The snapshot the frontend already consumes (`frontend/src/types/ai.ts`).
 * Every value originates from the AI FastAPI service and/or PostgreSQL — never
 * hard-coded in the backend. Field names are the frontend's camelCase contract.
 */
export interface AnalyticsSnapshot {
  forecast: ReportForecast
  forecastSeries: {
    timestamp: string
    predictedWaterLevel: number
    observedWaterLevel?: number
    floodProbability: number
  }[]
  thresholds: { thresholdLevel?: number; label?: string }
  riskAnalytics: {
    riskTrend: AnalyticsTrendPoint[]
    probabilityTrend: AnalyticsTrendPoint[]
    distribution: { riskLevel: RiskFilter; count: number }[]
    summary: { high: number; medium: number; low: number; critical: number }
    overallTrend: 'up' | 'down' | 'flat'
  }
  activeModel: {
    modelId: string
    name: string
    version: string
    algorithm: string
    status: ModelInfoContract['status']
    lastTrainedAt: string
    lastEvaluatedAt: string
    metrics: ModelInfoContract['metrics']
    /**
     * True when the registry has no row for the forecast's model, so the panel
     * is assembled from the forecast record instead of stored model metadata.
     * The frontend labels this so a fallback is never mistaken for registry data.
     */
    derived?: boolean
  }
  recentPredictions: {
    forecastId: string
    timestamp: string
    probability: number
    riskLevel: RiskFilter
    waterLevel: number
    modelId: string
    status: PredictionRecordContract['status']
  }[]
  optimizationReadiness: {
    forecastId: string
    riskScore: number
    priority: OptimizationReference['priority']
    candidateLocationsAvailable: boolean
    resourceConstraintsAvailable: boolean
    ready: boolean
  }
  systemHealth: SystemHealth
  updatedAt: string
}

export interface ReportForecast {
  forecastId: string
  floodProbability: number
  riskLevel: RiskFilter
  predictedWaterLevel: number
  forecastHorizon: string
  modelId: string
  modelName: string
  modelVersion: string
  predictionTimestamp: string
  status: ForecastContract['status']
  priority: Forecast['priority']
  createdAt: string
}

export interface AnalyticsTrendPoint {
  timestamp: string
  value: number
}