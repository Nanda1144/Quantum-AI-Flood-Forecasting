/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * OptimizationJobService orchestration tests — the 10 documented scenarios.
 *
 *   1  valid optimization
 *   2  invalid objective weights
 *   3  infeasible budget
 *   4  no candidates
 *   5  QUBO generation failure (fallback: local QUBO / error policy)
 *   6  QAOA executor failure (classical-only / error policy)
 *   7  hardware down (retry_simulator ladder)
 *   8  invalid decoded solution
 *   9  constraint violation (invalid outcome, completed job)
 *   10 successful classical benchmark is persisted
 */

import assert from 'node:assert/strict'
import { describe, it, before, afterEach } from 'node:test'
import { QuantumServiceError } from '../../src/clients/quantum-service.client.ts'
import { OptimizationJobService } from '../../src/services/optimization-orchestrator.service.ts'
import { MemoryForecastRepository, MemoryOptimizationJobRepository } from '../../src/repositories/memory/repositories.ts'
import { ServerCandidateStore, ServerConstraintsSource } from '../../src/services/gis/candidate-store.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { EmptyCandidateStore, makeForecast, makeRunRequest } from '../helpers/optimization-sources.ts'
import type { OptimizationJobServiceOptions } from '../../src/services/optimization-orchestrator.service.ts'
import type { OptimizationJob } from '../../src/types/optimization.ts'

const OPTIONS: OptimizationJobServiceOptions = {
  fallbackPolicy: 'retry_simulator',
  exhaustiveLimit: 18,
  executionTimeoutMs: 5000,
  quboInlineLimit: 12,
}

