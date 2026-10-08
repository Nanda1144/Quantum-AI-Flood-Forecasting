/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { isThresholdOfficial, openProvenanceQuestions } from './contract.ts'
import {
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
  type DatasetType,
  type ForecastProvenance,
  type MetricProvenance,
  type ForecastRecord,
  type ThresholdPolicy,
} from './types.ts'

/**
 * Provenance guards for forecast data entering the backend.
 *
 * The failure these prevent is specific and easy to miss: a synthetic or
 * unlabelled forecast gets cached, replayed, and displayed weeks later by code
 * that has no idea where it came from. By then the disclaimer is gone and the
 * number looks real.
 *
 * Each guard below is a pure function, so the rule is testable without a
 * database, an HTTP client, or a running service.
 */

/** A forecast may not be presented as a real result when this is false. */
export function isPresentableAsRealResult(forecast: ForecastRecord): boolean {
  return forecast.provenance.datasetType === 'real' && forecast.provenance.disclaimer === null
}

/**
 * Metrics may be shown as a performance result only when they were measured on
 * held-out data from a real dataset.
 *
 * Three independent conditions, because each can be wrong on its own: synthetic
 * data, a score the model was selected on, or a score with no provenance at all.
 */
export function areMetricsPresentableAsResult(
  forecast: ForecastRecord,
): { presentable: boolean; reasons: string[] } {
  const reasons: string[] = []
  if (forecast.provenance.datasetType !== 'real') {
    reasons.push(
      `dataset_type is '${forecast.provenance.datasetType}', not 'real'. ` +
        'These metrics describe the code, not a hydrological result.',
    )
  }
  if (forecast.metrics === null) {
    reasons.push('no metrics were attached to this forecast.')
  }
  const metricProvenance: MetricProvenance | null = forecast.metricProvenance
  if (metricProvenance === null) {
    reasons.push('no metric provenance was recorded, so the split is unknown.')
  } else {
    // Only a `test` score is held out. Both train and validation are scored on
    // data the model has already had a relationship with, so neither is an
    // estimate of performance on unseen data.
    //
    // The split is checked directly rather than trusting `isSelectionStatistic`
    // alone, for two reasons: a train-split score is not held out even though it
    // is not literally the selection statistic, and a record claiming
    // `{ split: 'validation', isSelectionStatistic: false }` is self-contradictory
    // and must not be reported either way. Reading the flag alone would let both
    // through.
    if (metricProvenance.split === 'train') {
      reasons.push(
        "the score was measured on the 'train' split, the data the model was fitted on. " +
          'It is a fit statistic, not an estimate of performance on unseen data.',
      )
    }
    if (metricProvenance.split === 'validation') {
      reasons.push(
        `the score was measured on the '${metricProvenance.split}' split, which the model was ` +
          'selected on. It is optimistic by construction and is not a held-out estimate.',
      )
    }
    if (metricProvenance.isSelectionStatistic) {
      reasons.push(
        'the record marks this score as a selection statistic, so it was optimised against ' +
          'rather than merely observed.',
      )
    }
  }
  return { presentable: reasons.length === 0, reasons }
}

/**
 * The label a consumer must display next to this forecast.
 *
 * Returns `null` only when the forecast is genuinely presentable. Anything else
 * gets a mandatory label, so "no label" and "not real data" cannot coincide.
 */
export function mandatoryForecastLabel(forecast: ForecastRecord): string | null {
  if (isPresentableAsRealResult(forecast)) return null
  if (forecast.provenance.datasetType === 'synthetic') return SYNTHETIC_DATA_DISCLAIMER
  if (forecast.provenance.datasetType === 'unknown') {
    return (
      'UNVERIFIED PROVENANCE: the source of this forecast is not recorded. ' +
      'It must not be presented as a hydrological observation.'
    )
  }
  return forecast.provenance.disclaimer
}

/** The label a consumer must display next to these metrics. */
export function mandatoryMetricLabel(forecast: ForecastRecord): string | null {
  const { presentable } = areMetricsPresentableAsResult(forecast)
  if (presentable) return null
  if (forecast.provenance.datasetType === 'synthetic') return SYNTHETIC_METRIC_LABEL
  const reasons = areMetricsPresentableAsResult(forecast).reasons
  return `NOT A HELD-OUT RESULT: ${reasons.join(' ')}`
}

/**
 * Throw when a forecast is about to be persisted or relayed in a way that would
 * strip its provenance.
 *
 * This is the enforcement point for the rule that an unlabelled synthetic
 * forecast must never reach durable storage.
 */
export function assertForecastMayBeStored(forecast: ForecastRecord): void {
  if (forecast.provenance.datasetType === 'synthetic' && forecast.provenance.disclaimer === null) {
    throw new Error(
      'Refusing to store a synthetic forecast without its disclaimer. ' +
        'A cached synthetic forecast outlives the session that labelled it.',
    )
  }
}

/** Throw when a metric is about to be reported as a result. */
export function assertMetricsMayBeReported(forecast: ForecastRecord): void {
  const { presentable, reasons } = areMetricsPresentableAsResult(forecast)
  if (!presentable) {
    throw new Error(`Refusing to report these metrics as a result: ${reasons.join(' ')}`)
  }
}

/** The provenance fields still unknown, recomputed rather than trusted. */
export function openQuestions(forecast: ForecastRecord): string[] {
  const declared = new Set(forecast.provenance.missingFields)
  const computed = openProvenanceQuestions(forecast.provenance)
  return [...new Set([...computed, ...declared])].sort()
}

/** Whether a threshold may be described as an official flood stage. */
export function thresholdIsOfficial(forecast: ForecastRecord): boolean {
  return isThresholdOfficial(forecast.thresholdPolicy)
}

/**
 * A description of a threshold, safe to render.
 *
 * Never returns a bare number. An unapproved threshold is rendered with its
 * source and its `pending` state, because a number without that context reads as
 * a validated flood stage.
 */
export function describeThreshold(forecast: ForecastRecord): string {
  const threshold: number | null = forecast.threshold
  if (threshold === null) {
    return 'No flood threshold is configured. Risk levels are not derived from a stage.'
  }
  const units: string = forecast.provenance.targetUnits ?? 'units unknown'
  const policy: ThresholdPolicy = forecast.thresholdPolicy
  if (policy === 'approved') {
    return `Flood threshold ${threshold} ${units} (approved).`
  }
  const source: string = forecast.thresholdSource ?? 'source not recorded'
  return (
    `Flood threshold ${threshold} ${units} — PENDING approval, NOT an official flood stage. ` +
    `Source: ${source}.`
  )
}

/** A compact, one-line provenance summary for logs. */
export function summariseProvenance(
  forecast: ForecastRecord,
  datasetType?: DatasetType,
): string {
  const type: DatasetType = datasetType ?? forecast.provenance.datasetType
  const reference: string = forecast.provenance.datasetReference ?? 'unrecorded'
  const station: string = forecast.provenance.stationReference ?? 'unrecorded'
  return (
    `dataset=${reference} type=${type} station=${station} ` +
    `target=${forecast.target} horizon=${forecast.forecastHorizon} ` +
    `threshold_policy=${forecast.thresholdPolicy}`
  )
}

/** Re-exported so consumers need only one import. */
export type { ForecastProvenance, MetricProvenance, ThresholdPolicy }
