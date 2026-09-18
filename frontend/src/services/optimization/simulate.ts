/**
 * Development-only simulation of the quantum optimization pipeline.
 *
 * This module is ONLY reachable through the `mock` adapter behind the
 * `VITE_USE_MOCK_DATA` flag (see `services/optimization/adapter.ts`). It is a
 * transparent stand-in for the real quantum service so the dashboard can be
 * exercised without a live executor: it builds a real QUBO from the weighted
 * objective, maps it to a cost Hamiltonian, samples a QAOA-style outcome, and
 * — critically — runs constraint validation so invalid solutions are surfaced
 * exactly as production would surface them.
 *
 * All randomness is seeded and deterministic per (forecast, candidate count).
 */

import type {
  CandidateLocation,
  CoverageRequirement,
  ObjectiveKey,
  OptimizeRequest,
  QuboDocument,
  ResourceConstraints,
} from '../../types/optimization'
import { normalizeWeights } from '../../lib/quantum'

/** Deterministic PRNG (mulberry32). */
export type Rng = () => number

export function mulberry32(seed: number): Rng {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Stable integer hash so identical inputs always reproduce identical results. */
export function hashString(value: string): number {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const ZONES = ['Delta North', 'Delta South', 'Estuary West', 'Estuary East', 'Urban Belt', 'Reservoir Ridge']

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/**
 * Generates `count` plausible candidate sites. Scores follow a few latent
 * clusters so "hot spots" genuinely concentrate risk and population.
 */
export function generateCandidates(count: number, forecastReference: string): CandidateLocation[] {
  const rng = mulberry32(hashString(forecastReference) ^ Math.imul(count, 2654435761))
  const hotspots = Array.from({ length: Math.max(1, Math.round(count / 5)) }, () => Math.floor(rng() * count))
  return Array.from({ length: count }, (_, i) => {
    const cluster = i % ZONES.length
    const nearHot = hotspots.some((h) => Math.abs(h - i) <= 1)
    const heat = clamp01(0.28 + (nearHot ? 0.5 : 0) + rng() * 0.22)
    const population = clamp01((cluster === 4 ? 0.7 : 0.3) + (nearHot ? 0.35 : 0) + rng() * 0.15)
    const infra = clamp01((cluster === 5 ? 0.65 : 0.35) + (nearHot ? 0.25 : 0) + rng() * 0.2)
    const comm = clamp01(0.5 + (cluster === 4 ? 0.2 : 0) + (rng() - 0.5) * 0.3)
    return {
      id: `SIT-${String(i + 1).padStart(3, '0')}`,
      name: `Sensor ${String(i + 1).padStart(3, '0')}`,
      zone: ZONES[cluster],
      latitude: 8.9 + rng() * 0.5,
      longitude: -79.8 + rng() * 0.4,
      floodRisk: heat,
      populationExposure: population,
      infrastructureCriticality: infra,
      communicationScore: comm,
      sensorCostK: Math.round(22 + rng() * 46),
      coverageRadiusKm: Math.round(8 + rng() * 14),
    }
  })
}

export function baseConstraints(count: number): ResourceConstraints {
  return {
    maxSensors: Math.max(3, Math.round(count / 4)),
    budgetK: null,
    coverageRequirements: [],
    notes: [
      'Minimum inter-sensor separation 120 m',
      'Telemetry backhaul to command center required',
      'Hardware access windows CET 06:00–20:00',
    ],
  }
}

/** Weighted utility per site behind the objective (dominates the diagonal). */
export function siteUtility(site: CandidateLocation, weights: Record<ObjectiveKey, number>): number {
  const costScore = Math.max(0, 1 - site.sensorCostK / 120)
  return (
    weights.risk * site.floodRisk +
    weights.populationCoverage * site.populationExposure +
    weights.infrastructureCoverage * site.infrastructureCriticality +
    weights.communication * site.communicationScore +
    weights.cost * costScore
  )
}

/** Overlap reward for redundancy (Gaussian on distance, driven by coverage). */
export function siteOverlap(a: CandidateLocation, b: CandidateLocation): number {
  const dLat = a.latitude - b.latitude
  const dLon = a.longitude - b.longitude
  const dist = Math.hypot(dLat, dLon)
  const sigma = ((a.coverageRadiusKm + b.coverageRadiusKm) / 2) * 0.6 * (1 / 111)
  return Math.exp(-(dist * dist) / (2 * sigma * sigma))
}

export interface QuboBuild {
  doc: QuboDocument
  linear: number[]
  quadratic: number[][]
  penaltyScale: number
}

/**
 * Classic penalty QUBO: maximize weighted utility, add redundancy bonuses,
 * and penalize deviation from the cardinality + cost limits with dominated
 * penalty terms (P ≫ utility magnitudes).
 */
export function buildQubo(request: OptimizeRequest, inputs: { candidates: CandidateLocation[] }): QuboBuild {
  const siteIds = inputs.candidates.length
  const candidates = inputs.candidates
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights

  const linear: number[] = candidates.map((site) => -siteUtility(site, weights))
  const quadratic: number[][] = Array.from({ length: siteIds }, () => Array(siteIds).fill(0))
  for (let i = 0; i < siteIds; i++) {
    for (let j = i + 1; j < siteIds; j++) {
      const overlap = siteOverlap(candidates[i], candidates[j])
      const bonus = -weights.redundancy * overlap * 2
      quadratic[i][j] += bonus / 2
    }
  }

  const magnitude = Math.max(
    1,
    ...linear.map((v) => Math.abs(v)),
    ...quadratic.flat().map((v) => Math.abs(v)),
  )
  const penaltyScale = magnitude * 2 + 1

  for (let i = 0; i < siteIds; i++) {
    linear[i] -= 2 * request.maxSensors * penaltyScale
    quadratic[i][i] += penaltyScale
  }
  for (let i = 0; i < siteIds; i++) {
    for (let j = i + 1; j < siteIds; j++) {
      quadratic[i][j] += 2 * penaltyScale
    }
  }

  if (request.budgetK !== null) {
    const scale = penaltyScale / Math.max(1, request.budgetK)
    for (let i = 0; i < siteIds; i++) {
      linear[i] += -2 * request.budgetK * scale * candidates[i].sensorCostK
      quadratic[i][i] += scale * candidates[i].sensorCostK ** 2
    }
    for (let i = 0; i < siteIds; i++) {
      for (let j = i + 1; j < siteIds; j++) {
        quadratic[i][j] += 2 * scale * candidates[i].sensorCostK * candidates[j].sensorCostK
      }
    }
  }

  const offset = penaltyScale * request.maxSensors ** 2
  const variableNames = candidates.map((site) => site.id)
  const parts: string[] = []
  for (let i = 0; i < siteIds; i++) {
    if (Math.abs(linear[i]) > 1e-9) parts.push(`${linear[i].toFixed(3)}·${variableNames[i]}`)
  }
  for (let i = 0; i < siteIds; i++) {
    for (let j = i + 1; j < siteIds; j++) {
      const q = quadratic[i][j]
      if (Math.abs(q) > 1e-9) parts.push(`${q.toFixed(3)}·${variableNames[i]},${variableNames[j]}`)
    }
  }
  if (parts.length === 0) parts.push('0')

  const doc: QuboDocument = {
    variableCount: siteIds,
    variables: variableNames,
    expression: parts.slice(0, 12).join(' + ') + (parts.length > 12 ? ` + … (${parts.length - 12} more terms)` : ''),
    matrix: quadratic.map((row) => row.concat(linear)),
    offset: Number(offset.toFixed(3)),
  }
  return { doc, linear, quadratic, penaltyScale }
}

export interface DecodedRun {
  selected: CandidateLocation[]
  bitstring: string
}

/** Greedy, budget-aware cardinality decode — the QAOA measurement is centred on it. */
export function decodeSelection(request: OptimizeRequest, candidates: CandidateLocation[]): DecodedRun {
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
  const ranked = candidates
    .map((site) => ({ site, utility: siteUtility(site, weights) }))
    .sort((a, b) => b.utility - a.utility)
  const selected: CandidateLocation[] = []
  let spent = 0
  for (const item of ranked) {
    if (selected.length >= request.maxSensors) break
    if (request.budgetK !== null && spent + item.site.sensorCostK > request.budgetK) continue
    selected.push(item.site)
    spent += item.site.sensorCostK
  }
  const mask = new Set(selected.map((site) => site.id))
  const bitstring = candidates.map((site) => (mask.has(site.id) ? '1' : '0')).join('')
  return { selected, bitstring }
}

/** Sample measurement outcomes clustered around the decoded optimum. */
export function sampleMeasurements(bitstring: string, shots: number, layers: number, rng: Rng): string[] {
  const flips: string[] = []
  while (flips.length < Math.max(64, shots / 8)) {
    let sample = bitstring
    for (let i = 0; i < sample.length; i++) {
      const p = 0.015 + (layers > 1 ? 0.01 : 0) + rng() * 0.02
      if (rng() < p) {
        sample = sample.slice(0, i) + (sample[i] === '1' ? '0' : '1') + sample.slice(i + 1)
      }
    }
    flips.push(sample)
  }
  return flips
}

/** Union-approximation of coverage achieved by a selection. */
function coveredFraction(selected: CandidateLocation[], metric: 'population' | 'infrastructure'): number {
  let notCovered = 1
  for (const site of selected) {
    const contribution = metric === 'population' ? site.populationExposure : site.infrastructureCriticality
    notCovered *= 1 - contribution * 0.55
  }
  return 1 - notCovered
}

/** Hard feasibility gate used by the pipeline's constraint-validation stage. */
export function validateConstraints(
  selected: CandidateLocation[],
  request: OptimizeRequest,
  requirements: CoverageRequirement[],
): { violations: { code: string; message: string }[]; summary: string } {
  const violations: { code: string; message: string }[] = []
  const spent = selected.reduce((sum, site) => sum + site.sensorCostK, 0)
  if (selected.length > request.maxSensors) {
    violations.push({
      code: 'SENSOR_LIMIT_EXCEEDED',
      message: `Selected ${selected.length} sensors exceeds the limit of ${request.maxSensors}.`,
    })
  }
  if (request.budgetK !== null && spent > request.budgetK) {
    violations.push({
      code: 'BUDGET_EXCEEDED',
      message: `Estimated cost $${spent}k exceeds the $${request.budgetK}k budget.`,
    })
  }
  for (const req of requirements) {
    const got = coveredFraction(selected, req.metric)
    if (got < req.minFraction - 1e-9) {
      violations.push({
        code: `COVERAGE_${req.metric.toUpperCase()}_BELOW_MINIMUM`,
        message: `${req.origin} requires minimum ${Math.round(req.minFraction * 100)}% ${req.metric} coverage; only ${Math.round(got * 100)}% achievable.`,
      })
    }
  }
  const summary =
    violations.length === 0
      ? 'All constraints satisfied — solution is operationally valid.'
      : violations.map((v) => v.message).join(' ')
  return { violations, summary }
}