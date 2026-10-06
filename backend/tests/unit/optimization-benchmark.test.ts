/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Benchmark API tests (migration-free).
 *
 * Covers the seven required scenarios against the real pipeline output:
 *   1. equal solution           → ratio exactly 1, exact_optimal basis
 *   2. better classical         → ratio < 1
 *   3. better QAOA              → ratio > 1 (only possible vs the greedy reference)
 *   4. constraint violation     → violations surfaced + infeasible flag
 *   5. invalid benchmark        → ratio null + OBJECTIVE_NOT_POSITIVE (no blind division)
 *   6. missing classical result → structured nulls + missing reason
 *   7. missing quantum result   → structured nulls + CLASSICAL_ONLY_RUN
 *
 * Plus the raw ratio math (equal / better-classical / better-QAOA / invalid /
 * negative / missing), and service behaviour (quantum runtime from the 006
 * persistence layer, the benchmark ledger filters, ownership scoping).
 */

import assert from 'node:assert/strict'
import { describe, it, before, afterEach } from 'node:test'
import { AppError } from '../../src/envelope.ts'
import { OptimizationJobService, type OptimizationJobServiceOptions } from '../../src/services/optimization-orchestrator.service.ts'
import { MemoryForecastRepository, MemoryOptimizationJobRepository, MemoryQuantumJobRepository } from '../../src/repositories/memory/repositories.ts'
import { ServerCandidateStore, ServerConstraintsSource } from '../../src/services/gis/candidate-store.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { makeForecast, makeRunRequest } from '../helpers/optimization-sources.ts'
import {
  OBJECTIVE_DIRECTION,
  buildBenchmarkDocument,
  computeApproximationRatio,
  type QuantumExecutionInput,
} from '../../src/lib/optimization/benchmark.ts'
import { seedFrom } from '../../src/services/deterministic.ts'
import type { OptimizationJob } from '../../src/types/optimization.ts'

const OPTIONS: OptimizationJobServiceOptions = {
  fallbackPolicy: 'retry_simulator',
  exhaustiveLimit: 18,
  executionTimeoutMs: 5000,
  quboInlineLimit: 12,
}

const EXECUTED: QuantumExecutionInput = { ran: true, runtimeMs: 4, runtimeSource: 'quantum_results.runtime_ms' }

const clone = <T>(value: T): T => structuredClone(value)

describe('benchmark: approximation ratio math (direction-aware)', () => {
  it('defines the objective direction as MAXIMISE (weighted utility)', () => {
    assert.equal(OBJECTIVE_DIRECTION, 'maximize')
  })

  it('equal solution → ratio 1.0 on the exact-optimal basis', () => {
    const ratio = computeApproximationRatio(10, 10, 'exhaustive', true)
    assert.equal(ratio.value, 1)
    assert.equal(ratio.basis, 'exact_optimal')
    assert.equal(ratio.invalidReason, null)
    assert.equal(ratio.feasible, true)
  })

  it('better classical → ratio below 1', () => {
    const ratio = computeApproximationRatio(2.5, 2, 'exhaustive', true)
    assert.equal(ratio.value, 0.8)
    assert.equal(ratio.basis, 'exact_optimal')
  })

  it('better QAOA → ratio above 1 only against the greedy reference', () => {
    const ratio = computeApproximationRatio(2, 3, 'greedy', true)
    assert.equal(ratio.value, 1.5)
    assert.equal(ratio.basis, 'greedy_reference')
    assert.match(ratio.note, /heuristic|greedy/)
  })

  it('greedy reference is NEVER conflated with the exact optimum', () => {
    const ratio = computeApproximationRatio(2, 3, 'greedy', true)
    assert.notEqual(ratio.basis, 'exact_optimal')
  })

  it('non-positive reference → invalid, no blind division', () => {
    for (const value of [0, -1]) {
      const ratio = computeApproximationRatio(value, 3, 'exhaustive', true)
      assert.equal(ratio.value, null)
      assert.equal(ratio.invalidReason, 'OBJECTIVE_NOT_POSITIVE')
      assert.match(ratio.note, /non-positive|≤ 0/)
    }
  })

  it('negative quantum objective → invalid (sign-flipped quotient is meaningless)', () => {
    const ratio = computeApproximationRatio(10, -2, 'exhaustive', true)
    assert.equal(ratio.value, null)
    assert.equal(ratio.invalidReason, 'QUANTUM_OBJECTIVE_NEGATIVE')
  })

  it('missing either side → invalid with a structured reason', () => {
    assert.equal(computeApproximationRatio(null, 3, 'exhaustive', true).invalidReason, 'MISSING_CLASSICAL_REFERENCE')
    assert.equal(computeApproximationRatio(3, null, 'exhaustive', true).invalidReason, 'MISSING_QUANTUM_OBJECTIVE')
  })

  it('infeasible quantum solution keeps the raw ratio but flags feasible=false', () => {
    const ratio = computeApproximationRatio(10, 9, 'exhaustive', false)
    assert.equal(ratio.value, 0.9)
    assert.equal(ratio.feasible, false)
    assert.match(ratio.note, /INFEASIBLE/)
  })
})

