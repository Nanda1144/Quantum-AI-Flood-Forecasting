/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * API client for the forecast record.
 *
 * ## Why this does not modify `aiService.ts`
 *
 * `services/aiService.ts` is team-owned and stays exactly as it is. It exposes
 * `fetchJson` — auth headers, timeout, 401 handling, error normalisation — which
 * is the whole transport concern, so this client reuses it rather than
 * reimplementing it. That is a deliberate trade: a second `fetch` wrapper is one
 * more place to get 401 handling wrong.
 *
 * ## The one behaviour this client does NOT inherit
 *
 * `loadAIAnalytics()` falls back to clearly-flagged sample data when the backend
 * is unreachable. That is a reasonable choice for a demo dashboard, and this
 * client does not use it, for a specific reason:
 *
 * the component renders **provenance and evaluation status**. A sample
 * snapshot's `activeModel.metrics` is invented, and a component whose entire job
 * is to say "this number is not trustworthy" cannot itself be fed invented
 * numbers — the failure would be invisible and self-contradictory.
 *
 * So this client surfaces the error and lets the UI render an honest empty state.
 * The sample-data path remains available to the team dashboard, untouched.
 *
 * ## Not yet on the wire
 *
 * The provenance, threshold-policy and held-out-metric fields below are **not**
 * carried by the running AI contract. They require a team owner to extend
 * `ai-service/app/schemas/models.py`. Until then the normalizer records them as
 * `null` / `'unknown'` rather than deriving them — see
 * `docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`.
 */

import { fetchJson } from '../../services/aiService'
import type { APIError, RiskLevel } from '../../types/ai'
import type {
  ForecastBacktestPoint,
  ForecastDatasetType,
  ForecastRecord,
  ForecastTarget,
  ForecastMetricProvenance,
  ForecastModelComparison,
  ForecastModelComparisonRow,
  ForecastProvenance,
  ForecastRegressionMetrics,
  ForecastSplitLabel,
  ForecastThresholdPolicy,
} from './types'

/** Raw shapes the running contract actually sends, before normalisation. */
interface RawForecastPayload {
  forecast_id: string
  prediction_timestamp: string
  forecast_horizon: string
  model_id: string
  model_version: string
  status: 'completed' | 'pending' | 'failed'
  predicted_water_level: number
  flood_probability: number
  risk_level: RiskLevel
  threshold_level?: number | null
  threshold_label?: string | null
}

const asString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() !== '' ? value : null

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

/**
 * `thresholdPolicyFrom` — pending on every path.
 *
 * The running contract has no field for formal approval, so the only honest
 * reading of a bare threshold is "unapproved". Inferring sign-off from the
 * absence of a disclaimer would be reading an approval into silence.
 */
function thresholdPolicyFrom(label: string | null, level: number | null): ForecastThresholdPolicy {
  if (label !== null && /not official|pending|unapproved/i.test(label)) return 'pending'
  if (level !== null) return 'pending'
  return 'pending'
}

function normaliseProvenance(raw: RawForecastPayload): ForecastProvenance {
  return {
    datasetReference: null,
    // The running contract carries no lineage at all. 'unknown' is the only
    // honest value; 'real' would assert a data origin nobody sent.
    datasetType: 'unknown',
    datasetLicense: null,
    datasetChecksum: null,
    samplingInterval: null,
    stationReference: null,
    target: 'water_level',
    targetUnits: null,
    forecastHorizonHours: parseHorizonHours(raw.forecast_horizon),
    leadTimeRows: 0,
    modelId: raw.model_id,
    modelVersion: raw.model_version,
    contractVersion: 'unknown',
    featureList: [],
    disclaimer: null,
    metricsLabel: null,
    missingFields: [],
  }
}

function normaliseMetrics(raw: unknown): ForecastRegressionMetrics | null {
  if (raw === null || typeof raw !== 'object') return null
  const m = raw as Record<string, unknown>
  const mae = asNumber(m.mae)
  const rmse = asNumber(m.rmse)
  const r2 = asNumber(m.r2)
  const nse = asNumber(m.nse)
  const peak = asNumber(m.peakAbsoluteError)
  const bias = asNumber(m.bias)
  const n = asNumber(m.nSamples)
  // A partial metric set is not a metric set. Returning null here means the UI
  // shows "no metrics were measured" rather than four confident numbers and a
  // hole where the fifth should be.
  if (mae === null || rmse === null || r2 === null || nse === null || peak === null) return null
  return {
    mae,
    rmse,
    r2,
    nse,
    peakAbsoluteError: peak,
    bias: bias ?? 0,
    nSamples: n ?? 0,
  }
}

function normaliseMetricProvenance(raw: unknown): ForecastMetricProvenance | null {
  if (raw === null || typeof raw !== 'object') return null
  const m = raw as Record<string, unknown>
  const split = m.split
  if (split !== 'train' && split !== 'validation' && split !== 'test') return null
  return { split, isSelectionStatistic: m.isSelectionStatistic === true }
}

