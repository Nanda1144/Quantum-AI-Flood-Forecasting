/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Normalizer tests.
 *
 * The normalizers' job is to record what the transport did not send as `null`
 * rather than inferring it. Almost every test below is therefore a test that
 * something was NOT invented: no default units, no guessed provenance, no
 * completed metric set, no rescued backtest point.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  loadNavyaComparison,
  loadNavyaForecast,
  parseHorizonHours,
  toNavyaForecastRecord,
  toNavyaModelComparison,
} from './navyaForecastService'
import { honestComparison } from './fixtures'

/** A minimal payload in the shape the running contract actually sends. */
const RAW = {
  forecast_id: 'FC-20240101-1200',
  prediction_timestamp: '2024-01-01T12:00:00Z',
  forecast_horizon: '24h',
  model_id: 'NAVYA-HYDRO-001',
  model_version: '1.0.0',
  status: 'completed' as const,
  predicted_water_level: 3.4,
  flood_probability: 0.9,
  risk_level: 'CRITICAL' as const,
}

describe('parseHorizonHours', () => {
  it('parses the common forms', () => {
    expect(parseHorizonHours('24h')).toBe(24)
    expect(parseHorizonHours(' 6H ')).toBe(6)
    expect(parseHorizonHours('1.5h')).toBe(1.5)
  })

  it('returns 0 for unparseable input rather than a guessed default', () => {
    expect(parseHorizonHours('24 hours')).toBe(0)
    expect(parseHorizonHours('')).toBe(0)
    expect(parseHorizonHours('1D')).toBe(0)
  })
})

describe('toNavyaForecastRecord', () => {
  it('maps the wire fields through unchanged', () => {
    const record = toNavyaForecastRecord(RAW)
    expect(record.forecastId).toBe('FC-20240101-1200')
    expect(record.predictedValue).toBe(3.4)
    expect(record.floodProbability).toBe(0.9)
    expect(record.riskLevel).toBe('CRITICAL')
    expect(record.forecastHorizon).toBe('24h')
  })

  it('records absent provenance as unknown, never as real', () => {
    const record = toNavyaForecastRecord(RAW)
    expect(record.provenance.datasetType).toBe('unknown')
    expect(record.provenance.datasetReference).toBeNull()
    expect(record.provenance.datasetLicense).toBeNull()
    expect(record.provenance.stationReference).toBeNull()
    expect(record.provenance.targetUnits).toBeNull()
  })

  it('leaves threshold policy pending even when a threshold is present', () => {
    const record = toNavyaForecastRecord({ ...RAW, threshold_level: 3.0 })
    expect(record.threshold).toBe(3.0)
    expect(record.thresholdPolicy).toBe('pending')
  })

  it('leaves threshold policy pending when there is no threshold at all', () => {
    expect(toNavyaForecastRecord(RAW).thresholdPolicy).toBe('pending')
    expect(toNavyaForecastRecord({ ...RAW, threshold_level: null }).thresholdPolicy).toBe('pending')
  })

  it('does not treat an empty threshold label as a source', () => {
    const record = toNavyaForecastRecord({ ...RAW, threshold_label: '   ' })
    expect(record.thresholdSource).toBeNull()
  })

  it('returns null metrics when the payload carries none', () => {
    expect(toNavyaForecastRecord(RAW).metrics).toBeNull()
  })

  it('refuses a partial metric set rather than filling the holes', () => {
    const record = toNavyaForecastRecord({
      ...RAW,
      metrics: { mae: 0.1, rmse: 0.2, nSamples: 100 },
    } as unknown as typeof RAW)
    // A missing r2/nse/peak must not render as four confident numbers and a hole.
    expect(record.metrics).toBeNull()
  })

  it('accepts a complete metric set', () => {
    const record = toNavyaForecastRecord({
      ...RAW,
      metrics: {
        mae: 0.1,
        rmse: 0.2,
        r2: 0.8,
        nse: 0.79,
        peakAbsoluteError: 1.5,
        bias: -0.05,
        nSamples: 1825,
      },
    } as unknown as typeof RAW)
    expect(record.metrics).toEqual({
      mae: 0.1,
      rmse: 0.2,
      r2: 0.8,
      nse: 0.79,
      peakAbsoluteError: 1.5,
      bias: -0.05,
      nSamples: 1825,
    })
  })

  it('rejects a metric value that is not a finite number', () => {
    const record = toNavyaForecastRecord({
      ...RAW,
      metrics: {
        mae: Number.NaN,
        rmse: 0.2,
        r2: 0.8,
        nse: 0.79,
        peakAbsoluteError: 1.5,
      },
    } as unknown as typeof RAW)
    expect(record.metrics).toBeNull()
  })

  it('rejects an unrecognised split name', () => {
    const record = toNavyaForecastRecord({
      ...RAW,
      metricProvenance: { split: 'holdout', isSelectionStatistic: false },
    } as unknown as typeof RAW)
    expect(record.metricProvenance).toBeNull()
  })

  it('drops a backtest point that is missing a field', () => {
    const record = toNavyaForecastRecord({
      ...RAW,
      backtest: [
        {
          timestamp: '2024-01-01T00:00:00Z',
          originTimestamp: '2023-12-31T00:00:00Z',
          predicted: 2.1,
          observed: 2.05,
          floodProbability: 0.1,
        },
        { timestamp: '2024-01-02T00:00:00Z', predicted: 2.2, observed: 2.3 },
      ],
    } as unknown as typeof RAW)
    // The count on screen must be the count of complete pairs.
    expect(record.backtest).toHaveLength(1)
    expect(record.backtest[0].predicted).toBe(2.1)
  })

  it('returns an empty backtest rather than a fabricated one', () => {
    expect(toNavyaForecastRecord(RAW).backtest).toEqual([])
  })
})

