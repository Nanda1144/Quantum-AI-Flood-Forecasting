/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the sensor-placement QUBO math directly: symmetric
 * construction, dominated penalty terms (an infeasible bitstring must never
 * out-rank a feasible one), budget/cardinality-aware greedy decode, the hard
 * feasibility gate, and the objective metric. No test claims a quantum speedup.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  buildQubo,
  computeObjective,
  evaluateQubo,
  greedyDecode,
  normalizeWeights,
  objectiveKeys,
  siteUtility,
  validateConstraints,
} from '../../src/lib/optimization/qubo.ts'
import { candidateSet, makeRunRequest } from '../helpers/optimization-sources.ts'

const candidates = candidateSet(6)

describe('buildQubo', () => {
  it('encodes a triangular Q-matrix with the documented variable count', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const build = buildQubo(request, candidates)

    assert.equal(build.doc.variableCount, 6)
    assert.equal(build.doc.variables.length, 6)
    // The coupling for pair (i, j) is stored once on the upper triangle; the
    // doc matrix rows carry the quadratic columns plus the linear terms.
    for (let j = 0; j < 6; j++) {
      assert.equal(build.doc.matrix.length, 6)
      assert.equal(build.doc.matrix[j].length, 12)
      for (let i = 0; i < 6; i++) {
        if (i > j) assert.equal(build.quadratic[i][j], 0, `lower triangle quadratic[${i}][${j}] must stay zero`)
      }
    }
    assert.equal(build.doc.offset, Number((build.penaltyScale * 3 ** 2).toFixed(3)))
  })

  it('penalty terms dominate utility magnitudes so infeasible solutions cost more', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const build = buildQubo(request, candidates)

    const greedy = greedyDecode(request, candidates)
    const allOnes = '1'.repeat(6)
    const allZero = '0'.repeat(6)

    // Penalty dominating ⇒ the feasible greedy decode costs less than the
    // infeasible "select everything" solution and less than the empty one.
    assert.ok(evaluateQubo(build, greedy.bitstring) < evaluateQubo(build, allOnes))
    assert.ok(evaluateQubo(build, greedy.bitstring) < evaluateQubo(build, allZero))
  })
})

describe('greedyDecode', () => {
  it('never exceeds the sensor cap', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const { selected } = greedyDecode(request, candidates)
    assert.ok(selected.length <= 3)
  })

  it('stays within an explicit budget when one exists', () => {
    const request = makeRunRequest({ candidateCount: 8, maxSensors: 3, budgetK: 120 })
    const moreCandidates = candidateSet(8)
    const { selected } = greedyDecode(request, moreCandidates)
    const spent = selected.reduce((sum, site) => sum + site.sensorCostK, 0)
    assert.ok(spent <= 120, `expected spend ${spent} <= 120`)
  })
})

describe('validateConstraints', () => {
  it('flags a selection larger than maxSensors', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 2, budgetK: null })
    const verdict = validateConstraints(candidates.slice(0, 4), request, [])
    assert.ok(verdict.violations.some((v) => v.code === 'SENSOR_LIMIT_EXCEEDED'))
  })

  it('flags spend beyond the budget', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 2, budgetK: 1 })
    const verdict = validateConstraints(candidates.slice(0, 2), request, [])
    assert.ok(verdict.violations.some((v) => v.code === 'BUDGET_EXCEEDED'))
  })

  it('flags unmet coverage floors', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 1, budgetK: null })
    const verdict = validateConstraints(candidates.slice(0, 1), request, [
      { metric: 'population', minFraction: 0.99, origin: 'operator' },
    ])
    assert.ok(verdict.violations.some((v) => v.code === 'COVERAGE_POPULATION_BELOW_MINIMUM'))
  })

  it('passes a feasible selection', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const greedy = greedyDecode(request, candidates)
    const verdict = validateConstraints(greedy.selected, request, [])
    assert.deepEqual(verdict.violations, [])
  })
})

describe('computeObjective', () => {
  it('is a fraction of total weighted utility within [0, 1]', () => {
    const request = makeRunRequest({
      candidateCount: 6,
      maxSensors: 3,
      budgetK: null,
      weights: { risk: 1, populationCoverage: 1, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 },
    })
    const metrics = computeObjective(request, candidates, candidates.slice(0, 2))
    assert.ok(metrics.objectiveValue >= 0 && metrics.objectiveValue <= 1)
    assert.ok(metrics.populationTotal > 0)
    assert.ok(metrics.populationCovered >= 0)
  })

  it('never rates an empty selection above a useful one', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const empty = computeObjective(request, candidates, [])
    const greedy = greedyDecode(request, candidates)
    const useful = computeObjective(request, candidates, greedy.selected)
    assert.ok(useful.objectiveValue >= empty.objectiveValue)
  })
})

describe('qubo primitives', () => {
  it('normalizeWeights maps the six objective keys onto a unit sum', () => {
    const weights = { risk: 1, populationCoverage: 2, infrastructureCoverage: 2, communication: 0, cost: 0, redundancy: 0 }
    const normalized = normalizeWeights(weights)
    const total = Object.values(normalized).reduce((sum, value) => sum + value, 0)
    assert.ok(Math.abs(total - 1) < 1e-9)
  })

  it('objectiveKeys exposes exactly the six declared axes', () => {
    assert.deepEqual(objectiveKeys(), [
      'risk',
      'populationCoverage',
      'infrastructureCoverage',
      'communication',
      'cost',
      'redundancy',
    ])
  })

  it('siteUtility stays non-negative for valid sites', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const weights = request.normalizeWeights ? normalizeWeights(request.weights) : request.weights
    for (const site of candidates) {
      assert.ok(siteUtility(site, weights) >= 0)
    }
  })
})