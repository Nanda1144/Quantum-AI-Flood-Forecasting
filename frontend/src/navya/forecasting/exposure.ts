/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Exposure and response-priority availability for the risk dashboard.
 *
 * The task requires population exposure, infrastructure exposure and a Q-FLARE
 * response priority. None of the three has a data path:
 *
 * - The forecast contract (`NavyaForecastRecord`) has no exposure fields at all.
 * - The Phase 8 boundary (`ai-service/app/engines/hydro/response_context.py`)
 *   models exposure *availability* (`ExposureAvailability`) but carries **no
 *   values**, and nothing on the boundary is exposed to the frontend through an
 *   HTTP endpoint.
 * - The Phase 8 integration assessment (`integration_assessment.py`) uses the
 *   status vocabulary `COMPLETE | PARTIAL | WITHHELD | NOT_EVALUABLE` for how
 *   far a forecast can be assessed into risk and response.
 *
 * So the frontend can truthfully render **status only**, never a number. The
 * status vocabulary below is a frontend mirror of that Phase 8 boundary
 * vocabulary, and every reading in this revision is `NOT_EVALUABLE` with a
 * reason: no exposure assessment is *sent* to the browser, so nothing could be
 * evaluated. A future backend response is rendered verbatim — this component
 * will never upgrade, downgrade or override a status, because overriding an
 * upstream withholding is exactly how a "not evaluated" becomes a "fine".
 *
 * No population count, no affected-people figure, no exposure percentage, no
 * infrastructure inventory and no damage estimate can ever be produced by this
 * module. The `value` field exists so the rendering contract is explicit that a
 * value *would* have somewhere to go, and it is always `null`.
 */

import { HUMAN_INPUT_REQUIRED, type NavyaForecastRecord } from './types'

/**
 * Frontend mirror of the Phase 8 integration status vocabulary
 * (`ai-service/app/engines/hydro/integration_assessment.py`).
 */
export type NavyaExposureAvailability = 'COMPLETE' | 'PARTIAL' | 'WITHHELD' | 'NOT_EVALUABLE'

/** Which exposure kind a reading describes. */
export type NavyaExposureKind =
  | 'population_exposure'
  | 'infrastructure_exposure'
  | 'response_priority'

/** A single exposure/response reading: status plus the reason for it. */
export interface NavyaExposureReading {
  kind: NavyaExposureKind
  availability: NavyaExposureAvailability
  /** The only place a value may live. Always `null` in this revision. */
  value: null
  reason: string
}

/** Why population exposure cannot be shown. */
export const POPULATION_EXPOSURE_REASON =
  'The forecast contract carries no population exposure assessment, and the Phase 8 boundary ' +
  `exposes availability only, with no values. ${HUMAN_INPUT_REQUIRED}`

/** Why infrastructure exposure cannot be shown. */
export const INFRASTRUCTURE_EXPOSURE_REASON =
  'The forecast contract carries no infrastructure exposure assessment, and the Phase 8 ' +
  `boundary exposes availability only, with no values. ${HUMAN_INPUT_REQUIRED}`

/** Why a Q-FLARE response priority cannot be shown. */
export const RESPONSE_PRIORITY_REASON =
  'No response-priority contract reaches the frontend. Phase 8 defines the status vocabulary, ' +
  `but the forecast-to-response boundary is not served over HTTP. ${HUMAN_INPUT_REQUIRED}`

/**
 * Population exposure reading.
 *
 * Always `NOT_EVALUABLE`: an assessment is not merely withheld, it was never
 * evaluated and never sent. If the backend ever returns a status, this function
 * should pass it through — the frontend must not invent the verdict.
 */
export function populationExposure(
  _record: NavyaForecastRecord,
): NavyaExposureReading {
  return {
    kind: 'population_exposure',
    availability: 'NOT_EVALUABLE',
    value: null,
    reason: POPULATION_EXPOSURE_REASON,
  }
}

/** Infrastructure exposure reading. See `populationExposure`. */
export function infrastructureExposure(
  _record: NavyaForecastRecord,
): NavyaExposureReading {
  return {
    kind: 'infrastructure_exposure',
    availability: 'NOT_EVALUABLE',
    value: null,
    reason: INFRASTRUCTURE_EXPOSURE_REASON,
  }
}

/** Q-FLARE response-priority reading. See `populationExposure`. */
export function responsePriority(
  _record: NavyaForecastRecord,
): NavyaExposureReading {
  return {
    kind: 'response_priority',
    availability: 'NOT_EVALUABLE',
    value: null,
    reason: RESPONSE_PRIORITY_REASON,
  }
}

/** All three readings in display order. */
export function exposureReadings(record: NavyaForecastRecord): NavyaExposureReading[] {
  return [populationExposure(record), infrastructureExposure(record), responsePriority(record)]
}

/** A human-safe sentence for a reading. Never contains a number. */
export function describeExposureReading(reading: NavyaExposureReading): string {
  return `${reading.availability}: ${reading.reason}`
}