describe('toNavyaModelComparison', () => {
  it('marks an unexecuted row unavailable instead of scoring it zero', () => {
    const comparison = toNavyaModelComparison(honestComparison())
    const unscored = comparison.rows.find((r) => r.key === 'xgboost')
    expect(unscored?.executed).toBe(false)
    expect(unscored?.rmse).toBeNull()
    expect(unscored?.unavailableReason).toBe('xgboost.XGBRegressor is not installed')
  })

  it('refuses to invent a label for a row that carries none', () => {
    const comparison = toNavyaModelComparison({
      ...honestComparison(),
      rows: [{ key: 'a', executed: true, rmse: 0.1 }],
    })
    expect(comparison.rows[0].metricsLabel).toBe('no label recorded')
  })

  it('defaults the ranking split to validation, never to test', () => {
    const comparison = toNavyaModelComparison({ rows: [] })
    expect(comparison.selectionSplit).toBe('validation')
    expect(comparison.heldOutSplit).toBe('test')
  })

  it('preserves an explicit ranking split so the guard can inspect it', () => {
    expect(toNavyaModelComparison({ selectionSplit: 'test', rows: [] }).selectionSplit).toBe('test')
  })

  it('treats heldOutScored as false unless the payload says true', () => {
    expect(toNavyaModelComparison({ rows: [] }).heldOutScored).toBe(false)
    expect(toNavyaModelComparison({ rows: [], heldOutScored: true }).heldOutScored).toBe(true)
  })
})

describe('loadNavyaForecast / loadNavyaComparison', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function ok(body: unknown) {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: body }),
      headers: { get: () => null },
    })
  }

  it('reads the team endpoint without a sample-data fallback', async () => {
    ok(RAW)
    const record = await loadNavyaForecast()
    expect(record.forecastId).toBe('FC-20240101-1200')
    expect(record.provenance.datasetType).toBe('unknown')
  })

  it('propagates a failure instead of substituting a sample forecast', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: { code: 'SERVICE_DOWN', message: 'AI service is down' } }),
      headers: { get: () => null },
    })
    // The team's `fetchJson` normalises failures to a plain `APIError` object, not
    // an `Error` instance, so the assertion matches the shape rather than a message.
    await expect(loadNavyaForecast()).rejects.toMatchObject({
      code: 'SERVICE_DOWN',
      message: 'AI service is down',
    })
  })

  it('returns null for a failed comparison rather than throwing', async () => {
    fetchMock.mockRejectedValue(new Error('network'))
    await expect(loadNavyaComparison()).resolves.toBeNull()
  })
})
