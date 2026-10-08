/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Fixture builders for the forecasting tests.
 *
 * ## Every number here is a test fixture, not a result
 *
 * These are hand-written values chosen to be recognisable in a failure message.
 * They are NOT hydrological measurements and they are NOT metrics — they exist so
 * a test can assert that a specific value survives or is refused on its way to
 * the screen. A test that renders `0.25` and asserts `0.25` proves the pipeline
 * is transparent, not that a model achieved anything.
 *
 * The deliberately-wrong builders at the bottom exist to prove the guards have
 * teeth. A guard that has never been shown rejecting something is not a guard.
 *
 * This file is the own; the team's `src/test/fixtures.ts` is untouched.
 */

import type {
  ForecastBacktestPoint,
  ForecastRecord,
  ForecastModelComparison,
  ForecastModelComparisonRow,
  ForecastProvenance,
  ForecastRegressionMetrics,
} from './types'

/** A complete, presentable real-data provenance. */
export const REAL_PROVENANCE: ForecastProvenance = {
  datasetReference: 'gauges/upper-reach.csv',
  datasetType: 'real',
  datasetLicense: 'CC-BY-4.0',
  datasetChecksum: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
  samplingInterval: '1D',
  stationReference: 'STN-0001',
  target: 'water_level',
  targetUnits: 'm',
  forecastHorizonHours: 24,
  leadTimeRows: 1,
  modelId: 'NAVYA-HYDRO-001',
  modelVersion: '1.0.0',
  contractVersion: '1.0.0',
  featureList: ['rainfall_24h', 'level_lag1'],
  disclaimer: null,
  metricsLabel: 'measured evaluation',
  missingFields: [],
}

/** Synthetic provenance with the required disclaimer attached. */
export const SYNTHETIC_PROVENANCE: ForecastProvenance = {
  ...REAL_PROVENANCE,
  datasetReference: null,
  datasetType: 'synthetic',
  datasetLicense: null,
  datasetChecksum: '585fced336c9428d323316d5f741c4f6113d1e2426d9575d838945d66d57c78f',
  stationReference: null,
  disclaimer: 'THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL HYDROLOGICAL OBSERVATION DATA.',
  metricsLabel: 'synthetic/demo evaluation only — not a production or research result',
  missingFields: ['dataset reference', 'station reference'],
}

/** A complete regression metric set. Values are arbitrary test fixtures. */
export const REAL_METRICS: ForecastRegressionMetrics = {
  mae: 0.12,
  rmse: 0.16,
  r2: 0.79,
  nse: 0.78,
  peakAbsoluteError: 1.56,
  bias: -0.06,
  nSamples: 1825,
}

const BACKTEST: ForecastBacktestPoint[] = [
  { timestamp: '2024-01-01T00:00:00Z', originTimestamp: '2023-12-31T00:00:00Z', predicted: 2.1, observed: 2.05, floodProbability: 0.1, riskLevel: 'LOW' },
  { timestamp: '2024-01-02T00:00:00Z', originTimestamp: '2024-01-01T00:00:00Z', predicted: 2.4, observed: 2.62, floodProbability: 0.3, riskLevel: 'MEDIUM' },
  { timestamp: '2024-01-03T00:00:00Z', originTimestamp: '2024-01-02T00:00:00Z', predicted: 3.0, observed: 2.81, floodProbability: 0.7, riskLevel: 'HIGH' },
  { timestamp: '2024-01-04T00:00:00Z', originTimestamp: '2024-01-03T00:00:00Z', predicted: 3.4, observed: 3.55, floodProbability: 0.9, riskLevel: 'CRITICAL' },
]

const BASE_RECORD: ForecastRecord = {
  forecastId: 'FC-20240101-1200',
  forecastTimestamp: '2024-01-01T12:00:00Z',
  forecastHorizon: '24h',
  modelId: 'NAVYA-HYDRO-001',
  modelVersion: '1.0.0',
  status: 'completed',
  target: 'water_level',
  predictedValue: 3.4,
  predictedWaterLevel: 3.4,
  predictedInflow: null,
  floodProbability: 0.9,
  riskLevel: 'CRITICAL',
  riskScore: 0.9,
  threshold: 3.0,
  thresholdPolicy: 'pending',
  thresholdSource: 'DEMO value; NOT an official flood stage',
  residualSigma: 0.41,
  provenance: REAL_PROVENANCE,
  metrics: REAL_METRICS,
  metricProvenance: { split: 'test', isSelectionStatistic: false },
  backtest: BACKTEST,
}

