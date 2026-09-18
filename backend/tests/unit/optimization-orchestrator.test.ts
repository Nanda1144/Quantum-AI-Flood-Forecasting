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
})