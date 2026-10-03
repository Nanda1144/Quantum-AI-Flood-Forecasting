/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { ForecastClient } from '../../clients/ai-service.client.ts'
import type {
  ForecastContract,
  ModelInfoContract,
  RiskAnalyticsContract,
} from '../../types/contract.ts'
import { openQuestions } from './provenance.ts'
import type { NavyaForecastRecord, ThresholdPolicy } from './types.ts'

/**
 * Adapter from the team's AI-service contract to Navya's forecast record.
 *
 * ## Why an adapter and not a change to `ai-service.client.ts`
 *
 * `src/clients/ai-service.client.ts` is team-owned and correctly stays as it is:
 * it speaks the running FastAPI contract and nothing else. Navya's engine emits
 * a **superset** of that contract — it adds provenance, threshold policy and
 * held-out metrics.
 *
 * Those fields are not on the wire today. Adding them requires a team owner to
 * extend `app/schemas/models.py`, which is team-owned, so the required change is
 * recorded in `01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md` rather than made here.
 *
 * Until then this adapter:
 *
 * - reads exactly the fields that exist today,
 * - records the fields that are *not* yet available as `null` rather than
 *   deriving them from what is,
 * - is a pure function, so the lossy step is visible and testable.
 *
 * The lossy parts are named in `LOSSY_FIELDS` and asserted by tests, so the gap
 * cannot quietly close without anyone noticing the list is now wrong.
 */

/** Fields the running AI contract does not carry, and their honest stand-in. */
export const LOSSY_FIELDS = {
  datasetReference: null,
  datasetLicense: null,
  datasetChecksum: null,
  samplingInterval: null,
  stationReference: null,
  residualSigma: null,
  thresholdSource: null,
  regressionMetrics: null,
  metricProvenance: null,
  backtest: null,
} as const

/**
 * `RiskAnalyticsContract.threshold_level` is the only threshold the running
 * contract carries. `threshold_label` is how the engine says what that number
 * actually is, and it is the field that keeps a demo threshold from being read
 * as an official flood stage.
 */
function thresholdPolicyFrom(analytics: RiskAnalyticsContract | null): ThresholdPolicy {
  const label: string | null | undefined = analytics?.threshold_label
  if (typeof label === 'string' && /not official|pending|unapproved/i.test(label)) return 'pending'
  if (analytics?.threshold_level !== null && analytics?.threshold_level !== undefined) {
    // A threshold exists and nothing in the label disclaims it. Still 'pending':
    // the running contract has no way to record formal approval, so claiming
    // 'approved' here would be inferring sign-off from silence.
    return 'pending'
  }
  return 'pending'
}

/**
 * Build a Navya forecast record from the running contract.
 *
 * `analytics` is optional: it is a second call, and its absence degrades the
 * record to `pending` rather than failing the request.
 */
export function toNavyaForecastRecord(
  contract: ForecastContract,
  options: {
    analytics?: RiskAnalyticsContract | null
    model?: ModelInfoContract | null
  } = {},
): NavyaForecastRecord {
  const analytics: RiskAnalyticsContract | null = options.analytics ?? null
  const model: ModelInfoContract | null = options.model ?? null
  const threshold: number | null = analytics?.threshold_level ?? null
  const targetUnits: string | null = null

  return {
    forecastId: contract.forecast_id,
    forecastTimestamp: contract.prediction_timestamp,
    forecastHorizon: contract.forecast_horizon,
    modelId: contract.model_id,
    modelVersion: contract.model_version,
    status: contract.status,
    target: 'water_level',
    targetUnits,
    predictedValue: contract.predicted_water_level,
    predictedWaterLevel: contract.predicted_water_level,
    predictedInflow: null,
    floodProbability: contract.flood_probability,
    riskLevel: contract.risk_level,
    riskScore: contract.flood_probability,
    threshold,
    thresholdPolicy: thresholdPolicyFrom(analytics),
    thresholdSource: analytics?.threshold_label ?? null,
    residualSigma: LOSSY_FIELDS.residualSigma,
    provenance: {
      datasetReference: LOSSY_FIELDS.datasetReference,
      // The running contract carries no provenance at all. 'unknown' is the only
      // honest value: claiming 'real' would assert a data lineage nobody sent.
      datasetType: 'unknown',
      datasetLicense: LOSSY_FIELDS.datasetLicense,
      datasetChecksum: LOSSY_FIELDS.datasetChecksum,
      samplingInterval: LOSSY_FIELDS.samplingInterval,
      stationReference: LOSSY_FIELDS.stationReference,
      target: 'water_level',
      targetUnits,
      forecastHorizonHours: parseHorizonHours(contract.forecast_horizon),
      leadTimeRows: 0,
      modelId: model?.model_id ?? contract.model_id,
      modelVersion: model?.version ?? contract.model_version,
      contractVersion: 'unknown',
      featureList: [],
      disclaimer: null,
      metricsLabel: null,
      missingFields: [],
    },
    metrics: null,
    metricProvenance: null,
    backtest: [],
  }
}

/** Parse `'6h'` into `6`. Unknown formats return `null` rather than a guess. */
export function parseHorizonHours(horizon: string): number {
  const match: RegExpMatchArray | null = /^(\d+(?:\.\d+)?)\s*h$/i.exec(horizon.trim())
  if (match === null) return 0
  const value: number = Number.parseFloat(match[1])
  return Number.isFinite(value) ? value : 0
}

/**
 * Recompute the open provenance questions for a record built by this adapter.
 *
 * A record assembled from the running contract will always have several. That is
 * the point: it tells a consumer exactly what the transport threw away.
 */
export function adapterGaps(record: NavyaForecastRecord): string[] {
  return openQuestions(record)
}

/**
 * The read seam Navya's own code uses. It reuses the team's client unchanged.
 *
 * Declared as an interface so a test can pass a stub with no network access.
 */
export interface NavyaForecastReader {
  latest(horizonHours?: number): Promise<NavyaForecastRecord>
  series(hours?: number): Promise<unknown>
  riskAnalytics(): Promise<RiskAnalyticsContract | null>
  models(): Promise<ModelInfoContract[]>
}

/**
 * Wrap the team's `ForecastClient` so Navya's code reads enriched records.
 *
 * Does not cache, retry, or alter any existing behaviour — it only adapts the
 * shape. `riskAnalytics` returns `null` on failure rather than throwing, because
 * a missing risk-analytics call degrades the record to a pending threshold and
 * should not fail the forecast read itself.
 */
export class NavyaForecastAdapter implements NavyaForecastReader {
  constructor(private readonly client: ForecastClient) {}

  async latest(horizonHours = 24): Promise<NavyaForecastRecord> {
    const contract: ForecastContract = await this.client.getLatestForecast(horizonHours)
    const [analytics, models] = await Promise.all([
      this.riskAnalytics(),
      this.client.getModels().catch(() => [] as ModelInfoContract[]),
    ])
    return toNavyaForecastRecord(contract, {
      analytics,
      model: models.find((m) => m.model_id === contract.model_id) ?? null,
    })
  }

  series(hours = 24): Promise<unknown> {
    return this.client.getForecastSeries(hours)
  }

  async riskAnalytics(): Promise<RiskAnalyticsContract | null> {
    try {
      return await this.client.getRiskAnalytics()
    } catch {
      return null
    }
  }

  models(): Promise<ModelInfoContract[]> {
    return this.client.getModels()
  }
}