/** A fully-specified real-data record: every guard should pass. */
export function realForecastRecord(overrides: Partial<ForecastRecord> = {}): ForecastRecord {
  return { ...BASE_RECORD, ...overrides }
}

/** A synthetic-data record. Guards must refuse to present it as a result. */
export function syntheticForecastRecord(
  overrides: Partial<ForecastRecord> = {},
): ForecastRecord {
  return {
    ...BASE_RECORD,
    threshold: 3.0,
    provenance: SYNTHETIC_PROVENANCE,
    metrics: REAL_METRICS,
    metricProvenance: { split: 'test', isSelectionStatistic: false },
    ...overrides,
  }
}

/* ------------------------------------------------------------------ */
/* Counterfactuals — records that MUST be refused                      */
/* ------------------------------------------------------------------ */

/** A train-split score: a fit statistic, not a held-out estimate. */
export function trainSplitRecord(): ForecastRecord {
  return realForecastRecord({
    metricProvenance: { split: 'train', isSelectionStatistic: false },
  })
}

/** A validation-split score: what the model was selected on. Optimistic. */
export function validationSplitRecord(): ForecastRecord {
  return realForecastRecord({
    metricProvenance: { split: 'validation', isSelectionStatistic: true },
  })
}

/** Self-contradictory: says validation but denies being a selection statistic. */
export function contradictorySplitRecord(): ForecastRecord {
  return realForecastRecord({
    metricProvenance: { split: 'validation', isSelectionStatistic: false },
  })
}

/** Provenance of unknown origin: not fake, but not documented either. */
export function unknownProvenanceRecord(): ForecastRecord {
  return realForecastRecord({
    provenance: { ...SYNTHETIC_PROVENANCE, datasetType: 'unknown', disclaimer: null },
  })
}

const SCORED_ROW: ForecastModelComparisonRow = {
  key: 'ridge',
  displayName: 'Ridge',
  algorithm: 'RidgeRegression',
  executed: true,
  rmse: 0.16,
  mae: 0.12,
  r2: 0.79,
  nse: 0.78,
  nSamples: 1825,
  selected: true,
  unavailableReason: null,
  metricsLabel: 'measured evaluation',
}

const UNSCORED_ROW: ForecastModelComparisonRow = {
  key: 'xgboost',
  displayName: 'XGBoost',
  algorithm: 'XGBRegressor',
  executed: false,
  rmse: null,
  mae: null,
  r2: null,
  nse: null,
  nSamples: null,
  selected: false,
  unavailableReason: 'xgboost.XGBRegressor is not installed',
  metricsLabel: 'measured evaluation',
}

const BASE_COMPARISON: ForecastModelComparison = {
  selectionSplit: 'validation',
  heldOutSplit: 'test',
  selectionMetric: 'rmse',
  selectedKey: 'ridge',
  rows: [SCORED_ROW, UNSCORED_ROW],
  metricsLabel: 'measured evaluation',
  heldOutScored: true,
}

/** A comparison the honesty guard should accept. */
export function honestComparison(overrides: Partial<ForecastModelComparison> = {}): ForecastModelComparison {
  return { ...BASE_COMPARISON, ...overrides }
}

/** A comparison that ranks on the test split — must be refused. */
export function testSplitRanking(): ForecastModelComparison {
  return honestComparison({ selectionSplit: 'test' })
}

/** A comparison whose executed row carries no score — must be refused. */
export function executedRowWithNoScore(): ForecastModelComparison {
  return honestComparison({
    rows: [{ ...SCORED_ROW, rmse: null }],
  })
}

/** A comparison with executed candidates but no selection — must be refused. */
export function executedWithNoSelection(): ForecastModelComparison {
  return honestComparison({ selectedKey: '' })
}
