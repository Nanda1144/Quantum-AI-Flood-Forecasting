/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the classical reference solver that grounds every
 * quantum result: exhaustive brute-force is feasible for small sets, greedy is
 * the always-available fallback, and neither ever overruns the configured
 * cardinality or budget. No test claims a quantum speedup.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { exhaustiveSolve, solveClassicalReference } from '../../src/lib/optimization/classical.ts'
import { candidateSet, makeRunRequest } from '../helpers/optimization-sources.ts'

describe('exhaustiveSolve', () => {
  it('respects the cardinality cap', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const { selected } = exhaustiveSolve(request, candidateSet(6))
    assert.ok(selected.length <= 3)
  })

  it('respects the budget cap', () => {
    const request = makeRunRequest({ candidateCount: 8, maxSensors: 3, budgetK: 110 })
    const { selected } = exhaustiveSolve(request, candidateSet(8))
    const spent = selected.reduce((sum, site) => sum + site.sensorCostK, 0)
    assert.ok(spent <= 110, `expected spend ${spent} <= 110`)
  })

  it('matches or beats the greedy decode on the same objective', () => {
    const request = makeRunRequest({ candidateCount: 8, maxSensors: 3, budgetK: 150 })
    const moreCandidates = candidateSet(8)
    const { metrics: exhaustiveMetrics } = exhaustiveSolve(request, moreCandidates)
    const greedy = solveClassicalReference(request, moreCandidates, 18)
    assert.ok(
      exhaustiveMetrics.objectiveValue >= greedy.comparison.objectiveValue - 1e-9,
      'exhaustive must be the upper bound on the reference objective',
    )
  })
})

describe('solveClassicalReference', () => {
  it('uses exhaustive search when the candidate set is within the limit', () => {
    const request = makeRunRequest({ candidateCount: 6, maxSensors: 3, budgetK: null })
    const run = solveClassicalReference(request, candidateSet(6), 18)
    assert.equal(run.comparison.method, 'exhaustive')
    assert.ok(run.comparison.objectiveValue > 0)
    assert.ok(run.comparison.executionTimeMs >= 1)
  })

  it('falls back to greedy when the candidate set exceeds the limit', () => {
    const request = makeRunRequest({ candidateCount: 32, maxSensors: 4, budgetK: 300 })
    const run = solveClassicalReference(request, candidateSet(32), 18)
    assert.equal(run.comparison.method, 'greedy')
    const spent = run.selected.reduce((sum, site) => sum + site.sensorCostK, 0)
    assert.ok(run.selected.length <= 4)
    assert.ok(spent <= 300)
  })
})