describe('benchmark document (the seven required scenarios)', () => {
  let forecastRepo: MemoryForecastRepository
  let jobRepo: MemoryOptimizationJobRepository
  let quantumRepo: MemoryQuantumJobRepository
  let quantum: FakeQuantumServiceClient

  const service = (options: Partial<OptimizationJobServiceOptions> = {}) =>
    new OptimizationJobService(
      jobRepo,
      forecastRepo,
      new ServerCandidateStore(),
      new ServerConstraintsSource(),
      quantum,
      { ...OPTIONS, quantumJobRepo: quantumRepo, ...options },
    )

  before(() => {
    forecastRepo = new MemoryForecastRepository()
    jobRepo = new MemoryOptimizationJobRepository()
    quantumRepo = new MemoryQuantumJobRepository()
    quantum = new FakeQuantumServiceClient()
  })

  afterEach(() => {
    quantum.quboError = null
    quantum.optimizeErrorFor = () => null
    quantum.resultErrorFor = () => null
    quantum.resultOverrides = {}
    quantum.jobIdFromOptimize = true
    quantum.resetQuantumPersistence()
    quantumRepo.deleteAll()
    jobRepo.deleteAll()
    forecastRepo.deleteAll()
  })

  const run = async (body: ReturnType<typeof makeRunRequest>, svc = service()): Promise<OptimizationJob> => {
    await forecastRepo.save(makeForecast())
    const job = await svc.createJob(body, 'operator')
    return svc.waitForTerminal(job.id)
  }

  const docFor = (job: OptimizationJob, execution: QuantumExecutionInput = EXECUTED) =>
    buildBenchmarkDocument(job, { quantumExecution: execution })

  it('1. equal solution → ratio 1.0, exhaustive ground truth, seed present', async () => {
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')
    const patched = clone(job)
    patched.result!.classicalComparison.objectiveValue = 12
    patched.result!.objectiveValue = 12

    const doc = docFor(patched)
    assert.equal(doc.jobId, job.id)
    assert.equal(doc.problem.size.candidates, 6)
    assert.equal(doc.classical.solver, 'exhaustive')
    assert.equal(doc.classical.optimal, true)
    assert.equal(doc.classical.objectiveValue, 12)
    assert.equal(doc.quantum.objectiveValue, 12)
    assert.equal(doc.quantum.runtimeMs, 4)
    assert.equal(doc.quantum.runtimeSource, 'quantum_results.runtime_ms')
    assert.equal(doc.approximationRatio.value, 1)
    assert.equal(doc.approximationRatio.basis, 'exact_optimal')
    assert.equal(doc.approximationRatio.direction, 'maximize')
    assert.equal(doc.reproducibility.seed, seedFrom([job.id, job.request.forecastReference, job.request.candidateCount]))
    assert.equal(doc.reproducibility.qaoa.layers, 2)
    assert.equal(doc.reproducibility.qaoa.shots, 1024)
    assert.equal(doc.reproducibility.qaoa.backend, 'qflare_simulator_statevector')
    assert.equal(doc.reproducibility.qaoa.angles, null)
    assert.equal(doc.quantumAdvantageClaimed, false)
    assert.match(doc.disclaimer, /No quantum speedup is claimed/)
  })

  it('2. better classical → ratio below 1', async () => {
    const job = await run(makeRunRequest())
    const patched = clone(job)
    patched.result!.classicalComparison.objectiveValue = 10
    patched.result!.objectiveValue = 7.5

    const doc = docFor(patched)
    assert.equal(doc.approximationRatio.value, 0.75)
    assert.equal(doc.approximationRatio.basis, 'exact_optimal')
    assert.equal(doc.approximationRatio.invalidReason, null)
  })

  it('3. better QAOA → ratio above 1 against the greedy reference', async () => {
    const job = await run(makeRunRequest())
    const patched = clone(job)
    patched.result!.classicalComparison.method = 'greedy'
    patched.result!.classicalComparison.objectiveValue = 2
    patched.result!.objectiveValue = 3

    const doc = docFor(patched)
    assert.equal(doc.classical.optimal, false)
    assert.equal(doc.approximationRatio.value, 1.5)
    assert.equal(doc.approximationRatio.basis, 'greedy_reference')
    assert.match(doc.approximationRatio.note, /not a claim of optimality/i)
  })

  it('4. constraint violation → violations surfaced, ratio flagged infeasible', async () => {
    const job = await run(makeRunRequest())
    const patched = clone(job)
    patched.result!.classicalComparison.objectiveValue = 10
    patched.result!.objectiveValue = 9
    patched.result!.constraintViolations = [
      { code: 'SENSOR_LIMIT_EXCEEDED', message: 'selected more than the allowed sensor limit' },
    ]
    patched.result!.validationStatus = 'invalid'
    patched.result!.validationSummary = 'Sensor limit exceeded'
    patched.validationStatus = 'invalid'
    patched.validationSummary = 'Sensor limit exceeded'

    const doc = docFor(patched)
    assert.equal(doc.constraintViolations.length, 1)
    assert.equal(doc.constraintViolations[0].code, 'SENSOR_LIMIT_EXCEEDED')
    assert.equal(doc.validation.status, 'invalid')
    assert.equal(doc.validation.summary, 'Sensor limit exceeded')
    assert.equal(doc.approximationRatio.value, 0.9)
    assert.equal(doc.approximationRatio.feasible, false)
  })

  it('5. invalid benchmark → ratio null instead of a blind division', async () => {
    const job = await run(makeRunRequest())
    const patched = clone(job)
    patched.result!.classicalComparison.objectiveValue = 0
    patched.result!.objectiveValue = 9

    const doc = docFor(patched)
    assert.equal(doc.approximationRatio.value, null)
    assert.equal(doc.approximationRatio.invalidReason, 'OBJECTIVE_NOT_POSITIVE')
    assert.match(doc.approximationRatio.note, /mathematically meaningless/)
  })

  it('6. missing classical result → structured nulls + missing reason', async () => {
    const job = await run(makeRunRequest())
    const patched = clone(job)
    delete (patched.result as unknown as Record<string, unknown>).classicalComparison

    const doc = docFor(patched)
    assert.equal(doc.classical.objectiveValue, null)
    assert.equal(doc.classical.missingReason, 'MISSING_CLASSICAL_COMPARISON')
    assert.equal(doc.approximationRatio.value, null)
    assert.equal(doc.approximationRatio.invalidReason, 'MISSING_CLASSICAL_REFERENCE')
  })

  it('7. missing quantum result (classical-only fallback) → structured nulls', async () => {
    quantum.failMode('ibm_hardware')
    const job = await run(
      makeRunRequest({ executionMode: 'hardware', hardwareEnabled: true, backend: 'ibm_kyiv' }),
      service({ fallbackPolicy: 'classical_only' }),
    )
    assert.equal(job.status, 'completed')
    assert.equal(job.fallbackApplied, true)
    assert.equal(job.result!.measurementCounts.length, 0)

    const doc = docFor(job, { ran: false, runtimeMs: null, runtimeSource: null })
    assert.equal(doc.quantum.objectiveValue, null)
    assert.equal(doc.quantum.missingReason, 'CLASSICAL_ONLY_RUN')
    assert.equal(doc.quantum.executionMode, 'classical')
    assert.equal(doc.quantum.runtimeMs, null)
    assert.equal(doc.approximationRatio.value, null)
    assert.equal(doc.approximationRatio.invalidReason, 'MISSING_QUANTUM_OBJECTIVE')
    assert.ok(doc.classical.objectiveValue !== null, 'the classical reference still runs for a classical-only job')
  })

  it('reads the executor runtime from the 006 persistence layer (quantum_results.runtime_ms)', async () => {
    const job = await run(makeRunRequest())
    const doc = await service().getBenchmarkForPrincipal(job.id, { username: 'operator', role: 'operator' })
    assert.equal(doc.quantum.runtimeMs, 4)
    assert.equal(doc.quantum.runtimeSource, 'quantum_results.runtime_ms')
    assert.equal(doc.quantum.algorithm, 'qaoa')
  })

  it('persists the migration 007 benchmark reference snapshot on the result record', async () => {
    const job = await run(makeRunRequest())
    const record = await jobRepo.findResult(job.id)
    assert.ok(record, 'a completed job always yields a normalized result row')
    assert.equal(record.classicalSolver, 'exhaustive')
    assert.equal(record.classicalRuntimeMs, job.result!.classicalComparison.executionTimeMs)
    assert.equal(record.classicalObjective, job.result!.classicalComparison.objectiveValue)
    assert.equal(record.approximationRatio, 1)
    assert.equal(record.approximationBasis, 'exact_optimal')
    assert.equal(record.approximationInvalidReason, null)
    assert.equal(record.randomSeed, seedFrom([job.id, job.request.forecastReference, job.request.candidateCount]))
  })

  it('the benchmark snapshot is write-once — a second save never overwrites history', async () => {
    const job = await run(makeRunRequest())
    const original = await jobRepo.findResult(job.id)
    assert.ok(original)
    const tampered = clone(original)
    tampered.approximationRatio = 99
    tampered.approximationBasis = 'greedy_reference'
    tampered.classicalSolver = 'greedy'
    tampered.randomSeed = 12345
    await jobRepo.saveResult(tampered)

    const again = await jobRepo.findResult(job.id)
    assert.ok(again)
    assert.equal(again.approximationRatio, 1, 'stored ratio is preserved')
    assert.equal(again.approximationBasis, 'exact_optimal', 'stored basis is preserved')
    assert.equal(again.classicalSolver, 'exhaustive', 'stored solver is preserved')
    assert.equal(again.randomSeed, seedFrom([job.id, job.request.forecastReference, job.request.candidateCount]), 'stored seed is preserved')

    // The document built over the row also refuses to restate a tampered value.
    const doc = await service().getBenchmarkForPrincipal(job.id, { username: 'operator', role: 'operator' })
    assert.equal(doc.approximationRatio.value, 1)
    assert.equal(doc.reproducibility.seed, seedFrom([job.id, job.request.forecastReference, job.request.candidateCount]))
  })

  it('a null ratio persists the invalid-reason code (honest absence)', async () => {
    quantum.failMode('ibm_hardware')
    const job = await run(
      makeRunRequest({ executionMode: 'hardware', hardwareEnabled: true, backend: 'ibm_kyiv' }),
      service({ fallbackPolicy: 'classical_only' }),
    )
    assert.equal(job.status, 'completed')
    const record = await jobRepo.findResult(job.id)
    assert.ok(record)
    assert.equal(record.approximationRatio, null)
    assert.equal(record.approximationInvalidReason, 'MISSING_QUANTUM_OBJECTIVE')
    assert.equal(record.classicalSolver, 'exhaustive')
    assert.ok(record.classicalRuntimeMs !== null)

    const doc = await service().getBenchmarkForPrincipal(job.id, { username: 'operator', role: 'operator' })
    assert.equal(doc.approximationRatio.value, null)
    assert.equal(doc.approximationRatio.invalidReason, 'MISSING_QUANTUM_OBJECTIVE')
  })

  it('getBenchmarkForPrincipal → 404 when the job never produced a result', async () => {
    quantum.failMode('simulator')
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')
    await assert.rejects(
      service().getBenchmarkForPrincipal(job.id, { username: 'operator', role: 'operator' }),
      (error: unknown) => error instanceof AppError && error.code === 'RESULT_NOT_FOUND',
    )
  })

  it('getBenchmarkForPrincipal hides foreign jobs and deleted jobs', async () => {
    const job = await run(makeRunRequest())
    const svc = service()
    await assert.rejects(
      svc.getBenchmarkForPrincipal(job.id, { username: 'viewer', role: 'viewer' }),
      (error: unknown) => error instanceof AppError && error.code === 'JOB_NOT_FOUND',
    )
    const deleted = await jobRepo.deleteJob(job.id, 'admin', 'test cleanup')
    assert.ok(deleted.deletedAt)
    await assert.rejects(
      svc.getBenchmarkForPrincipal(job.id, { username: 'admin', role: 'admin' }),
      (error: unknown) => error instanceof AppError && error.code === 'JOB_NOT_FOUND',
    )
  })
})

