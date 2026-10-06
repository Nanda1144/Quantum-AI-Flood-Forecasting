/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Decision reasoning for the Optimization Result page — pure, shared by the
 * location table, the map and the explanation panel.
 *
 * Every sentence is assembled from fields the gateway already stored
 * (`objectiveBreakdown`, `coverage`, `constraintViolations`,
 * `classicalComparison`, the job's resolved constraints). Nothing is inferred
 * from raw geometry and no causal claim is invented: the panel reports the
 * stored contributions and validation outcome, and it explicitly refuses to
 * recommend an infeasible selection.
 */

import type { CandidateLocation, OptimizationResult, QuantumJobSummary } from '../types/optimization'
import { formatScore } from './quantum'

/**
 * Display-only risk cutoff for the map/table legend. The risk values are the
 * GIS module's stored floodRisk scores; the threshold is a UI affordance and is
 * labelled as such wherever it is shown.
 */
export const HIGH_RISK_THRESHOLD = 0.6

export interface LocationRow {
  id: string
  name: string
  zone: string
  latitude: number | null
  longitude: number | null
  floodRisk: number | null
  /** GIS population exposure for the site (0–1), or null when unknown. */
  populationExposure: number | null
  /** GIS infrastructure criticality for the site (0–1), or null when unknown. */
  infrastructureCriticality: number | null
  selected: boolean
  highRisk: boolean
}

/**
 * Join the decoded selection with the federated GIS candidates. When the
 * geometry is unreachable only the selected sites are known, so the rows carry
 * null coordinates and the page says so — no placeholder geometry is invented.
 */
export function buildLocationRows(candidates: CandidateLocation[] | null, result: OptimizationResult): LocationRow[] {
  const selectedIds = new Set(result.selectedLocations.map((site) => site.id))

  if (candidates && candidates.length > 0) {
    return candidates
      .map((candidate) => ({
        id: candidate.id,
        name: candidate.name,
        zone: candidate.zone,
        latitude: candidate.latitude,
        longitude: candidate.longitude,
        floodRisk: candidate.floodRisk,
        populationExposure: candidate.populationExposure,
        infrastructureCriticality: candidate.infrastructureCriticality,
        selected: selectedIds.has(candidate.id),
        highRisk: candidate.floodRisk >= HIGH_RISK_THRESHOLD,
      }))
      .sort((a, b) => Number(b.selected) - Number(a.selected) || a.id.localeCompare(b.id))
  }

  return result.selectedLocations.map((site) => ({
    id: site.id,
    name: site.name,
    zone: site.zone,
    latitude: null,
    longitude: null,
    floodRisk: site.floodRisk,
    populationExposure: site.populationCovered,
    infrastructureCriticality: site.infrastructureCovered,
    selected: true,
    highRisk: site.floodRisk >= HIGH_RISK_THRESHOLD,
  }))
}

export interface DecisionNarrative {
  headline: string
  reasons: string[]
  caveats: string[]
}

function coverageLine(result: OptimizationResult): string | null {
  const coverage = result.coverage
  if (!coverage) return null
  const population = coverage.populationTotal > 0 ? formatScore(coverage.populationCovered / coverage.populationTotal) : null
  const infrastructure =
    coverage.infrastructureTotal > 0 ? formatScore(coverage.infrastructureCovered / coverage.infrastructureTotal) : null
  if (population === null && infrastructure === null) return null
  return `The selected set covers ${population ?? '—'} of the exposed population and ${infrastructure ?? '—'} of critical infrastructure.`
}

/**
 * Factual, input-derived explanation. Reasons describe what the stored result
 * contains; caveats carry the honesty guardrails (invalid selection, no
 * advantage claim).
 */
export function decisionExplanation(summary: QuantumJobSummary, result: OptimizationResult): DecisionNarrative {
  const valid = result.validationStatus === 'valid' && result.constraintViolations.length === 0
  const ways: string[] = []
  const caveats: string[] = []

  const candidateCount = summary.variablesCount ?? result.qubits
  const maxSensors = summary.constraints?.maxSensors ?? null
  ways.push(
    `The decoder selected ${result.selectedLocations.length} of ${candidateCount} candidate sites` +
      `${maxSensors !== null ? `, within the configured sensor limit of ${maxSensors}` : ''}.`,
  )

  const total = result.objectiveBreakdown.reduce((sum, entry) => sum + entry.value, 0)
  const axes = [...result.objectiveBreakdown]
    .filter((entry) => entry.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)
  if (axes.length > 0) {
    const share = (value: number) => formatScore(total > 0 ? value / total : 0)
    ways.push(
      `The weighted objective was driven mainly by ${axes
        .map((entry) => `${entry.label} (${share(entry.value)} of the captured utility)`)
        .join(', ')}.`,
    )
  }

  const coverage = coverageLine(result)
  if (coverage) ways.push(coverage)

  const classical = result.classicalComparison
  ways.push(
    `The stored classical reference (${classical.method || 'reference solver'}) returned ` +
      `${formatScore(classical.objectiveValue)} against the quantum path's ${formatScore(result.objectiveValue)} ` +
      `for this exact instance — one experiment, no general speedup implied.`,
  )

  if (valid) {
    ways.push('Every configured constraint validated with no recorded violations for the decoded selection.')
  } else {
    const detail =
      result.validationSummary ||
      result.constraintViolations.map((violation) => violation.message).join('; ') ||
      'no detail recorded'
    caveats.push(
      `Constraint validation failed: ${detail}. An infeasible selection is shown for transparency only and is not operationally recommended.`,
    )
  }

  caveats.push('This page is decision support, not an autonomous command: the operator confirms any deployment.')

  return {
    headline: valid ? 'Why these locations were selected' : 'Why this result is shown but not recommended',
    reasons: ways,
    caveats,
  }
}
