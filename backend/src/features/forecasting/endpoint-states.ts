/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is
 * clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Availability states for the forecast + risk endpoint surfaces.
 *
 * The B3 endpoints must represent unavailable, not-evaluable, missing, or
 * dependency-blocked states honestly. The vocabulary below is the backend
 * mirror of the Phase 8 boundary status vocabulary
 * (`ai-service/app/engines/hydro/integration_assessment.py`:
 * `COMPLETE | PARTIAL | WITHHELD | NOT_EVALUABLE`) and the Phase 7 response
 * decision vocabulary (`WITHHELD | MONITOR | HEIGHTENED_MONITORING |
 * REVIEW_WARNING`), so any frontend that already renders those statuses
 * verbatim can consume these payloads without translating them.
 *
 * Everything in this file is a pure constant or pure builder: no I/O, no
 * clock reads, no random/uuid generation, no GIS computation, no quantum
 * calls. A state is a sentence with reasons, never a silence and never a
 * number ÔÇö exposure absence is `null`, never `0`, because `0` would claim an
 * evaluated zero population or infrastructure.
 */

import { HUMAN_INPUT_REQUIRED } from './candidate-risk.ts'

/** Typed availability states a successful response may carry. */
export type AvailabilityStatus = 'NOT_EVALUABLE' | 'UNAVAILABLE' | 'MISSING_CONTEXT'

/** Stable machine codes for the Navya endpoint availability states. */
export const AvailabilityCodes = {
  FORECAST_TO_STATION_MAPPING_UNAVAILABLE: 'FORECAST_TO_STATION_MAPPING_UNAVAILABLE',
  RISK_MAP_NOT_EVALUABLE: 'RISK_MAP_NOT_EVALUABLE',
  AREA_RISK_NOT_EVALUABLE: 'AREA_RISK_NOT_EVALUABLE',
} as const

/** The exact sentence required for the forecastÔåÆstation surface. */
export const STATION_MAPPING_UNAVAILABLE_MESSAGE =
  'Forecast-to-station mapping is not available in the current authoritative persistence schema.'

/**
 * Phase 7 response-decision vocabulary. `WITHHELD` remains the safe default:
 * no authoritative operational policy exists, and EVACUATE /
 * MANDATORY_EVACUATION / EMERGENCY_DECLARED are structurally unconfigurable.
 */
export const RESPONSE_DECISION_VOCABULARY = [
  'WITHHELD',
  'MONITOR',
  'HEIGHTENED_MONITORING',
  'REVIEW_WARNING',
] as const

export type ResponseDecision = (typeof RESPONSE_DECISION_VOCABULARY)[number]

/** Phase 7 states that are structurally unconfigurable today. */
export const RESPONSE_DECISION_UNCONFIGURABLE = [
  'EVACUATE',
  'MANDATORY_EVACUATION',
  'EMERGENCY_DECLARED',
] as const

export const SAFE_DEFAULT_RESPONSE_DECISION: ResponseDecision = 'WITHHELD'

/** Kinds of exposure/response readings the risk surfaces can honestly carry. */
export type ExposureKind = 'population_exposure' | 'infrastructure_exposure' | 'response_priority'

/** A single availability reading ÔÇö mirrors the frontend's `NavyaExposureReading`. */
export interface ExposureReading {
  kind: ExposureKind
  availability: 'NOT_EVALUABLE'
  value: null
  reason: string
}

export type NavyaExposureReading = ExposureReading

/** The exposure + response block shared by the risk surfaces. */
export interface ExposureBlock {
  readings: NavyaExposureReading[]
  responsePriority: {
    decision: 'WITHHELD'
    availability: 'NOT_EVALUABLE'
    value: null
    reason: string
  }
}

/** GET /api/forecast/station/:id ÔÇö typed NOT_EVALUABLE state. */
export interface StationForecastResponse {
  status: 'NOT_EVALUABLE'
  code: typeof AvailabilityCodes.FORECAST_TO_STATION_MAPPING_UNAVAILABLE
  stationId: string
  message: string
  reasons: readonly string[]
}

