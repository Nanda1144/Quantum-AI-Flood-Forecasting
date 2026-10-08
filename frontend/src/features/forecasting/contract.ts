/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Client-side honesty guards.
 *
 * ## Why the browser needs its own copy
 *
 * The backend already refuses to store an unlabelled synthetic forecast. That is
 * necessary but not sufficient: the browser is the last place a number is
 * rendered, and it is the place a screenshot is taken from. A payload that
 * reaches the UI has passed the backend, but the *display* rules are the
 * backend's to lose in a refactor, and a cached payload outlives the request that
 * validated it.
 *
 * So the rule is enforced again where the rendering happens. These are pure
 * functions — testable with no DOM, no network, and no service running.
 *
 * Every one of them returns an **absence** rather than a substitute. `null` for a
 * label means "no label is required", and it is only ever returned when the data
 * is genuinely presentable.
 */

import {
  HUMAN_INPUT_REQUIRED,
  INTEGRATION_STATEMENT,
  SYNTHETIC_DATA_DISCLAIMER,
  SYNTHETIC_METRIC_LABEL,
  type ForecastDatasetType,
  type ForecastRecord,
  type ForecastModelComparison,
  type ForecastModelComparisonRow,
  type ForecastProvenance,
} from './types'

/** A forecast may be presented as a real result only when this is true. */
export function isPresentableAsRealResult(forecast: ForecastRecord): boolean {
  return forecast.provenance.datasetType === 'real' && forecast.provenance.disclaimer === null
}

/**
 * The label the UI **must** render next to this forecast.
 *
 * Returns `null` only for a genuinely presentable forecast, so "no label" and
 * "not real data" can never coincide.
 *
 * "Unknown" provenance is deliberately **not** labelled synthetic. The data may
 * well be genuine but undocumented; calling it fake would be its own kind of lie,
 * and would teach a reader to discount the synthetic label.
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

/** Whether these metrics may be shown as a performance result, and why not. */
export function metricPresentation(
  forecast: ForecastRecord,
): { presentable: boolean; reasons: string[] } {
  const reasons: string[] = []
  if (forecast.provenance.datasetType !== 'real') {
    reasons.push(
      `the data is ${describeDatasetType(forecast.provenance.datasetType)}, not a real dataset. ` +
        'These scores describe the code, not a hydrological result.',
    )
  }
  if (forecast.metrics === null) {
    reasons.push('no metrics were measured for this forecast.')
  }
  const provenance = forecast.metricProvenance
  if (provenance === null) {
    reasons.push('no metric provenance was recorded, so the split is unknown.')
  } else {
    // Only a `test` score is held out. Both `train` and `validation` are measured
    // on data the model has already had a relationship with, so neither is an
    // estimate of performance on unseen data. The split is read directly rather
    // than inferred from the flag: a train-split score is not literally a
    // selection statistic, and a record claiming
    // `{ split: 'validation', isSelectionStatistic: false }` is self-contradictory.
    if (provenance.split === 'train') {
      reasons.push(
        'the score was measured on the train split, the data the model was fitted on. ' +
          'It is a fit statistic, not an estimate of performance on unseen data.',
      )
    }
    if (provenance.split === 'validation') {
      reasons.push(
        'the score was measured on the validation split, which the model was selected on. ' +
          'It is optimistic by construction and is not a held-out estimate.',
      )
    }
    if (provenance.isSelectionStatistic) {
      reasons.push('the record marks this score as a selection statistic, so it was optimised against.')
    }
  }
  return { presentable: reasons.length === 0, reasons }
}

/**
 * The label the UI **must** render next to these metrics.
 *
 * A synthetic score gets the short canonical phrase. Anything else gets the
 * specific reasons, because "not a held-out result" and "not real data" are
 * different problems and a reader debugging a number needs to know which it is.
 */
export function mandatoryMetricLabel(forecast: ForecastRecord): string | null {
  const { presentable, reasons } = metricPresentation(forecast)
  if (presentable) return null
  if (forecast.provenance.datasetType === 'synthetic') return SYNTHETIC_METRIC_LABEL
  return `NOT A HELD-OUT RESULT: ${reasons.join(' ')}`
}

/** A human name for a provenance class. Never a claim. */
export function describeDatasetType(type: ForecastDatasetType): string {
  switch (type) {
    case 'real':
      return 'real'
    case 'synthetic':
      return 'synthetic/demo'
    default:
      return 'of unknown provenance'
  }
}

/**
 * Provenance fields still unknown, recomputed rather than trusted.
 *
 * Recomputed because a payload's own `missingFields` is a claim made by whatever
 * produced it, and the point of this function is to be an independent check.
 */
