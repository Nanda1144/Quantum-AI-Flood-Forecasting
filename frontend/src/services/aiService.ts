/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type {
  AISnapshot,
  APIError,
  Forecast,
  ModelComparisonQuery,
  ModelComparisonResult,
  ModelComparisonRow,
  ModelInfo,
  RecentPrediction,
  RiskAnalytics,
  AIServiceHealth,
  OptimizationReadiness,
} from '../types/ai'
import { authHeaders, notifyUnauthorized } from './authService'

/** Base URL for the Node backend. Empty string = same origin (Vite dev proxy -> :3000). */
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * Whether the clearly-flagged sample-data fallback is enabled. Evaluated at
 * call time so tests/env can toggle it. Production builds never allow mock
 * data regardless of VITE_USE_MOCK_DATA.
 */
export function shouldAllowMockData(): boolean {
  return import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_DATA !== 'false'
}

const REQUEST_TIMEOUT_MS = 6000

function toError(error: unknown): APIError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    return error as APIError
  }
  return { code: 'API_ERROR', message: 'Request to the AI service failed' }
}

async function fetchJson<T>(path: string, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      signal: controller.signal,
      headers: { Accept: 'application/json', ...authHeaders() },
    })
    if (response.status === 401) {
      notifyUnauthorized()
      throw { code: 'UNAUTHORIZED', message: 'Session expired or not authenticated — please sign in' } satisfies APIError
    }
    if (!response.ok) {
      let message = `Request to ${path} failed with status ${response.status}`
      let code = 'HTTP_ERROR'
      try {
        const body = (await response.json()) as { error?: { code?: string; message?: string } }
        if (body?.error?.message) {
          message = body.error.message
          code = body.error.code ?? code
        }
      } catch {
        /* non-JSON error body, keep defaults */
      }
      throw { code, message }
    }
    const body = (await response.json()) as { data?: unknown }
    return (body.data ?? body) as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw { code: 'TIMEOUT', message: `Request to ${path} timed out` } satisfies APIError
    }
    throw toError(error)
  } finally {
    clearTimeout(timer)
  }
}

/* ------------------------------------------------------------------ */
/* Sample-data fallback. Used only when the backend is unreachable and */
/* VITE_USE_MOCK_DATA is not set to false. Clearly flagged as mock.     */
/* ------------------------------------------------------------------ */

const round = (value: number, digits = 2): number => {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 36e5).toISOString()
}

function buildSeries() {
  const points = []
  for (let i = 23; i >= 0; i -= 1) {
    const progress = (23 - i) / 23
    const base = 6.9 + progress * 0.9
    const predictedWaterLevel = round(base + Math.sin(i / 2.2) * 0.12)
    const observedWaterLevel = round(base - 0.35 + Math.sin(i / 3) * 0.15)
    const floodProbability = round(Math.min(0.93, 0.55 + progress * 0.37 + Math.sin(i / 2.8) * 0.05))
    points.push({
      timestamp: hoursAgo(23 - i),
      predictedWaterLevel,
      observedWaterLevel,
      floodProbability,
    })
  }
  return points
}

function buildTrend(initial: number, deltas: number[]): { timestamp: string; value: number }[] {
  let value = initial
  return deltas.map((delta, index) => {
    value = Math.min(0.96, Math.max(0.05, value + delta))
    return { timestamp: hoursAgo(deltas.length - 1 - index), value: round(value) }
  })
}

function buildRiskTrend(): { timestamp: string; value: number }[] {
  const deltas = [0, 0.02, -0.01, 0.03, 0.02, 0.04, -0.02, 0.03, 0.03, 0.05, 0.04, 0.06]
  return buildTrend(0.5, deltas)
}

function buildProbabilityTrend(): { timestamp: string; value: number }[] {
  const deltas = [0.02, 0.01, 0.03, -0.02, 0.04, 0.02, 0.05, -0.01, 0.06, 0.03, 0.07, 0.04]
  return buildTrend(0.42, deltas)
}