describe('OptimizationJobService orchestration', () => {
  let forecastRepo: MemoryForecastRepository
  let jobRepo: MemoryOptimizationJobRepository
  let quantum: FakeQuantumServiceClient

  const service = (options: Partial<OptimizationJobServiceOptions> = {}) =>
    new OptimizationJobService(
      jobRepo,
      forecastRepo,
      new ServerCandidateStore(),
      new ServerConstraintsSource(),
      quantum,
      { ...OPTIONS, ...options },
    )

  before(() => {
    forecastRepo = new MemoryForecastRepository()
    jobRepo = new MemoryOptimizationJobRepository()
    quantum = new FakeQuantumServiceClient()
  })

  afterEach(() => {
    quantum.quboError = null
    quantum.optimizeErrorFor = () => null
    quantum.resultOverrides = {}
  })

  async function run(request: ReturnType<typeof makeRunRequest>, svc = service()): Promise<OptimizationJob> {
    await forecastRepo.save(makeForecast())
    const job = await svc.createJob(request, 'operator')
    return svc.waitForTerminal(job.id)
  }

  // 1 ────────────────────────────────────────────────────────────────────────
  it('1. completes a valid optimization with result + classical comparison', async () => {
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')
    assert.equal(job.validationStatus, 'valid')

    const result = job.result!
    assert.equal(result.jobId, job.id)
    assert.equal(result.quantumAdvantageClaimed, false)
    assert.equal(result.selectedLocations.length, job.request.maxSensors)
    assert.equal(result.validationStatus, 'valid')
    assert.deepEqual(result.constraintViolations, [])
    assert.equal(typeof result.objectiveValue, 'number')
    assert.ok(result.objectiveValue > 0)
    assert.equal(result.classicalComparison.method, 'exhaustive')
    assert.ok(result.classicalComparison.objectiveValue > 0)
    assert.equal(job.classical!.method, 'exhaustive')

    // Persistence-layer configuration record.
    assert.equal(typeof result.bitstring, 'string')
    assert.equal(result.bitstring.length, job.request.candidateCount)
    assert.equal(job.forecastReference, job.request.forecastReference)
    assert.equal(job.inputReference, `ai://forecasts/${job.request.forecastReference}`)
    assert.equal(job.variablesCount, job.request.candidateCount)
    assert.deepEqual(job.constraints?.coverageRequirements, [])
    assert.equal(job.constraints?.maxSensors, job.request.maxSensors)
    assert.equal(job.objectiveConfiguration?.shots, job.request.shots)
    assert.equal(job.objectiveConfiguration?.layers, job.request.layers)
    assert.equal(job.quboStorage, 'inline')
    assert.equal(job.quboArtifactReference, null)
    assert.equal(job.errorMessage, null)
    assert.equal(job.deletedAt, null)
  })

  it('persists a normalized result row for a completed job', async () => {
    const job = await run(makeRunRequest())
    const record = await jobRepo.findResult(job.id)
    assert.ok(record, 'a completed job must have a persisted result row')
    assert.equal(record!.id, `${job.id}-R1`)
    assert.equal(record!.optimizationJobId, job.id)
    assert.equal(record!.bitstring, job.result!.bitstring)
    assert.equal(record!.validationStatus, 'valid')
    assert.equal(record!.selectedLocationIds.length, job.request.maxSensors)
    assert.ok(record!.objectiveValue > 0)
    assert.equal(record!.classicalObjective, job.result!.classicalComparison.objectiveValue)
    assert.equal(record!.quantumObjective, job.result!.objectiveValue)
    assert.equal(record!.approximationQuality, 1)
  })

  it('routes QUBOs above the inline limit to the artifact store by reference', async () => {
    const job = await run(makeRunRequest({ candidateCount: 14, maxSensors: 5 }))
    assert.equal(job.status, 'completed')
    assert.equal(job.quboStorage, 'artifact')
    assert.equal(job.qubo, null, 'large QUBO must travel by reference, not inline')
    assert.match(job.quboArtifactReference!, /^qflare:\/\/qubo\//)
    assert.equal(job.result!.qubo.variableCount, 14)
  })

  it('soft-deletes through the repository with an audit trail (never a hard delete)', async () => {
    const job = await run(makeRunRequest())
    const deleted = await jobRepo.deleteJob(job.id, 'admin', 'approved cleanup')
    assert.ok(deleted.deletedAt)
    assert.equal(deleted.deletedBy, 'admin')
    assert.equal(deleted.deleteReason, 'approved cleanup')
    assert.ok(jobRepo.findById(job.id), 'the row must still exist after a soft delete')
    const audit = await jobRepo.listAudit(job.id)
    assert.equal(audit.length, 1)
    assert.equal(audit[0].action, 'soft_deleted')
    assert.equal(audit[0].actor, 'admin')
    assert.equal(audit[0].reason, 'approved cleanup')
  })

  it('records every pipeline step as done', async () => {
    const job = await run(makeRunRequest())
    const pending = job.steps.filter((step) => step.status !== 'done')
    assert.deepEqual(pending, [])
    assert.ok(job.startedAt)
    assert.ok(job.completedAt)
  })

  // 2 ────────────────────────────────────────────────────────────────────────
  it('2. rejects all-zero objective weights with INVALID_OBJECTIVE_WEIGHTS', async () => {
    const job = await run(
      makeRunRequest({
        weights: { risk: 0, populationCoverage: 0, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 },
      }),
    )
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'INVALID_OBJECTIVE_WEIGHTS')
  })

  // 3 ────────────────────────────────────────────────────────────────────────
  it('3. rejects a budget below the cheapest candidate with INFEASIBLE_BUDGET', async () => {
    // Sensor costs are drawn from [22, 68]; a $20k budget can never fund one.
    const job = await run(makeRunRequest({ budgetK: 20 }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'INFEASIBLE_BUDGET')
    assert.equal((job.error!.details as { minCandidateCostK: number }).minCandidateCostK >= 22, true)
  })

  it('rejects a falsified negative budget at the service boundary', async () => {
    const job = await run(makeRunRequest({ budgetK: -5 }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'INFEASIBLE_BUDGET')
  })

  // 4 ────────────────────────────────────────────────────────────────────────
  it('4. fails with NO_CANDIDATES when the GIS source returns none', async () => {
    await forecastRepo.save(makeForecast())
    const svc = new OptimizationJobService(
      jobRepo,
      forecastRepo,
      new EmptyCandidateStore(),
      new ServerConstraintsSource(),
      quantum,
      OPTIONS,
    )
    const job = await run(makeRunRequest(), svc)
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'NO_CANDIDATES')
  })

  it('fails with FORECAST_NOT_FOUND when the forecast reference is unknown', async () => {
    const job = await run(makeRunRequest({ forecastReference: 'FC-20991231-9999' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'FORECAST_NOT_FOUND')
  })

  it('fails with UNSUPPORTED_PROBLEM_TYPE outside the enabled envelope', async () => {
    const job = await run(makeRunRequest({ problemType: 'resource_allocation' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'UNSUPPORTED_PROBLEM_TYPE')
  })

  // 5 ────────────────────────────────────────────────────────────────────────
  it('5a. falls back to the local QUBO when the quantum service QUBO fails (retry_simulator)', async () => {
    quantum.quboError = new QuantumServiceError('QUBO_UNAVAILABLE', 503, 'qubo builder down')
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')
    assert.equal(job.fallbackApplied, true)
    assert.match(job.fallbackReason ?? '', /quantum_qubo_unavailable/)
    assert.ok(job.result!.qubo.variableCount === job.request.candidateCount)
  })

  it('5b. fails with QUBO_GENERATION_FAILED under the error policy', async () => {
    quantum.quboError = new QuantumServiceError('QUBO_UNAVAILABLE', 503, 'qubo builder down')
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'QUBO_GENERATION_FAILED')
  })

  // 6 ────────────────────────────────────────────────────────────────────────
  it('6a. fails with QAOA_EXECUTION_FAILED when the configured simulator fails under error policy', async () => {
    quantum.failMode('simulator')
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'QAOA_EXECUTION_FAILED')
  })

  it('6b. completes classical-only when hardware fails under classical_only policy', async () => {
    quantum.failMode('ibm_hardware')
    const job = await run(makeRunRequest({ executionMode: 'hardware', backend: 'ibm_brisbane' }), service({ fallbackPolicy: 'classical_only' }))
    assert.equal(job.status, 'completed')
    assert.equal(job.fallbackApplied, true)
    assert.match(job.fallbackReason ?? '', /ibm_hardware/)
    assert.equal(job.executionModeUsed, 'ibm_hardware')
    const result = job.result!
    assert.equal(result.simulated, false)
    assert.deepEqual(result.measurementCounts, [])
    assert.equal(result.classicalComparison.objectiveValue, job.classical!.objectiveValue)
    assert.equal(result.selectedLocations.length, job.request.maxSensors)
  })

  // 7 ────────────────────────────────────────────────────────────────────────
  it('7. retries on the simulator when hardware is down (retry_simulator)', async () => {
    quantum.failMode('ibm_hardware')
    const job = await run(makeRunRequest({ executionMode: 'hardware', backend: 'ibm_brisbane' }))
    assert.equal(job.status, 'completed')
    assert.equal(job.fallbackApplied, true)
    assert.match(job.fallbackReason ?? '', /ibm_hardware/)
    assert.equal(job.executionModeUsed, 'simulator')
    assert.equal(job.backendUsed, 'qflare_simulator_statevector')
    assert.equal(job.result!.simulated, true)
    assert.ok(job.result!.measurementCounts.length > 0)
  })

  it('does not fall back when a pure-simulator mode fails (returns a hard result)', async () => {
    quantum.failMode('simulator')
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'retry_simulator' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'QAOA_EXECUTION_FAILED')
    assert.equal(job.fallbackApplied, false)
  })

  // 8 ────────────────────────────────────────────────────────────────────────
  it('8. fails with DECODING_FAILED on an invalid decoded bitstring', async () => {
    quantum.resultOverrides.topBitstring = '11' // wrong length for 6 candidates
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'DECODING_FAILED')
    assert.equal((job.error!.details as { bitstring: string }).bitstring, '11')
  })

  // 9 ────────────────────────────────────────────────────────────────────────
  it('9. marks an over-selection invalid while still completing the job', async () => {
    quantum.resultOverrides.topBitstring = '111111' // exceeds maxSensors=3
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')
    assert.equal(job.validationStatus, 'invalid')
    const result = job.result!
    assert.equal(result.validationStatus, 'invalid')
    assert.ok(result.constraintViolations.some((violation) => violation.code === 'SENSOR_LIMIT_EXCEEDED'))
    assert.equal(job.classical!.method, 'exhaustive')
  })

  it('9b. an unachievable coverage floor yields exactly ONE violation (no echo duplication)', async () => {
    const job = await run(
      makeRunRequest({
        coverageRequirements: [{ metric: 'population', minFraction: 0.99, origin: 'Operator' }],
      }),
    )
    assert.equal(job.status, 'completed')
    assert.equal(job.validationStatus, 'invalid')
    const violations = job.result!.constraintViolations.filter((violation) => violation.code === 'COVERAGE_POPULATION_BELOW_MINIMUM')
    assert.equal(violations.length, 1)
    assert.match(violations[0].message, /only \d+% achievable/)
    assert.equal(job.classical!.method, 'exhaustive')
  })

  // 10 ───────────────────────────────────────────────────────────────────────
  it('10. persists a usable classical benchmark with every result', async () => {
    const job = await run(makeRunRequest({ candidateCount: 6 }))
    const result = job.result!
    assert.equal(result.classicalComparison.method, 'exhaustive')
    assert.ok(result.classicalComparison.objectiveValue > 0)
    assert.equal(typeof result.classicalComparison.executionTimeMs, 'number')
    assert.equal(typeof result.classicalComparison.gapVsQuantum, 'number')
    assert.equal(result.quantumAdvantageClaimed, false)
    assert.match(result.benchmarkDisclaimer ?? '', /No quantum speedup/)
    assert.ok(job.classical!.selectedCount >= 1)
  })

  // Ownership periphery ─────────────────────────────────────────────────────
  it('scopes job reads to the owner (404 for non-owners, admin bypasses)', async () => {
    const job = await run(makeRunRequest())
    const own = await service().getJobForPrincipal(job.id, { username: 'operator', role: 'operator' })
    assert.equal(own.id, job.id)

    await assert.rejects(
      service().getJobForPrincipal(job.id, { username: 'viewer', role: 'viewer' }),
      (error: { status?: number }) => error.status === 404,
    )

    const asAdmin = await service().getJobForPrincipal(job.id, { username: 'admin', role: 'admin' })
    assert.equal(asAdmin.id, job.id)
  })

  it('surfaces a 404 for an unknown job id', async () => {
    await assert.rejects(service().getJob('QOP-NOPE'), (error: { status?: number }) => error.status === 404)
  })

  it('summaries expose the jobId alias used by the frontend adapter', async () => {
    const job = await run(makeRunRequest())
    const summary = service().summary(job)
    assert.equal(summary.jobId, job.id)
    assert.equal(summary.id, job.id)
    assert.equal(summary.backend, job.backend)
    assert.equal(summary.qubitCount, job.result!.qubits)
    assert.ok('status' in summary)
  })

  // Experiment ledger ───────────────────────────────────────────────────────
  it('benchmark summaries carry the classical reference and quality honestly', async () => {
    const job = await run(makeRunRequest())
    const summary = service().summary(job)
    const result = job.result!
    assert.equal(summary.resultSummary.objectiveValue, result.objectiveValue)
    assert.equal(summary.resultSummary.classicalObjectiveValue, result.classicalComparison.objectiveValue)
    assert.equal(summary.resultSummary.classicalRuntimeMs, result.classicalComparison.executionTimeMs)
    assert.equal(summary.resultSummary.validated, true)
    assert.equal(summary.resultSummary.constraintViolationCount, 0)
    assert.equal(
      summary.resultSummary.approximationQuality,
      Number(Math.min(1, result.objectiveValue / result.classicalComparison.objectiveValue).toFixed(4)),
    )
    assert.ok(summary.resultSummary.approximationQuality! <= 1)
  })

  it('listSummariesForPrincipal returns the ledger newest-first and scoped to the owner', async () => {
    const earlier = await run(makeRunRequest())
    const later = await run(makeRunRequest())
    const svc = service()

    const visible = await svc.listSummariesForPrincipal({ username: 'operator', role: 'operator' })
    assert.ok(visible.length >= 2, 'the ledger must include every completed run from the suite')
    for (const entry of visible) {
      assert.equal(entry.jobId, entry.id)
      assert.ok(entry.createdAt)
      // The two just-created runs must both be present, newest first.
      if (entry.jobId === earlier.id || entry.jobId === later.id) {
        assert.equal(entry.owner, 'operator')
      }
    }
    const indexOfEarlier = visible.findIndex((entry) => entry.jobId === earlier.id)
    const indexOfLater = visible.findIndex((entry) => entry.jobId === later.id)
    assert.ok(indexOfEarlier >= 0 && indexOfLater >= 0)
    assert.ok(indexOfLater < indexOfEarlier, 'newer runs must sort ahead of older ones')

    const foreign = await svc.listSummariesForPrincipal({ username: 'someone-else', role: 'viewer' })
    assert.equal(foreign.length, 0, 'a non-owner must never see another tenant ledger')

    const all = await svc.listSummariesForPrincipal({ username: 'admin', role: 'admin' })
    assert.equal(all.length, visible.length, 'admin sees the full ledger')
  })
})