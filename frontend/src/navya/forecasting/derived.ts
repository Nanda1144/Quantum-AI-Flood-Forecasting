/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Metrics computed from the forecast record for display.
 *
 * Two of the task's metrics — **expected peak** and **time to threshold** — are
 * forward-looking quantities: they are properties of a *lead-time series*, the
 * model's predictions row by row across the horizon. The running contract does
 * not carry one. `NavyaForecastRecord` has a single point prediction
 * (`predictedValue`) and a backtest window (`backtest[]`, a *hindcast* of past
 * timestamps), and nothing else.
 *
 * This module makes that absence structural rather than incidental:
 *
 * - `forecastSeriesOf` returns the lead-time series the record carries, which is
 *   **empty**. It is not `backtest`: those points are historical predictions
 *   made *in the past*; computing a crossing time from them would report a
 *   historical accident as a forward lead time.
 * - `expectedPeakOf` and `timeToThreshold` accept an explicit series so the
 *   *math* is implemented, unit-tested on all its branches, and ready for the
 *   day the backend sends rows — while the live UI is handed the record's real
 *   (empty) series and therefore renders the honest "unavailable" state.
 *
 * Every absence is a sentence with a reason, never a blank. A blank reads as an
 * oversight; a reason reads as a decision.
 */

import { HUMAN_INPUT_REQUIRED, type NavyaForecastRecord } from './types'

/** One forward forecast point: the predicted target at a timestamp. */
export interface NavyaForecastSeriesPoint {
  timestamp: string
  value: number
}

/**
 * The lead-time series the record carries.
 *
 * Always empty in this revision. `provenance.leadTimeRows` counts rows the
 * engine produced, but the payload exposes no per-row timestamps or values, so
 * there is nothing to read — and synthesising rows from a count would be
 * inventing a series.
 */
export function forecastSeriesOf(record: NavyaForecastRecord | null): NavyaForecastSeriesPoint[] {
  if (record === null) return []
  // The contract sends a single point prediction and a backtest window, not a
  // lead-time array. Nothing may be read where nothing was sent.
  return []
}

export type ExpectedPeakResult =
  | { status: 'available'; value: number; units: string | null }
  | { status: 'unavailable'; reason: string }

/**
 * Expected peak over the forecast horizon.
 *
 * Peak of the lead-time series, if one exists. With no series, there is no peak
 * to report: a point prediction is a single value at a single timestamp, not a
 * statement about where the level tops out. The optional `series` argument lets
 * tests exercise the available branch without pretending the contract sends one.
 */
export function expectedPeakOf(
  record: NavyaForecastRecord,
  series: NavyaForecastSeriesPoint[] = forecastSeriesOf(record),
): ExpectedPeakResult {
  if (series.length === 0) {
    return {
      status: 'unavailable',
      reason:
        'The forecast record carries a single point prediction and no lead-time series, so no ' +
        `peak over the horizon exists to compute. ${HUMAN_INPUT_REQUIRED}`,
    }
  }
  const values = series.map((point) => point.value)
  const peak = Math.max(...values)
  return { status: 'available', value: peak, units: record.provenance.targetUnits }
}

export type TimeToThresholdResult =
  | { status: 'threshold_unavailable'; reason: string }
  | { status: 'forecast_unavailable'; reason: string }
  | {
      status: 'reached'
      /** Elapsed hours from the first series point to the crossing. Null when timestamps are unusable. */
      hours: number | null
      timestamp: string
      crossingIndex: number
    }
  | { status: 'not_reached'; reason: string }

const HOUR_MS = 3_600_000

/**
 * Time until the predicted target crosses the configured threshold.
 *
 * Rules, in order:
 *
 * 1. **Threshold unavailable** — `null` threshold means nothing to cross. This
 *    wins over an empty series because even a full series could not produce a
 *    time.
 * 2. **Forecast unavailable** — an empty series cannot cross anything. This is
 *    the state the live UI reaches today, because `forecastSeriesOf` is empty.
 * 3. **Crossing** — the first point where the predicted value is `>=` the
 *    threshold. Exactly-on-the-threshold counts: it is crossed.
 * 4. **Not reached** — the series never reaches the threshold within its
 *    horizon, and the verdict says so rather than leaving the reader guessing
 *    whether the check ran.
 *
 * Elapsed time is measured between the first series point (the forecast origin)
 * and the crossing point. When the timestamps cannot be parsed, the crossing is
 * still reported — with `hours: null` — because dropping a real crossing because
 * of a formatting problem would be a different kind of lie.
 */
export function timeToThreshold(
  series: NavyaForecastSeriesPoint[],
  threshold: number | null,
): TimeToThresholdResult {
  if (threshold === null || !Number.isFinite(threshold)) {
    return {
      status: 'threshold_unavailable',
      reason: 'No flood threshold is configured, so no crossing time can be computed.',
    }
  }
  if (series.length === 0) {
    return {
      status: 'forecast_unavailable',
      reason: `No lead-time forecast series exists, so a crossing time cannot be computed. ${HUMAN_INPUT_REQUIRED}`,
    }
  }

  const crossingIndex = series.findIndex((point) => point.value >= threshold)
  if (crossingIndex === -1) {
    return {
      status: 'not_reached',
      reason: 'Not reached in forecast horizon',
    }
  }

  const origin = series[0]
  const crossing = series[crossingIndex]
  const originTime = Date.parse(origin.timestamp)
  const crossingTime = Date.parse(crossing.timestamp)
  const hours =
    Number.isFinite(originTime) && Number.isFinite(crossingTime)
      ? Math.max(0, (crossingTime - originTime) / HOUR_MS)
      : null

  return { status: 'reached', hours, timestamp: crossing.timestamp, crossingIndex }
}