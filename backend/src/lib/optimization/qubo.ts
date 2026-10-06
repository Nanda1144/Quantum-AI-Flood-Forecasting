/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Sensor-placement QUBO construction and related math.
 *
 * This is the backend twin of `frontend/src/services/optimization/simulate.ts`:
 * the deterministic penalty QUBO over candidate sites, the weighted utility
 * objective, the objective/coverage evaluation, and the greedy decode. Keeping
 * the math identical across the frontend, the Node orchestrator and the
 * quantum FastAPI service means a result computed in one layer is always
 * comparable with the others.
 *
 * All values are already normalised floats in [0,1]; nothing here performs ML
 * or forecasting — it only consumes federated inputs and produces QUBOs.
 */

import type {
  CandidateLocation,
  CoverageRequirement,
  ObjectiveKey,
  ObjectiveWeights,
  QuboBuild,
  QuboDocument,
  RunOptimizationRequest,
} from '../../types/optimization.ts'

const OBJECTIVE_KEYS: ObjectiveKey[] = [
  'risk',
  'populationCoverage',
  'infrastructureCoverage',
  'communication',
  'cost',
  'redundancy',
]

/** Normalised weights (sum → 1) are what the executor consumes. */
export function normalizeWeights(weights: ObjectiveWeights): ObjectiveWeights {
  const total = OBJECTIVE_KEYS.reduce((sum, key) => sum + (weights[key] ?? 0), 0)
  if (!Number.isFinite(total) || total <= 0) return weights
  const out = {} as ObjectiveWeights
  for (const key of OBJECTIVE_KEYS) out[key] = (weights[key] ?? 0) / total
  return out
}

export function objectiveKeys(): ObjectiveKey[] {
  return [...OBJECTIVE_KEYS]
}

