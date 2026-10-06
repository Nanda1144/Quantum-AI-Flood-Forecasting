/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Tests for expected peak and time-to-threshold.
 *
 * Both quantities need a *lead-time forecast series* — rows of future
 * predictions. The contract never sends one, so `forecastSeriesOf` is empty and
 * the live dashboard reaches the honest unavailable states. But the math must
 * still exist, be correct, and be proven: the series argument lets these tests
 * drive every branch — crossing, no crossing, threshold unknown, and forecast
 * unknown — without pretending the backend sends rows.
 */

import { describe, expect, it } from 'vitest'
import { expectedPeakOf, forecastSeriesOf, timeToThreshold, type NavyaForecastSeriesPoint } from './derived'
import { realForecastRecord, syntheticForecastRecord } from './fixtures'
import { HUMAN_INPUT_REQUIRED } from './types'

describe('forecastSeriesOf', () => {
  it('is empty for a null record', () => {
    expect(forecastSeriesOf(null)).toEqual([])
  })

  it('is empty for a real record — the contract sends no lead-time array', () => {
    expect(forecastSeriesOf(realForecastRecord())).toEqual([])
  })

  it('never substitutes the backtest as a forward series', () => {
    const record = realForecastRecord()
    expect(record.backtest.length).toBeGreaterThan(0)
    expect(forecastSeriesOf(record)).toEqual([])
  })
})

describe('expectedPeakOf', () => {
  it('is unavailable when the record carries no lead-time series', () => {
    const result = expectedPeakOf(realForecastRecord())
    expect(result.status).toBe('unavailable')
    if (result.status === 'unavailable') {
      expect(result.reason).toMatch(/single point prediction/)
      expect(result.reason).toContain(HUMAN_INPUT_REQUIRED)
    }
  })

  it('reports the peak of a supplied series with the record’s units', () => {
    const record = realForecastRecord({ target: 'water_level' })
    const series: NavyaForecastSeriesPoint[] = [
      { timestamp: '2024-01-01T00:00:00Z', value: 1.2 },
      { timestamp: '2024-01-01T01:00:00Z', value: 2.8 },
      { timestamp: '2024-01-01T02:00:00Z', value: 2.4 },
    ]
    const result = expectedPeakOf(record, series)
    expect(result.status).toBe('available')
    if (result.status === 'available') {
      expect(result.value).toBe(2.8)
      expect(result.units).toBe('m')
    }
  })

  it('does not peak outside the supplied series', () => {
    const result = expectedPeakOf(realForecastRecord(), [
      { timestamp: '2024-01-01T00:00:00Z', value: 1.1 },
    ])
    expect(result.status).toBe('available')
    if (result.status === 'available') expect(result.value).toBe(1.1)
  })
})

describe('timeToThreshold', () => {
  const CROSSING: NavyaForecastSeriesPoint[] = [
    { timestamp: '2024-01-01T00:00:00Z', value: 1.5 },
    { timestamp: '2024-01-01T01:00:00Z', value: 2.5 },
    { timestamp: '2024-01-01T02:00:00Z', value: 3.0 },
  ]

  it('reports the elapsed hours to the first crossing', () => {
    const result = timeToThreshold(CROSSING, 2.5)
    expect(result.status).toBe('reached')
    if (result.status === 'reached') {
      expect(result.hours).toBe(1)
      expect(result.crossingIndex).toBe(1)
      expect(result.timestamp).toBe('2024-01-01T01:00:00Z')
    }
  })

  it('counts a value exactly on the threshold as crossed', () => {
    const result = timeToThreshold(
      [
        { timestamp: '2024-01-01T00:00:00Z', value: 1.0 },
        { timestamp: '2024-01-01T01:00:00Z', value: 2.5 },
      ],
      2.5,
    )
    expect(result.status).toBe('reached')
    if (result.status === 'reached') expect(result.hours).toBe(1)
  })

  it('reports zero hours when the origin itself is at or above the threshold', () => {
    const result = timeToThreshold(
      [{ timestamp: '2024-01-01T00:00:00Z', value: 4.0 }],
      2.5,
    )
    expect(result.status).toBe('reached')
    if (result.status === 'reached') expect(result.hours).toBe(0)
  })

  it('says the threshold is not reached within the horizon', () => {
    const result = timeToThreshold(
      [
        { timestamp: '2024-01-01T00:00:00Z', value: 1.0 },
        { timestamp: '2024-01-01T01:00:00Z', value: 1.4 },
      ],
      2.5,
    )
    expect(result.status).toBe('not_reached')
    if (result.status === 'not_reached') {
      expect(result.reason).toBe('Not reached in forecast horizon')
    }
  })

  it('reports unavailable when no threshold is configured', () => {
    const result = timeToThreshold(CROSSING, null)
    expect(result.status).toBe('threshold_unavailable')
    if (result.status === 'threshold_unavailable') {
      expect(result.reason).toMatch(/No flood threshold is configured/)
    }
  })

  it('reports the threshold problem before an empty series', () => {
    expect(timeToThreshold([], null).status).toBe('threshold_unavailable')
  })

  it('reports unavailable when the forecast series is missing', () => {
    const result = timeToThreshold([], 2.5)
    expect(result.status).toBe('forecast_unavailable')
    if (result.status === 'forecast_unavailable') {
      expect(result.reason).toContain(HUMAN_INPUT_REQUIRED)
    }
  })

  it('still reports a crossing with null elapsed hours when timestamps are unusable', () => {
    const result = timeToThreshold(
      [
        { timestamp: 'not-a-date', value: 1.0 },
        { timestamp: 'also-not-a-date', value: 3.0 },
      ],
      2.5,
    )
    expect(result.status).toBe('reached')
    if (result.status === 'reached') expect(result.hours).toBeNull()
  })
})

describe('synthetic records', () => {
  it('derive no series and therefore no peak or crossing', () => {
    const record = syntheticForecastRecord()
    expect(forecastSeriesOf(record)).toEqual([])
    expect(expectedPeakOf(record).status).toBe('unavailable')
    expect(timeToThreshold(forecastSeriesOf(record), record.threshold).status).toBe(
      'forecast_unavailable',
    )
  })
})