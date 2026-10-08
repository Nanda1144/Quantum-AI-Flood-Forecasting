/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform . It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { normalizeCandidateRisk } from './contract.ts'
import type {
  CandidateRiskAttribution,
  CandidateRiskMappingSpec,
  ForecastRecord,
} from './types.ts'

/**
 * Candidate-risk attribution: how a station-level flood forecast relates to the
 * individual sites the optimizer will place sensors at.
 *
 * ## The current state of this problem
 *
 * A station forecast is a value at one point on one reach. Attributing risk to a
 * candidate location requires knowing how that location relates to the station —
 * distance along the reach, elevation offset, tributary contribution, catchment
 * area. **None of that exists in this repository.**
 *
 * Two facts pin this down precisely:
 *
 * 1. `CandidateLocation` (team-owned, `src/types/optimization.ts`) has **no
 *    station key**. Its fields are `id`, `name`, `zone`, `latitude`,
 *    `longitude`, `floodRisk`, `populationExposure`, `infrastructureCriticality`,
 *    `communicationScore`, `sensorCostK`, `coverageRadiusKm`. There is nothing to
 *    join a station forecast on.
 * 2. `CandidateLocation.floodRisk` **already exists** and is consumed by
 *    `siteUtility()` in the QUBO builder. It is supplied by the GIS candidate
 *    store, not by the forecast. Its own provenance is not established anywhere
 *    in this repository.
 *
 * The consequence is worth stating plainly: **forecast-derived risk does not
 * reach the optimizer's objective today, and adding it would mean changing the
 * QUBO builder, which is team-owned.** Replacing `candidate.floodRisk` with a
 * forecast-derived value would silently change every optimization result the
 * platform has produced, so that change cannot be made here.
 *
 * Inventing a mapping — nearest-neighbour by coordinates, a uniform risk split, a
 * distance-decay function — would produce a number that looks like a hydrological
 * result and is not one. It would also be silently wrong in the specific way that
 * matters: it would over- and under-state risk with no signal that it had done so.
 *
 * So this module does the honest thing:
 *
 * - It **declares the mapping as unavailable** rather than approximating it.
 * - `derivedFloodRisk` is `null`, not a guess.
 * - `isSynthetic` is `true` until an authoritative mapping is supplied.
 * - Every unresolved dependency is named with the platform's
 *   "NOT FOUND … HUMAN / TEAM INPUT REQUIRED" convention.
 */

/** The exact convention used across the platform for an unresolved dependency. */
export const HUMAN_INPUT_REQUIRED = 'NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED'

/** Why the mapping cannot currently be produced. */
export const MAPPING_BLOCKERS: readonly string[] = [
  'Authoritative station identifiers and a station register.',
  'A station-to-candidate-location mapping. CandidateLocation carries no station key.',
  'Reach geometry and topology, to propagate a station forecast downstream.',
  'Elevation datum and terrain, to relate stage to a specific site.',
  'A documented rule for how forecast risk attenuates along a reach.',
  'Provenance for the existing CandidateLocation.floodRisk supplied by the GIS module, ' +
    'which is what the QUBO builder actually consumes today.',
] as const

/**
 * Build the mapping spec for a forecast, declaring it unavailable.
 *
 * Always returns a spec — there is no "no mapping" return — because the honest
 * answer is a spec whose `derivedFloodRisk` fields are `null` and whose
 * `synthetic` flag is `true`. A missing object invites a caller to substitute
 * something; a present, clearly-marked empty one does not.
 */
export function buildCandidateRiskMapping(
  forecast: ForecastRecord,
  candidateLocationIds: readonly string[],
): CandidateRiskMappingSpec {
  return {
    forecastId: forecast.forecastId,
    synthetic: true,
    source:
      'No station-to-candidate-location mapping exists. ' + HUMAN_INPUT_REQUIRED,
    attributions: candidateLocationIds.map((id) => unattributed(forecast, id)),
  }
}

/**
 * One candidate's attribution, with the risk explicitly left un-derived.
 */