/** Weighted utility per site behind the objective (dominates the diagonal). */
export function siteUtility(site: CandidateLocation, weights: ObjectiveWeights): number {
  const costScore = Math.max(0, 1 - site.sensorCostK / 120)
  return (
    (weights.risk ?? 0) * site.floodRisk +
    (weights.populationCoverage ?? 0) * site.populationExposure +
    (weights.infrastructureCoverage ?? 0) * site.infrastructureCriticality +
    (weights.communication ?? 0) * site.communicationScore +
    (weights.cost ?? 0) * costScore
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

export interface WeightsAndFeatures {
  weights: ObjectiveWeights
  utilities: number[]
}

/**
 * Normalise objective weights per the request flag. `normalizeWeights=false`
 * keeps the operator-scaled raw weights (matching the frontend contract).
 */
export function resolveWeights(request: RunOptimizationRequest): WeightsAndFeatures {
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
  return { weights, utilities: [] }
}

/**
 * Classic penalty QUBO: maximise weighted utility, add redundancy bonuses, and
 * penalise deviation from the cardinality + budget limits with dominated
 * penalty terms (P ≫ utility magnitudes).
 */
export function buildQubo(request: RunOptimizationRequest, candidates: CandidateLocation[]): QuboBuild {
  const siteIds = candidates.length
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights

  const linear: number[] = candidates.map((site) => -siteUtility(site, weights))
  const quadratic: number[][] = Array.from({ length: siteIds }, () => Array<number>(siteIds).fill(0))
  for (let i = 0; i < siteIds; i++) {
    for (let j = i + 1; j < siteIds; j++) {
      const overlap = siteOverlap(candidates[i], candidates[j])
      const bonus = -(weights.redundancy ?? 0) * overlap * 2
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
    if (Math.abs(linear[i]) > 1e-9) parts.push(`${linear[i].toFixed(3)} B${variableNames[i]}`)
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

/** Evaluate the QUBO cost (lower is better) of a binary solution string. */
export function evaluateQubo(build: QuboBuild, bitstring: string): number {
  const n = build.doc.variableCount
  if (bitstring.length !== n) throw new Error(`bitstring length ${bitstring.length} != qubo size ${n}`)
  let energy = build.doc.offset
  for (let i = 0; i < n; i++) {
    if (bitstring[i] !== '1') continue
    energy += build.linear[i] + build.quadratic[i][i]
    for (let j = i + 1; j < n; j++) {
      if (bitstring[j] === '1') energy += build.quadratic[i][j]
    }
  }
  return energy
}

export interface GreedyDecodeResult {
  selected: CandidateLocation[]
  bitstring: string
}

/** Greedy, budget-aware cardinality decode — the QAOA measurement is centred on it. */
export function greedyDecode(request: RunOptimizationRequest, candidates: CandidateLocation[]): GreedyDecodeResult {
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

/** Union-approximation of coverage achieved by a selection. */
function coveredFraction(selected: CandidateLocation[], metric: 'population' | 'infrastructure'): number {
  let notCovered = 1
  for (const site of selected) {
    const contribution = metric === 'population' ? site.populationExposure : site.infrastructureCriticality
    notCovered *= 1 - contribution * 0.55
  }
  return 1 - notCovered
}

export interface ValidationVerdict {
  violations: { code: string; message: string }[]
  summary: string
}

/** Hard feasibility gate used by the pipeline's constraint-validation step. */
export function validateConstraints(
  selected: CandidateLocation[],
  request: RunOptimizationRequest,
  requirements: CoverageRequirement[],
): ValidationVerdict {
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

export interface ObjectiveMetrics {
  objectiveValue: number
  breakdown: { key: ObjectiveKey; label: string; value: number }[]
  populationCovered: number
  populationTotal: number
  infrastructureCovered: number
  infrastructureTotal: number
}

const OBJECTIVE_LABELS: Record<ObjectiveKey, string> = {
  risk: 'Risk',
  populationCoverage: 'Population coverage',
  infrastructureCoverage: 'Infrastructure coverage',
  communication: 'Communication',
  cost: 'Cost',
  redundancy: 'Redundancy',
}

export function objectiveLabel(key: ObjectiveKey): string {
  return OBJECTIVE_LABELS[key]
}

/** Fraction-of-total weighted utility and per-axis breakdown for a selection. */
export function computeObjective(
  request: RunOptimizationRequest,
  candidates: CandidateLocation[],
  selected: CandidateLocation[],
): ObjectiveMetrics {
  const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
  const totalPopulation = candidates.reduce((sum, c) => sum + c.populationExposure, 0)
  const totalInfra = candidates.reduce((sum, c) => sum + c.infrastructureCriticality, 0)
  const populationCovered = selected.reduce((sum, c) => sum + c.populationExposure, 0)
  const infrastructureCovered = selected.reduce((sum, c) => sum + c.infrastructureCriticality, 0)
  const allUtility = candidates.reduce((sum, c) => sum + siteUtility(c, weights), 0)
  const pickUtility = selected.reduce((sum, c) => sum + siteUtility(c, weights), 0)
  const objectiveValue = allUtility > 0 ? pickUtility / allUtility : 0

  const breakdown = OBJECTIVE_KEYS.filter((key) => (weights[key] ?? 0) > 0).map((key) => {
    const metricValue = (c: CandidateLocation): number =>
      key === 'risk'
        ? c.floodRisk
        : key === 'populationCoverage'
          ? c.populationExposure
          : key === 'infrastructureCoverage'
            ? c.infrastructureCriticality
            : key === 'communication'
              ? c.communicationScore
              : key === 'cost'
                ? Math.max(0, 1 - c.sensorCostK / 120)
                : c.floodRisk
    const total = candidates.reduce((sum, c) => sum + ((weights[key] ?? 0) > 0 ? metricValue(c) : 0), 0)
    const picked = selected.reduce((sum, c) => sum + ((weights[key] ?? 0) > 0 ? metricValue(c) : 0), 0)
    return { key, label: OBJECTIVE_LABELS[key], value: total > 0 ? picked / total : 0 }
  })

  return {
    objectiveValue,
    breakdown,
    populationCovered,
    populationTotal: totalPopulation,
    infrastructureCovered,
    infrastructureTotal: totalInfra,
  }
}