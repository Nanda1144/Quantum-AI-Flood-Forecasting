/**
 * Classical reference solver for the sensor-placement problem.
 *
 * Always runs before/alongside QAOA and is always persisted with the result —
 * the orchestrator never claims a quantum speedup, so the classical benchmark
 * is the ground truth every execution is compared against.
 *
 * Method:
 *   - `greedy`     — sort sites by weighted utility, take the best while
 *                    respecting cardinality + budget (fast, always available).
 *   - `exhaustive` — when the candidate set is small enough
 *                    (`OPTIMIZATION_EXHAUSTIVE_LIMIT`), brute-force all viable
 *                    subsets to find the true optimum of the same objective,
 *                    so the benchmark is a fair reference.
 */

import { computeObjective, greedyDecode, type ObjectiveMetrics } from './qubo.ts'
import type {
  CandidateLocation,
  ClassicalComparison,
  RunOptimizationRequest,
} from '../../types/optimization.ts'

export interface ClassicalRun {
  comparison: ClassicalComparison
  selected: CandidateLocation[]
  bitstring: string
  metrics: ObjectiveMetrics
}

/**
 * Solve the reference problem and time it. `exhaustiveLimit` bounds the
 * brute-force search; larger candidate sets fall back to greedy.
 */
export function solveClassicalReference(
  request: RunOptimizationRequest,
  candidates: CandidateLocation[],
  exhaustiveLimit: number,
): ClassicalRun {
  const started = performance.now()
  const exhaustive = candidates.length <= exhaustiveLimit && candidates.length <= 24

  if (exhaustive) {
    const best = exhaustiveSolve(request, candidates)
    return finalize(request, candidates, best.selected, 'exhaustive', started)
  }

  const greedy = greedyDecode(request, candidates)
  return finalize(request, candidates, greedy.selected, 'greedy', started)
}

function finalize(
  request: RunOptimizationRequest,
  candidates: CandidateLocation[],
  selected: CandidateLocation[],
  method: string,
  started: number,
): ClassicalRun {
  const metrics = computeObjective(request, candidates, selected)
  const executionTimeMs = Math.max(1, Math.round(performance.now() - started))
  const mask = new Set(selected.map((site) => site.id))
  const bitstring = candidates.map((site) => (mask.has(site.id) ? '1' : '0')).join('')
  return {
    comparison: {
      method,
      objectiveValue: Number(metrics.objectiveValue.toFixed(4)),
      selectedCount: selected.length,
      executionTimeMs,
      gapVsQuantum: 0,
    },
    selected,
    bitstring,
    metrics,
  }
}

/**
 * Brute-force the cardinality- and budget-constrained selection that maximises
 * the same weighted-utility objective the QUBO encodes. Exponential, so the
 * caller caps the candidate set (`exhaustiveLimit`, ≤ 24).
 */
export function exhaustiveSolve(
  request: RunOptimizationRequest,
  candidates: CandidateLocation[],
): { selected: CandidateLocation[]; metrics: ObjectiveMetrics } {
  const n = candidates.length
  const maxSensor = Math.min(request.maxSensors, n)
  let bestSelected: CandidateLocation[] = []
  let bestMetrics: ObjectiveMetrics | null = null

  const visit = (start: number, selected: CandidateLocation[]) => {
    const spent = selected.reduce((sum, site) => sum + site.sensorCostK, 0)
    if (request.budgetK !== null && spent > request.budgetK) return
    const metrics = computeObjective(request, candidates, selected)
    if (!bestMetrics || metrics.objectiveValue > bestMetrics.objectiveValue + 1e-12) {
      bestMetrics = metrics
      bestSelected = selected
    }
    if (selected.length >= maxSensor) return
    for (let i = start; i < n; i++) {
      visit(i + 1, [...selected, candidates[i]])
    }
  }
  visit(0, [])

  if (!bestMetrics) bestMetrics = computeObjective(request, candidates, [])
  return { selected: bestSelected, metrics: bestMetrics }
}