/** GET /api/risk-map ÔÇö typed NOT_EVALUABLE state with exposure availability. */
export interface RiskMapResponse {
  status: 'NOT_EVALUABLE'
  code: typeof AvailabilityCodes.RISK_MAP_NOT_EVALUABLE
  message: string
  reasons: readonly string[]
  exposure: ExposureBlock
}

/** GET /api/risk/:areaId ÔÇö typed NOT_EVALUABLE state for one area. */
export interface RiskAreaResponse {
  status: 'NOT_EVALUABLE'
  code: typeof AvailabilityCodes.AREA_RISK_NOT_EVALUABLE
  areaId: string
  message: string
  reasons: readonly string[]
  exposure: ExposureBlock
}

const RISK_EXPOSURE_REASONS = {
  population:
    'No population-exposure dataset exists in the repository; a 0 would falsely claim an evaluated zero population.',
  infrastructure:
    'No infrastructure-exposure dataset exists in the repository; a 0 would falsely claim an evaluated zero infrastructure.',
  response:
    `WITHHELD is the Phase 7 safe default: no authoritative operational policy exists, so B3 computes no response priority. ${HUMAN_INPUT_REQUIRED}`,
} as const

export function exposureBlock(): ExposureBlock {
  const readings: NavyaExposureReading[] = [
    { kind: 'population_exposure', availability: 'NOT_EVALUABLE', value: null, reason: RISK_EXPOSURE_REASONS.population },
    { kind: 'infrastructure_exposure', availability: 'NOT_EVALUABLE', value: null, reason: RISK_EXPOSURE_REASONS.infrastructure },
    { kind: 'response_priority', availability: 'NOT_EVALUABLE', value: null, reason: RISK_EXPOSURE_REASONS.response },
  ]
  return {
    readings,
    responsePriority: { decision: 'WITHHELD', availability: 'NOT_EVALUABLE', value: null, reason: RISK_EXPOSURE_REASONS.response },
  }
}

const RISK_MAP_REASONS = [
  'No authoritative GIS stationÔåÆreach mapping exists in the repository.',
  'No population-exposure dataset exists in the repository.',
  'No infrastructure-exposure dataset exists in the repository.',
  'No authoritative area-risk dataset exists in the repository.',
  `B3 computes no risk scores or Q-FLARE response priorities. ${HUMAN_INPUT_REQUIRED}`,
] as const

const RISK_AREA_REASONS = [
  'No authoritative area registry exists in the repository.',
  'No authoritative area-risk dataset exists in the repository.',
  `B3 computes no risk scores or Q-FLARE response priorities. ${HUMAN_INPUT_REQUIRED}`,
] as const

/** GET /api/forecast/station/:id ÔÇö structural: the schema has no station FK. */
export function stationForecastState(stationId: string): StationForecastResponse {
  return {
    status: 'NOT_EVALUABLE',
    code: AvailabilityCodes.FORECAST_TO_STATION_MAPPING_UNAVAILABLE,
    stationId,
    message: STATION_MAPPING_UNAVAILABLE_MESSAGE,
    reasons: [
      'The forecasts table (migration 001) has no station foreign key.',
      'No station registry or stationÔåÆforecast mapping exists anywhere in the repository.',
      'Nearest-station or coordinate inference is forbidden: it would fabricate a relationship.',
      HUMAN_INPUT_REQUIRED,
    ],
  }
}

/** GET /api/risk-map ÔÇö no authoritative GIS/exposure/area data exists. */
export function riskMapState(): RiskMapResponse {
  return {
    status: 'NOT_EVALUABLE',
    code: AvailabilityCodes.RISK_MAP_NOT_EVALUABLE,
    message:
      'No authoritative area-risk dataset or GIS mapping exists, so a risk map cannot be evaluated.',
    reasons: RISK_MAP_REASONS,
    exposure: exposureBlock(),
  }
}

/** GET /api/risk/:areaId ÔÇö no authoritative area-risk dataset exists. */
export function riskAreaState(areaId: string): RiskAreaResponse {
  return {
    status: 'NOT_EVALUABLE',
    code: AvailabilityCodes.AREA_RISK_NOT_EVALUABLE,
    areaId,
    message: 'No authoritative risk dataset exists for this area, so it cannot be evaluated.',
    reasons: RISK_AREA_REASONS,
    exposure: exposureBlock(),
  }
}