function unattributed(
  forecast: ForecastRecord,
  candidateLocationId: string,
): CandidateRiskAttribution {
  return {
    candidateLocationId,
    forecastId: forecast.forecastId,
    stationReference: forecast.provenance.stationReference,
    reachReference: null,
    forecastRiskScore: forecast.riskScore,
    // null, not 0 and not forecastRiskScore: we do not know this site's risk.
    derivedFloodRisk: null,
    mappingProvenance: `Unmapped candidate. ${HUMAN_INPUT_REQUIRED}`,
    isSynthetic: true,
    notes: [
      'derivedFloodRisk is null because no station-to-candidate mapping is available.',
      'Assigning this candidate the station risk would assume every site shares the station stage.',
      'Assigning it zero would assert no flood risk, which is equally unevidenced.',
      ...MAPPING_BLOCKERS,
    ],
  }
}

/**
 * Attach a derived risk to a candidate, for when a real mapping becomes
 * available.
 *
 * `mappingProvenance` is **required**: an attribution that cannot cite where its
 * number came from is not usable, and the team-owned side cannot be modified to
 * enforce that, so the check lives here.
 */
export function withDerivedRisk(
  attribution: CandidateRiskAttribution,
  derivedFloodRisk: number | null,
  mappingProvenance: string | null,
  notes: readonly string[] = [],
): CandidateRiskAttribution {
  if (mappingProvenance === null || mappingProvenance.trim() === '') {
    throw new Error(
      'A candidate risk attribution must cite its mapping provenance. ' + HUMAN_INPUT_REQUIRED,
    )
  }
  const normalized = normalizeCandidateRisk(derivedFloodRisk)
  return {
    ...attribution,
    derivedFloodRisk: normalized,
    mappingProvenance,
    // A real derivation clears the synthetic flag, but only if the risk is
    // actually present. A null risk stays unattributed regardless of the note.
    isSynthetic: normalized === null,
    notes: [...attribution.notes, ...notes],
  }
}

/**
 * Validate a spec before it is trusted.
 *
 * Rejects the two ways a mapping quietly becomes a fabrication: claiming to be
 * real while carrying un-derived risks, and mixing candidates from different
 * forecasts.
 */
export function validateCandidateRiskMapping(spec: CandidateRiskMappingSpec): void {
  for (const attribution of spec.attributions) {
    if (attribution.forecastId !== spec.forecastId) {
      throw new Error(
        `Attribution for candidate '${attribution.candidateLocationId}' references forecast ` +
          `'${attribution.forecastId}' but the spec is for forecast '${spec.forecastId}'.`,
      )
    }
    if (attribution.derivedFloodRisk === null && !attribution.isSynthetic) {
      throw new Error(
        `Candidate '${attribution.candidateLocationId}' has no derived flood risk but is not ` +
          `marked synthetic. ${HUMAN_INPUT_REQUIRED}`,
      )
    }
    if (!attribution.isSynthetic && attribution.mappingProvenance.trim() === '') {
      throw new Error(
        `Candidate '${attribution.candidateLocationId}' is marked real but cites no mapping ` +
          `provenance.`,
      )
    }
  }
  if (!spec.synthetic && spec.attributions.length > 0) {
    const unDerived = spec.attributions.filter((a) => a.derivedFloodRisk === null)
    if (unDerived.length > 0) {
      throw new Error(
        `Spec claims to be real but ${unDerived.length} candidate(s) have no derived risk. ` +
          HUMAN_INPUT_REQUIRED,
      )
    }
  }
}

/**
 * The forecast-level risk only — the one number that is genuinely known today.
 *
 * Useful as an explicitly coarse input: it says "this reach is at risk", and says
 * nothing about which site is worst-affected.
 */
export function forecastLevelRisk(forecast: ForecastRecord): number {
  return forecast.riskScore
}

/** A one-line statement of what is and is not known. */
export function describeMappingLimitations(): string {
  return [
    'Candidate-level flood risk is NOT AVAILABLE.',
    'Blocked by:',
    ...MAPPING_BLOCKERS.map((blocker) => `  - ${blocker}`),
    `Result: every candidate carries derivedFloodRisk = null. ${HUMAN_INPUT_REQUIRED}`,
  ].join('\n')
}
