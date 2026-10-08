/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import {
  INTEGRATION_STATEMENT,
  type ExistingOptimizationPayload,
  type ForecastProvenance,
  type ForecastTarget,
  type ForecastRecord,
  type ProposedForecastHandoff,
  type ThresholdPolicy,
} from './types.ts'
import type { RiskLevel } from '../../types/contract.ts'

/**
 * Pure builders that narrow a forecast record down to what the running
 * optimizer can accept, and back out exactly what it cannot.
 *
 * These are intentionally plain functions with no I/O. A handoff that depends on
 * a live forecast is a handoff nobody can unit-test, and the mapping is exactly
 * the part most worth testing: it is where a field silently becomes a claim.
 */

/** Platform priority vocabulary, matching `ForecastSyncService`. */
export type OptimizationPriority = 'low' | 'medium' | 'high' | 'critical'

/** Keys of `ExistingOptimizationPayload` that are actually required today. */
export const REQUIRED_EXISTING_FIELDS = ['forecast_id'] as const

/**
 * Map a risk level onto the platform priority.
 *
 * Matches the mapping `ForecastSyncService` and `OptimizationService` already
 * apply, so a handoff built here never contradicts what the platform stored from
 * the same forecast. An unrecognised level maps to `low` rather than throwing:
 * the optimizer still receives an explicit `risk_score` and can rank on that, so
 * the right failure mode is a conservative priority, not a dead request.
 */
export function priorityForRiskLevel(riskLevel: RiskLevel | null | undefined): OptimizationPriority {
  switch (riskLevel) {
    case 'CRITICAL':
      return 'critical'
    case 'HIGH':
      return 'high'
    case 'MEDIUM':
      return 'medium'
    default:
      return 'low'
  }
}

/**
 * Build the payload the running `POST /api/optimization/from-forecast` accepts.
 *
 * Every key emitted here is understood by the current backend. No field is sent
 * that the running zod schema would reject or silently drop.
 *
 * ## Why the availability flags are sent as `false`
 *
 * `OptimizationService.createFromForecast` resolves them as
 * `payload.candidate_locations_available ?? true`. Omitting them therefore makes
 * the platform persist `candidateLocationsAvailable: true` — a claim that
 * candidate locations and resource constraints are available. They are not: no
 * authoritative candidate set and no resource-constraint source exist in this
 * repository, and inventing either would be fabrication.
 *
 * Sending `false` records the truth and makes the downstream job report itself
 * as not ready, instead of looking ready and failing later for a reason that
 * looks unrelated to forecasting.
 */
export function toExistingOptimizationPayload(
  forecast: ForecastRecord,
  options: {
    /** Override when a real candidate set has been sourced. */
    candidateLocationsAvailable?: boolean
    /** Override when real resource constraints have been sourced. */
    resourceConstraintsAvailable?: boolean
  } = {},
): ExistingOptimizationPayload {
  const payload: ExistingOptimizationPayload = {
    forecast_id: forecast.forecastId,
    candidate_locations_available: options.candidateLocationsAvailable ?? false,
    resource_constraints_available: options.resourceConstraintsAvailable ?? false,
  }
  if (Number.isFinite(forecast.riskScore)) {
    payload.risk_score = forecast.riskScore
  }
  if (forecast.riskLevel) {
    payload.priority = priorityForRiskLevel(forecast.riskLevel)
  }
  return payload
}

/**
 * Fields the running backend understands but that are **not** sent today,
 * because there is no team-owned slot for them.
 *
 * Kept as data rather than as prose so a test can assert the list, and so a
 * reviewer can diff it against a future `contract.ts` change.
 */
export const FIELDS_REQUIRING_INTEGRATION: readonly string[] = [
  'flood_probability',
  'risk_level',
  'predicted_value',
  'predicted_inflow',
  'target',
  'target_units',
  'forecast_horizon',
  'forecast_timestamp',
  'threshold',
  'threshold_policy',
  'residual_sigma',
  'station_reference',
  'provenance_reference',
  'dataset_type',
  'status',
  'contract_version',
] as const