function normaliseBacktest(raw: unknown): ForecastBacktestPoint[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item): ForecastBacktestPoint[] => {
    if (item === null || typeof item !== 'object') return []
    const p = item as Record<string, unknown>
    const timestamp = asString(p.timestamp)
    const originTimestamp = asString(p.originTimestamp)
    const predicted = asNumber(p.predicted)
    const observed = asNumber(p.observed)
    const probability = asNumber(p.floodProbability)
    // A backtest point with a missing field is not a backtest point. Dropping it
    // here means the count on screen is the count of complete pairs.
    if (
      timestamp === null ||
      originTimestamp === null ||
      predicted === null ||
      observed === null ||
      probability === null
    ) {
      return []
    }
    return [
      {
        timestamp,
        originTimestamp,
        predicted,
        observed,
        floodProbability: probability,
        riskLevel: (asString(p.riskLevel) ?? 'LOW') as RiskLevel,
      },
    ]
  })
}

/**
 * Build a forecast record from a raw payload, recording everything the transport
 * dropped as `null` rather than inferring it.
 */
export function toForecastRecord(raw: RawForecastPayload): ForecastRecord {
  const thresholdLevel = asNumber(raw.threshold_level)
  const thresholdLabel = asString(raw.threshold_label)
  return {
    forecastId: raw.forecast_id,
    forecastTimestamp: raw.prediction_timestamp,
    forecastHorizon: raw.forecast_horizon,
    modelId: raw.model_id,
    modelVersion: raw.model_version,
    status: raw.status,
    target: 'water_level' satisfies ForecastTarget,
    predictedValue: raw.predicted_water_level,
    predictedWaterLevel: raw.predicted_water_level,
    predictedInflow: null,
    floodProbability: raw.flood_probability,
    riskLevel: raw.risk_level,
    riskScore: raw.flood_probability,
    threshold: thresholdLevel,
    thresholdPolicy: thresholdPolicyFrom(thresholdLabel, thresholdLevel),
    thresholdSource: thresholdLabel,
    residualSigma: null,
    provenance: normaliseProvenance(raw),
    metrics: normaliseMetrics((raw as unknown as Record<string, unknown>).metrics),
    metricProvenance: normaliseMetricProvenance(
      (raw as unknown as Record<string, unknown>).metricProvenance,
    ),
    backtest: normaliseBacktest((raw as unknown as Record<string, unknown>).backtest),
  }
}

/** Parse `'6h'` into `6`. Unparseable input returns 0, never a guessed default. */
export function parseHorizonHours(horizon: string): number {
  const match = /^(\d+(?:\.\d+)?)\s*h$/i.exec(horizon.trim())
  if (match === null) return 0
  const value = Number.parseFloat(match[1])
  return Number.isFinite(value) ? value : 0
}

function normaliseRow(raw: unknown): ForecastModelComparisonRow {
  const r = (raw ?? {}) as Record<string, unknown>
  const key = asString(r.key) ?? asString(r.modelId) ?? 'unknown'
  const executed = r.executed === true
  const unavailable = asString(r.unavailableReason)
  return {
    key,
    displayName: asString(r.displayName) ?? asString(r.name) ?? key,
    algorithm: asString(r.algorithm) ?? '',
    executed,
    rmse: asNumber(r.rmse),
    mae: asNumber(r.mae),
    r2: asNumber(r.r2),
    nse: asNumber(r.nse),
    nSamples: asNumber(r.nSamples),
    selected: r.selected === true,
    unavailableReason: executed ? null : unavailable,
    metricsLabel: asString(r.metricsLabel) ?? 'no label recorded',
  }
}

/**
 * Normalise a comparison payload.
 *
 * Throws rather than returning a partially-normalised comparison when no
 * candidate carries a score: a table of dashes is indistinguishable from a table
 * of zeroes at a glance, and the reader has no way to tell which they are.
 */
export function toForecastModelComparison(raw: unknown): ForecastModelComparison {
  const r = (raw ?? {}) as Record<string, unknown>
  const rows = Array.isArray(r.rows) ? r.rows.map(normaliseRow) : []
  const selectionSplit = asString(r.selectionSplit) as ForecastSplitLabel | null
  const heldOutSplit = asString(r.heldOutSplit) as ForecastSplitLabel | null
  return {
    selectionSplit: selectionSplit ?? 'validation',
    heldOutSplit: heldOutSplit ?? 'test',
    selectionMetric: asString(r.selectionMetric) ?? 'rmse',
    selectedKey: asString(r.selectedKey) ?? '',
    rows,
    metricsLabel: asString(r.metricsLabel) ?? 'no label recorded',
    heldOutScored: r.heldOutScored === true,
  }
}

export const forecastApi = {
  /** GET /api/ai/forecast — the team's endpoint, read without modification. */
  getLatest: () => fetchJson<RawForecastPayload>('/api/ai/forecast'),

  /** GET /api/ai/models/comparison — registry scores, never derived here. */
  getComparison: () => fetchJson<unknown>('/api/ai/models/comparison'),
}

/**
 * Load the forecast record.
 *
 * Unlike `loadAIAnalytics()`, this never falls back to sample data. A failure is
 * a failure, and the dashboard renders an honest error state instead of invented
 * numbers.
 */
export async function loadForecast(): Promise<ForecastRecord> {
  const raw = await forecastApi.getLatest()
  return toForecastRecord(raw)
}

/**
 * Load the comparison, or return `null` when it is unavailable.
 *
 * `null` rather than a throw: a missing comparison should not stop the forecast
 * itself from being shown, and the UI states which part failed.
 */
export async function loadForecastComparison(): Promise<ForecastModelComparison | null> {
  try {
    return toForecastModelComparison(await forecastApi.getComparison())
  } catch (error) {
    if ((error as APIError).code === 'UNAUTHORIZED') throw error
    return null
  }
}

export type { RawForecastPayload, ForecastDatasetType }