export function openQuestions(provenance: ForecastProvenance): string[] {
  const questions: string[] = []
  if (provenance.datasetReference === null) questions.push('dataset reference')
  if (provenance.datasetLicense === null) questions.push('dataset licence')
  if (provenance.datasetChecksum === null) questions.push('dataset checksum')
  if (provenance.samplingInterval === null) questions.push('sampling interval')
  if (provenance.stationReference === null) questions.push('station reference')
  if (provenance.targetUnits === null) questions.push('target units')
  if (provenance.datasetType !== 'real') questions.push('dataset type')
  // The payload's own list is merged in rather than trusted, so a producer that
  // recorded nothing is still reported as having recorded nothing.
  for (const field of provenance.missingFields) questions.push(field)
  return [...new Set(questions)].sort()
}

/** Whether a threshold may be described as an official flood stage. */
export function thresholdIsOfficial(forecast: ForecastRecord): boolean {
  return forecast.thresholdPolicy === 'approved'
}

/**
 * A threshold description that is safe to render.
 *
 * Never returns a bare number. An unapproved threshold is rendered with its
 * pending state and its source, because a number without that context reads as a
 * validated flood stage — which is the single most dangerous thing this UI could
 * imply.
 */
export function describeThreshold(forecast: ForecastRecord): string {
  const threshold = forecast.threshold
  if (threshold === null) {
    return 'No flood threshold is configured. Risk levels are not derived from a stage.'
  }
  const units = forecast.provenance.targetUnits ?? 'units unknown'
  if (thresholdIsOfficial(forecast)) {
    return `Flood threshold ${threshold} ${units} (approved).`
  }
  const source = forecast.thresholdSource ?? 'source not recorded'
  return (
    `Flood threshold ${threshold} ${units} — PENDING approval, NOT an official flood stage. ` +
    `Source: ${source}.`
  )
}

/** One line summarising provenance, for a log or a caption. */
export function summariseProvenance(forecast: ForecastRecord): string {
  const reference = forecast.provenance.datasetReference ?? 'unrecorded'
  const station = forecast.provenance.stationReference ?? 'unrecorded'
  return (
    `dataset=${reference} type=${forecast.provenance.datasetType} station=${station} ` +
    `target=${forecast.target} horizon=${forecast.forecastHorizon} ` +
    `threshold_policy=${forecast.thresholdPolicy}`
  )
}

/** The integration statement, exported so the UI and tests share one source. */
export function integrationStatement(): string {
  return INTEGRATION_STATEMENT
}

/** The unresolved-dependency convention, for reuse in the UI. */
export function humanInputRequired(): string {
  return HUMAN_INPUT_REQUIRED
}

/**
 * The banner severity the dashboard should render for a forecast.
 *
 * `blocking` means the record must not be shown as a result at all.
 * `advisory` means it can be shown, but only with its label attached.
 */
export function bannerSeverity(forecast: ForecastRecord): 'none' | 'advisory' | 'blocking' {
  if (isPresentableAsRealResult(forecast)) return 'none'
  // Unknown provenance is not an accusation: the record is displayable, but only
  // with its caveat. Synthetic data is displayable only as a demo.
  if (forecast.provenance.datasetType === 'unknown') return 'advisory'
  if (!mandatoryForecastLabel(forecast)) return 'none'
  return forecast.provenance.datasetType === 'synthetic' ? 'blocking' : 'advisory'
}

/**
 * Can this row's scores be shown, given the comparison's own label?
 *
 * A row with no executed score has nothing to show; the table renders the
 * unavailability reason instead of a dash that could read as a zero.
 */
export function rowIsScored(row: ForecastModelComparisonRow): boolean {
  return row.executed && row.rmse !== null
}

/** The reason a row has no score, or `null` when it has one. */
export function rowUnavailableReason(row: ForecastModelComparisonRow): string | null {
  if (rowIsScored(row)) return null
  return row.unavailableReason ?? 'This candidate was not evaluated. ' + HUMAN_INPUT_REQUIRED
}

/**
 * Validate a comparison before rendering it as a result.
 *
 * Rejects the two ways a comparison quietly becomes a fabrication: a row that
 * claims to have been scored while carrying no score, and a test split that
 * participated in the ranking.
 */
export function assertComparisonIsHonest(comparison: ForecastModelComparison): void {
  for (const row of comparison.rows) {
    if (row.executed && row.rmse === null) {
      throw new Error(
        `Model '${row.key}' is marked executed but carries no score. ${HUMAN_INPUT_REQUIRED}`,
      )
    }
    if (row.selected && comparison.selectionSplit === 'test') {
      throw new Error(
        'A model was selected on the test split, which would make the held-out score a ' +
          'selection statistic.',
      )
    }
  }
  if (comparison.selectedKey === '' && comparison.rows.some((r) => r.executed)) {
    throw new Error(
      'The comparison reports executed candidates but no selected model. ' + HUMAN_INPUT_REQUIRED,
    )
  }
}