/**
 * Build the full proposed handoff.
 *
 * **Not consumable by the running backend today.** It is the target shape, and
 * `fieldsRequiringIntegration()` reports what a team owner must add before it
 * can be posted.
 */
export function toProposedForecastHandoff(forecast: ForecastRecord): ProposedForecastHandoff {
  return {
    contract_version: forecast.provenance.contractVersion,
    forecast_id: forecast.forecastId,
    forecast_timestamp: forecast.forecastTimestamp,
    forecast_horizon: forecast.forecastHorizon,
    target: forecast.target,
    target_units: forecast.targetUnits,
    predicted_value: forecast.predictedValue,
    predicted_water_level: forecast.predictedWaterLevel,
    predicted_inflow: forecast.predictedInflow,
    flood_probability: forecast.floodProbability,
    risk_level: forecast.riskLevel,
    risk_score: forecast.riskScore,
    threshold: forecast.threshold,
    threshold_policy: forecast.thresholdPolicy,
    residual_sigma: forecast.residualSigma,
    station_reference: forecast.provenance.stationReference,
    provenance_reference: forecast.provenance.datasetReference,
    dataset_type: forecast.provenance.datasetType,
    status: forecast.status,
    integration_statement: INTEGRATION_STATEMENT,
  }
}

/** Names every proposed field that still needs a team-owner change. */
export function fieldsRequiringIntegration(): string[] {
  return [...FIELDS_REQUIRING_INTEGRATION]
}

/**
 * A short, human-readable summary of the handoff. Used by logs and by the
 * module README, and asserted by tests so the statement cannot be dropped.
 */
export function describeHandoff(forecast: ForecastRecord): string {
  const existing = toExistingOptimizationPayload(forecast)
  const lines = [
    'FORECAST -> OPTIMIZATION HANDOFF',
    `  contract_version : ${forecast.provenance.contractVersion}`,
    `  ${INTEGRATION_STATEMENT}`,
    '  accepted by the running optimizer today:',
    ...Object.entries(existing).map(([key, value]) => `    ${key} = ${JSON.stringify(value)}`),
    '  proposed fields pending team-owner integration:',
    ...fieldsRequiringIntegration().map((field) => `    ${field}`),
  ]
  return lines.join('\n')
}

/**
 * Normalise a candidate risk score into `0..1`, or `null` when absent.
 *
 * Out-of-range input is clamped rather than rejected, because a risk score that
 * has already been computed and is merely scaled should not crash a handoff.
 * Non-finite input returns `null` — the honest answer — rather than `0`, which
 * would read as "no flood risk at this candidate".
 */
export function normalizeCandidateRisk(value: number | null | undefined): number | null {
  if (value === null || value === undefined) return null
  if (!Number.isFinite(value)) return null
  if (value < 0) return 0
  if (value > 1) return 1
  return value
}

/**
 * Decide whether a threshold policy may be displayed as official.
 *
 * Only `approved` may. `pending` means a number is in use that nobody has signed
 * off, which is a materially different claim.
 */
export function isThresholdOfficial(policy: ThresholdPolicy): boolean {
  return policy === 'approved'
}

/** The target a forecast is for, validated against the two supported options. */
export function assertKnownTarget(target: string): ForecastTarget {
  if (target === 'water_level' || target === 'inflow') return target
  throw new Error(
    `Unsupported forecast target '${target}'. Supported targets are 'water_level' and 'inflow'.`,
  )
}

/** Provenance fields that are still unknown, recomputed from a record. */
export function openProvenanceQuestions(provenance: ForecastProvenance): string[] {
  const questions: string[] = []
  if (provenance.datasetReference === null) questions.push('datasetReference')
  if (provenance.datasetLicense === null) questions.push('datasetLicense')
  if (provenance.datasetChecksum === null) questions.push('datasetChecksum')
  if (provenance.samplingInterval === null) questions.push('samplingInterval')
  if (provenance.stationReference === null) questions.push('stationReference')
  if (provenance.targetUnits === null) questions.push('targetUnits')
  if (provenance.datasetType !== 'real') questions.push('datasetType')
  return questions
}