function buildMockSnapshot(): AISnapshot {
  const now = new Date().toISOString()
  const forecast: Forecast = {
    forecastId: 'FC-2409-0187',
    floodProbability: 0.91,
    riskLevel: 'HIGH',
    predictedWaterLevel: 7.82,
    forecastHorizon: '6h',
    modelId: 'MODEL001',
    modelVersion: 'v1.2',
    createdAt: hoursAgo(0.33),
    priority: 'high',
  }

  const riskAnalytics: RiskAnalytics = {
    riskTrend: buildRiskTrend(),
    probabilityTrend: buildProbabilityTrend(),
    distribution: [
      { riskLevel: 'LOW', count: 11 },
      { riskLevel: 'MEDIUM', count: 8 },
      { riskLevel: 'HIGH', count: 6 },
      { riskLevel: 'CRITICAL', count: 2 },
    ],
    summary: { high: 6, medium: 8, low: 11, critical: 2 },
    overallTrend: 'up',
  }

  const activeModel: ModelInfo = {
    modelId: 'MODEL001',
    name: 'GRU FloodNet Ensemble',
    version: 'v1.2',
    algorithm: 'Gated Recurrent Unit Ensemble',
    lastTrainedAt: hoursAgo(72),
    lastEvaluatedAt: hoursAgo(6),
    status: 'ready',
    metrics: { rmse: 0.24, mae: 0.18, nse: 0.91, accuracy: 0.89 },
  }

  const recentPredictions: RecentPrediction[] = [
    { forecastId: 'FC-2409-0187', timestamp: hoursAgo(0.33), probability: 0.91, riskLevel: 'HIGH', waterLevel: 7.82, modelId: 'MODEL001', status: 'completed' },
    { forecastId: 'FC-2409-0186', timestamp: hoursAgo(1.33), probability: 0.87, riskLevel: 'HIGH', waterLevel: 7.61, modelId: 'MODEL001', status: 'completed' },
    { forecastId: 'FC-2409-0185', timestamp: hoursAgo(2.33), probability: 0.78, riskLevel: 'MEDIUM', waterLevel: 7.22, modelId: 'MODEL002', status: 'completed' },
    { forecastId: 'FC-2409-0184', timestamp: hoursAgo(3.33), probability: 0.81, riskLevel: 'HIGH', waterLevel: 7.35, modelId: 'MODEL001', status: 'completed' },
    { forecastId: 'FC-2409-0183', timestamp: hoursAgo(4.33), probability: 0.69, riskLevel: 'MEDIUM', waterLevel: 6.98, modelId: 'MODEL001', status: 'completed' },
    { forecastId: 'FC-2409-0182', timestamp: hoursAgo(5.33), probability: 0.62, riskLevel: 'MEDIUM', waterLevel: 6.74, modelId: 'MODEL002', status: 'failed' },
  ]

  const optimizationReadiness: OptimizationReadiness = {
    forecastId: 'FC-2409-0187',
    riskScore: 0.91,
    priority: 'high',
    candidateLocationsAvailable: true,
    resourceConstraintsAvailable: true,
    ready: true,
  }

  const systemHealth: AIServiceHealth = {
    status: 'online',
    apiLatencyMs: 42,
    lastSuccessfulPrediction: hoursAgo(0.33),
    dataFreshness: '90s',
  }

  return {
    forecast,
    forecastSeries: buildSeries(),
    thresholds: {},
    riskAnalytics,
    activeModel,
    recentPredictions,
    optimizationReadiness,
    systemHealth,
    updatedAt: now,
  }
}

let mockCache: AISnapshot | null = null