describe('GET /api/optimization/benchmarks (filterable ledger)', () => {
  let forecastRepo: MemoryForecastRepository
  let jobRepo: MemoryOptimizationJobRepository
  let quantumRepo: MemoryQuantumJobRepository
  let quantum: FakeQuantumServiceClient

  const service = (options: Partial<OptimizationJobServiceOptions> = {}) =>
    new OptimizationJobService(
      jobRepo,
      forecastRepo,
      new ServerCandidateStore(),
      new ServerConstraintsSource(),
      quantum,
      { ...OPTIONS, quantumJobRepo: quantumRepo, ...options },
    )

  before(() => {
    forecastRepo = new MemoryForecastRepository()
    jobRepo = new MemoryOptimizationJobRepository()
    quantumRepo = new MemoryQuantumJobRepository()
    quantum = new FakeQuantumServiceClient()
  })

  afterEach(() => {
    quantum.resetQuantumPersistence()
    quantum.optimizeErrorFor = () => null
    quantum.resultErrorFor = () => null
    quantumRepo.deleteAll()
    jobRepo.deleteAll()
    forecastRepo.deleteAll()
  })

  const runOne = async (body: ReturnType<typeof makeRunRequest>): Promise<OptimizationJob> => {
    await forecastRepo.save(makeForecast())
    const job = await service().createJob(body, 'operator')
    return service().waitForTerminal(job.id)
  }

  it('lists only completed jobs with a stored result, newest first', async () => {
    const first = await runOne(makeRunRequest())
    const second = await runOne(makeRunRequest())
    assert.equal(first.status, 'completed')

    const rows = await service().listBenchmarksForPrincipal({}, { username: 'operator', role: 'operator' })
    assert.equal(rows.length, 2)
    assert.equal(rows[0].jobId, second.id)
    assert.equal(rows[1].jobId, first.id)
    assert.equal(rows[0].algorithm, 'qaoa')
    assert.equal(rows[0].classical.optimal, true)
    assert.ok(typeof rows[0].approximationRatio.value === 'number')
  })

  it('filters by problem type, algorithm and execution mode (requested or used)', async () => {
    await runOne(makeRunRequest())
    const rows = await service().listBenchmarksForPrincipal(
      {
        problemType: 'sensor_placement',
        algorithm: 'qaoa',
        executionMode: 'simulator',
      },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(rows.length, 1)

    const none = await service().listBenchmarksForPrincipal(
      { problemType: 'resource_allocation' },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(none.length, 0)

    const wrongMode = await service().listBenchmarksForPrincipal(
      { executionMode: 'ibm_hardware' },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(wrongMode.length, 0)
  })

  it('filters by experiment date range (lower bound or upper bound)', async () => {
    await runOne(makeRunRequest())
    const rows = await service().listBenchmarksForPrincipal({}, { username: 'operator', role: 'operator' })
    assert.equal(rows.length, 1)
    const createdAt = rows[0].createdAt

    const before = await service().listBenchmarksForPrincipal(
      { from: new Date(Date.parse(createdAt) + 10_000).toISOString() },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(before.length, 0)

    const after = await service().listBenchmarksForPrincipal(
      { to: new Date(Date.parse(createdAt) - 10_000).toISOString() },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(after.length, 0)

    const covering = await service().listBenchmarksForPrincipal(
      { from: createdAt, to: createdAt },
      { username: 'operator', role: 'operator' },
    )
    assert.equal(covering.length, 1)
  })

  it('scopes the ledger to the owner (admin sees all)', async () => {
    await runOne(makeRunRequest())
    const viewerRows = await service().listBenchmarksForPrincipal({}, { username: 'viewer', role: 'viewer' })
    assert.equal(viewerRows.length, 0)
    const adminRows = await service().listBenchmarksForPrincipal({}, { username: 'admin', role: 'admin' })
    assert.equal(adminRows.length, 1)
  })
})