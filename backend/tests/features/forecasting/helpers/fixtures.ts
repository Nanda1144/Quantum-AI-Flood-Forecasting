/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Fixture builders for the forecasting contract tests.
 *
 * Not named `*.test.ts`, so `node --test` does not collect it.
 *
 * ## The rule these fixtures follow
 *
 * Every number here is a **placeholder for a shape**, never a claimed result. The
 * values are round and self-evidently arbitrary (`riskScore: 0.62`, not
 * `0.6183...`), and each builder takes explicit overrides so a test never has to
 * edit one to get the case it wants.
 *
 * `realRecord()` exists so the "this may be shown as a result" branches can be
 * exercised at all — but it deliberately supplies **no** dataset, because none
 * exists to supply. It is a *shape* that satisfies the guard, not a claim that
 * the guard should ever be satisfied in production. The tests that use it assert
 * only the guard's logic, never a score.
 */

import type {
  AIHealthContract,
  ForecastContract,
  ForecastPointContract,
  ModelInfoContract,
  PredictionRecordContract,
  RiskAnalyticsContract,
} from '../../../src/types/contract.ts'
import type { ForecastClient } from '../../../src/clients/ai-service.client.ts'
import type {
  ForecastProvenance,
  ForecastRegressionMetrics,
  MetricProvenance,
  ForecastRecord,
} from '../../../src/features/forecasting/types.ts'

/** Matches the team's `^FC-\d{8}-\d{1,6}$` id shape. */
export const FORECAST_ID = 'FC-20240101-0600'

/**
 * A provenance block that says nothing is known.
 *
 * The default for every fixture: a record assembled without a real dataset must
 * not imply one exists.
 */
export function unrecordedProvenance(
  overrides: Partial<ForecastProvenance> = {},
): ForecastProvenance {
  return {
    datasetReference: null,
    datasetType: 'unknown',
    datasetLicense: null,
    datasetChecksum: null,
    samplingInterval: null,
    stationReference: null,
    target: 'water_level',
    targetUnits: null,
    forecastHorizonHours: 6,
    leadTimeRows: 0,
    modelId: 'NAVYA-HYDRO-001',
    modelVersion: '0.1.0',
    contractVersion: 'unknown',
    featureList: [],
    disclaimer: null,
    metricsLabel: null,
    missingFields: [],
    ...overrides,
  }
}

/**
 * A record with no dataset behind it — the state every real call currently
 * produces, because the running AI contract carries no provenance.
 */
export function unrecordedRecord(overrides: Partial<ForecastRecord> = {}): ForecastRecord {
  return {
    forecastId: FORECAST_ID,
    forecastTimestamp: '2024-01-01T06:00:00Z',
    forecastHorizon: '6h',
    modelId: 'NAVYA-HYDRO-001',
    modelVersion: '0.1.0',
    status: 'completed',
    target: 'water_level',
    targetUnits: null,
    predictedValue: 3.2,
    predictedWaterLevel: 3.2,
    predictedInflow: null,
    floodProbability: 0.62,
    riskLevel: 'HIGH',
    riskScore: 0.62,
    threshold: null,
    thresholdPolicy: 'pending',
    thresholdSource: null,
    residualSigma: null,
    provenance: unrecordedProvenance(),
    metrics: null,
    metricProvenance: null,
    backtest: [],
    ...overrides,
  }
}

/** Placeholder scores. Shapes only — see the file header. */
export function placeholderMetrics(
  overrides: Partial<ForecastRegressionMetrics> = {},
): ForecastRegressionMetrics {
  return {
    mae: 0.1,
    rmse: 0.2,
    r2: 0.8,
    nse: 0.8,
    peakAbsoluteError: 0.5,
    bias: 0.01,
    nSamples: 100,
    ...overrides,
  }
}

/** A held-out, non-selection metric provenance. */
export function heldOutProvenance(overrides: Partial<MetricProvenance> = {}): MetricProvenance {
  return { split: 'test', isSelectionStatistic: false, ...overrides }
}

/**
 * A record that passes every honesty guard.
 *
 * **Not a claim that such a record can currently be produced.** It is the
 * counterfactual a test needs to prove a guard actually has teeth — without it,
 * a guard that always refuses would pass every other test in the file.
 */