function getMockSnapshot(): AISnapshot {
  const base = mockCache ?? buildMockSnapshot()
  mockCache = { ...base, updatedAt: new Date().toISOString() }
  return mockCache
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

export interface AILoadResult {
  snapshot: AISnapshot
  isMock: boolean
}

const EMPTY_RISK: RiskAnalytics = {
  riskTrend: [],
  probabilityTrend: [],
  distribution: [],
  summary: { high: 0, medium: 0, low: 0, critical: 0 },
  overallTrend: 'flat',
}

/**
 * Ensures a raw backend payload satisfies the full AISnapshot contract.
 *
 * The snapshot is runtime JSON — a partial/stale response must never be able
 * to crash consumers (e.g. "Cannot read properties of undefined (reading
 * 'status')"). Missing optional slices default to safe empty values.
 */
function normalizeSnapshot(raw: AISnapshot): AISnapshot {
  if (!raw.forecast) {
    throw new Error('Analytics response did not include a forecast')
  }
  const risk = raw.riskAnalytics
  return {
    forecast: raw.forecast,
    forecastSeries: raw.forecastSeries ?? [],
    thresholds: raw.thresholds ?? {},
    riskAnalytics: risk
      ? {
          riskTrend: risk.riskTrend ?? [],
          probabilityTrend: risk.probabilityTrend ?? [],
          distribution: risk.distribution ?? [],
          summary: risk.summary ?? EMPTY_RISK.summary,
          overallTrend: risk.overallTrend ?? 'flat',
        }
      : EMPTY_RISK,
    activeModel: raw.activeModel,
    recentPredictions: raw.recentPredictions ?? [],
    optimizationReadiness: raw.optimizationReadiness,
    systemHealth: raw.systemHealth ?? {
      status: 'offline',
      apiLatencyMs: null,
      lastSuccessfulPrediction: null,
      dataFreshness: null,
    },
    updatedAt: raw.updatedAt ?? new Date().toISOString(),
  }
}

/**
 * Loads the full AI analytics snapshot.
 *
 * Prefers the backend composite endpoint GET /api/ai/analytics. When the
 * backend is unavailable and sample data is allowed, falls back to clearly
 * flagged sample data so the dashboard remains demonstrable.
 */
export async function loadAIAnalytics(): Promise<AILoadResult> {
  try {
    const snapshot = normalizeSnapshot(await fetchJson<AISnapshot>('/api/ai/analytics'))
    return { snapshot, isMock: false }
  } catch (error) {
    // A 401 is an auth problem, never a connection problem — surface it so the
    // session is cleared and the login screen returns instead of silently
    // showing local sample data while still appearing authenticated.
    if (shouldAllowMockData() && (error as APIError).code !== 'UNAUTHORIZED') {
      // Small delay so the loading skeleton is visible and state transitions are observable.
      await new Promise((resolve) => setTimeout(resolve, 700))
      return { snapshot: normalizeSnapshot(getMockSnapshot()), isMock: true }
    }
    throw error
  }
}

/* Individual endpoints surfaced for future reuse. */
export type RiskFilter = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface PredictionsQuery {
  page?: number
  limit?: number
  from?: string
  to?: string
  risk?: RiskFilter
  model?: string
}

/** Paginated shape returned by GET /api/ai/predictions. */
export interface PaginatedPredictions {
  items: RecentPrediction[]
  page: number
  limit: number
  total: number
  totalPages: number
}

/** Listing returned by GET /api/ai/models. */
export interface ModelsListing {
  models: ModelInfo[]
  activeModelId: string | null
}

/**
 * Ensures a comparison payload satisfies the contract so consumers never read
 * missing fields (same defensive intent as `normalizeSnapshot`). Metric values
 * are passed through untouched — nothing is derived here.
 */
function normalizeModelComparison(raw: ModelComparisonResult): ModelComparisonResult {
  const items = (Array.isArray(raw.items) ? raw.items : []).map((row) => ({
    modelId: row.modelId ?? '',
    name: row.name ?? '',
    version: row.version ?? '',
    algorithm: row.algorithm ?? '',
    status: row.status ?? 'development',
    dataset: row.dataset ?? '',
    artifactReference: row.artifactReference ?? '',
    metrics: row.metrics ?? {},
    ...(typeof row.trainingTimeMs === 'number' && { trainingTimeMs: row.trainingTimeMs }),
    ...(typeof row.inferenceTimeMs === 'number' && { inferenceTimeMs: row.inferenceTimeMs }),
    evaluatedAt: row.evaluatedAt ?? '',
    evaluationDataset: row.evaluationDataset ?? '',
  }))
  return {
    items,
    evaluatedRange: raw.evaluatedRange ?? { from: null, to: null },
    evaluationDatasets: Array.isArray(raw.evaluationDatasets) ? raw.evaluationDatasets : [],
  }
}

export const aiApi = {
  getStatus: () => fetchJson<AIServiceHealth>('/api/ai/status'),
  getPredictions: (query: PredictionsQuery = {}) => {
    const params = new URLSearchParams()
    if (query.page !== undefined) params.set('page', String(query.page))
    if (query.limit !== undefined) params.set('limit', String(query.limit))
    if (query.from) params.set('from', query.from)
    if (query.to) params.set('to', query.to)
    if (query.risk) params.set('risk', query.risk)
    if (query.model) params.set('model', query.model)
    const qs = params.toString()
    return fetchJson<PaginatedPredictions>(`/api/ai/predictions${qs ? `?${qs}` : ''}`)
  },
  getModels: () => fetchJson<ModelsListing>('/api/ai/models'),
  getModelMetrics: (modelId: string) =>
    fetchJson<ModelInfo['metrics']>(`/api/ai/models/${encodeURIComponent(modelId)}/metrics`),
  getModelsComparison: async (query: ModelComparisonQuery = {}) => {
    const params = new URLSearchParams()
    if (query.sort) params.set('sort', query.sort)
    if (query.direction) params.set('direction', query.direction)
    if (query.from) params.set('from', query.from)
    if (query.to) params.set('to', query.to)
    if (query.status) params.set('status', query.status)
    const qs = params.toString()
    const raw = await fetchJson<ModelComparisonResult>(`/api/ai/models/comparison${qs ? `?${qs}` : ''}`)
    return normalizeModelComparison(raw)
  },
}

/* ------------------------------------------------------------------ */
/* Sample-data fallback for the comparison page. Mirror of the         */
/* analytics fallback: real backend rows are the primary path; when    */
/* the backend is unreachable (or rejects the request) and sample data */
/* is allowed, clearly-labelled local rows keep the page demonstrable. */
/* ------------------------------------------------------------------ */

function buildMockComparisonResult(): ModelComparisonResult {
  const items: ModelComparisonRow[] = [
    {
      modelId: 'SAMPLE-001',
      name: 'GRU FloodNet Ensemble',
      version: 'v1.2',
      algorithm: 'Gated Recurrent Unit Ensemble',
      status: 'active',
      dataset: 'sample://training/panama-basin-2026',
      artifactReference: 'sample://artifacts/GRU-FloodNet-v1.2',
      metrics: { rmse: 0.21, mae: 0.16, r2: 0.93, nse: 0.91 },
      trainingTimeMs: 3600000,
      inferenceTimeMs: 3,
      evaluatedAt: hoursAgo(6),
      evaluationDataset: 'sample://eval/gatun-basin-2026',
    },
    {
      modelId: 'SAMPLE-002',
      name: 'Deep-Transformer',
      version: 'v2.0-dev',
      algorithm: 'Temporal Transformer',
      status: 'development',
      dataset: 'sample://training/panama-basin-2026',
      artifactReference: 'sample://artifacts/Deep-Transformer-v2.0-dev',
      metrics: { rmse: 0.149, mae: 0.112, r2: 0.979, nse: 0.976 },
      trainingTimeMs: 5400000,
      inferenceTimeMs: 1,
      evaluatedAt: hoursAgo(12),
      evaluationDataset: 'sample://eval/gatun-basin-2026',
    },
    {
      modelId: 'SAMPLE-003',
      name: 'XGBoost-Rainfall',
      version: 'v1.0',
      algorithm: 'Gradient Boosted Trees',
      status: 'active',
      dataset: 'sample://training/gatun-basin-2026',
      artifactReference: 'sample://artifacts/XGBoost-Rainfall-v1.0',
      metrics: { rmse: 0.27, mae: 0.21, r2: 0.88, nse: 0.87 },
      trainingTimeMs: 900000,
      inferenceTimeMs: 1,
      evaluatedAt: hoursAgo(48),
      evaluationDataset: 'sample://eval/gatun-basin-2026',
    },
    {
      modelId: 'SAMPLE-004',
      name: 'CNN-Rainfall',
      version: 'v2.1-dev',
      algorithm: '1D Temporal CNN',
      status: 'development',
      dataset: 'sample://training/panama-basin-2026',
      artifactReference: 'sample://artifacts/CNN-Rainfall-v2.1-dev',
      metrics: { rmse: 0.441, mae: 0.332, r2: 0.847, nse: 0.847 },
      trainingTimeMs: 2680000,
      inferenceTimeMs: 1,
      evaluatedAt: hoursAgo(24),
      evaluationDataset: 'sample://eval/panama-basin-2026',
    },
    {
      modelId: 'SAMPLE-005',
      name: 'LSTM Cascade',
      version: 'v1.1',
      algorithm: 'Stacked LSTM',
      status: 'retired',
      dataset: 'sample://training/gatun-basin-2026',
      artifactReference: 'sample://artifacts/LSTM-Cascade-v1.1',
      metrics: { rmse: 0.38, mae: 0.29, r2: 0.81, nse: 0.8 },
      trainingTimeMs: 4200000,
      inferenceTimeMs: 5,
      evaluatedAt: hoursAgo(120),
      evaluationDataset: 'sample://eval/gatun-basin-2026',
    },
  ]
  const evaluated = items.map((row) => row.evaluatedAt).filter(Boolean).sort()
  return {
    items,
    evaluatedRange: { from: evaluated[0] ?? null, to: evaluated[evaluated.length - 1] ?? null },
    evaluationDatasets: [...new Set(items.map((row) => row.evaluationDataset).filter(Boolean))],
  }
}

export interface ComparisonLoadResult {
  result: ModelComparisonResult
  isMock: boolean
}

/**
 * Loads model comparison for the given query.
 *
 * Prefers the backend endpoint GET /api/ai/models/comparison. When the backend
 * is unavailable (or rejects the request) and sample data is allowed, falls
 * back to clearly flagged local rows so the page remains demonstrable. Sample
 * rows carry `sample://` lineage and are surfaced to the UI as sample data.
 */
export async function loadModelComparison(query: ModelComparisonQuery = {}): Promise<ComparisonLoadResult> {
  try {
    const result = await aiApi.getModelsComparison(query)
    return { result, isMock: false }
  } catch (error) {
    // Auth rejections surface instead of swapping to sample rows — access control
    // must stay real (see loadAIAnalytics).
    if (shouldAllowMockData() && (error as APIError).code !== 'UNAUTHORIZED') {
      // Small delay so the loading skeleton is visible and state transitions are observable.
      await new Promise((resolve) => setTimeout(resolve, 500))
      return { result: buildMockComparisonResult(), isMock: true }
    }
    throw error
  }
}

export { fetchJson }