export function realRecord(overrides: Partial<ForecastRecord> = {}): ForecastRecord {
  return unrecordedRecord({
    targetUnits: 'm',
    threshold: 5,
    thresholdSource: 'supplied by the test as a shape, not by any authority',
    provenance: unrecordedProvenance({
      datasetReference: 'shape-only',
      datasetType: 'real',
      datasetLicense: 'shape-only',
      datasetChecksum: 'shape-only',
      samplingInterval: '1h',
      stationReference: 'shape-only',
      targetUnits: 'm',
    }),
    metrics: placeholderMetrics(),
    metricProvenance: heldOutProvenance(),
    ...overrides,
  })
}

/** The team's `ForecastContract`, as the running service returns it. */
export function forecastContract(overrides: Partial<ForecastContract> = {}): ForecastContract {
  return {
    forecast_id: FORECAST_ID,
    flood_probability: 0.62,
    risk_level: 'HIGH',
    predicted_water_level: 3.2,
    forecast_horizon: '6h',
    model_id: 'NAVYA-HYDRO-001',
    model_version: '0.1.0',
    prediction_timestamp: '2024-01-01T06:00:00Z',
    status: 'completed',
    ...overrides,
  }
}

export function riskAnalyticsContract(
  overrides: Partial<RiskAnalyticsContract> = {},
): RiskAnalyticsContract {
  return {
    risk_trend: [],
    probability_trend: [],
    distribution: [],
    summary: { high: 1, medium: 0, low: 0, critical: 0 },
    overall_trend: 'up',
    ...overrides,
  }
}

export function modelInfoContract(overrides: Partial<ModelInfoContract> = {}): ModelInfoContract {
  return {
    model_id: 'NAVYA-HYDRO-001',
    name: 'navya-hydro',
    version: '0.1.0',
    algorithm: 'ridge',
    status: 'ready',
    last_trained_at: '2024-01-01T00:00:00Z',
    last_evaluated_at: '2024-01-01T00:00:00Z',
    metrics: {},
    ...overrides,
  }
}

export function forecastPointContract(
  overrides: Partial<ForecastPointContract> = {},
): ForecastPointContract {
  return {
    timestamp: '2024-01-01T06:00:00Z',
    predicted_water_level: 3.2,
    flood_probability: 0.62,
    ...overrides,
  }
}

export function predictionRecordContract(
  overrides: Partial<PredictionRecordContract> = {},
): PredictionRecordContract {
  return {
    forecast_id: FORECAST_ID,
    timestamp: '2024-01-01T06:00:00Z',
    probability: 0.62,
    risk_level: 'HIGH',
    water_level: 3.2,
    model_id: 'NAVYA-HYDRO-001',
    status: 'completed',
    ...overrides,
  }
}

export function healthContract(overrides: Partial<AIHealthContract> = {}): AIHealthContract {
  return {
    service: 'q-flare-ai-service',
    version: '0.1.0',
    engine: 'navya-hydro',
    status: 'online',
    ...overrides,
  }
}

/** What a stubbed `ForecastClient` should do at each call. */
export interface StubForecastClientOptions {
  forecast?: ForecastContract | Error
  analytics?: RiskAnalyticsContract | Error
  models?: ModelInfoContract[] | Error
  series?: ForecastPointContract[] | Error
  recent?: PredictionRecordContract[] | Error
}

/**
 * A `ForecastClient` with no network access.
 *
 * Passing an `Error` makes that call reject, so the adapter's degradation paths
 * are reachable in a test rather than only in production.
 */
export function stubForecastClient(options: StubForecastClientOptions = {}): ForecastClient & {
  calls: string[]
} {
  const calls: string[] = []

  const resolve = <T>(value: T | Error | undefined, fallback: T): T => {
    if (value instanceof Error) throw value
    return value ?? fallback
  }

  return {
    calls,
    async health() {
      calls.push('health')
      return { health: healthContract(), latencyMs: 1 }
    },
    async getLatestForecast() {
      calls.push('getLatestForecast')
      return resolve(options.forecast, forecastContract())
    },
    async getForecastSeries() {
      calls.push('getForecastSeries')
      return resolve(options.series, [])
    },
    async getRiskAnalytics() {
      calls.push('getRiskAnalytics')
      return resolve(options.analytics, riskAnalyticsContract())
    },
    async getModels() {
      calls.push('getModels')
      return resolve(options.models, [])
    },
    async getRecentPredictions() {
      calls.push('getRecentPredictions')
      return resolve(options.recent, [])
    },
  }
}
