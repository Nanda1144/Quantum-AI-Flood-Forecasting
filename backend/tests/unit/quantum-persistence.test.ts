/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum job persistence lifecycle tests (migration 006).
 *
 * The orchestrator must persist one honest row per REAL quantum submission:
 *   - accepted job   → `quantum_jobs` row transitions queued → completed/failed
 *   - completed job  → exactly one `quantum_results` row (`<jobId>-R1`)
 *   - failed attempt → `failed` row with the executor error (no result row)
 *   - optimize-level failure → NO row (the platform never submitted)
 *   - persistence store failure → never breaks the optimization pipeline
 *
 * The MemoryQuantumJobRepository enforces the same FK-like + id-format rules
 * as the Postgres migration, so the guards are exercised here too.
 */

import assert from 'node:assert/strict'
import { describe, it, before, afterEach } from 'node:test'
import { OptimizationJobService } from '../../src/services/optimization-orchestrator.service.ts'
import { MemoryForecastRepository, MemoryOptimizationJobRepository, MemoryQuantumJobRepository } from '../../src/repositories/memory/repositories.ts'
import { ServerCandidateStore, ServerConstraintsSource } from '../../src/services/gis/candidate-store.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { makeForecast, makeRunRequest } from '../helpers/optimization-sources.ts'
import { AppError } from '../../src/envelope.ts'
import type { OptimizationJobServiceOptions } from '../../src/services/optimization-orchestrator.service.ts'
import type { OptimizationJob } from '../../src/types/optimization.ts'
import type { QuantumJobRecord, QuantumResultRecord } from '../../src/types/optimization.ts'
import type { QuantumJobRepository } from '../../src/repositories/repositories.ts'

const OPTIONS: OptimizationJobServiceOptions = {
  fallbackPolicy: 'retry_simulator',
  exhaustiveLimit: 18,
  executionTimeoutMs: 5000,
  quboInlineLimit: 12,
}

/** Repo wrapper that simulates a broken persistence store (best-effort check). */
class ThrowingQuantumJobRepo implements QuantumJobRepository {
  constructor(private readonly inner: QuantumJobRepository) {}
  async saveJob(): Promise<QuantumJobRecord> {
    throw new Error('store unavailable')
  }
  async findJobById(id: string) { return this.inner.findJobById(id) }
  async findJobsByOptimizationJobId(optimizationJobId: string) { return this.inner.findJobsByOptimizationJobId(optimizationJobId) }
  async saveResult(): Promise<QuantumResultRecord> {
    throw new Error('store unavailable')
  }
  async findResult(quantumJobId: string) { return this.inner.findResult(quantumJobId) }
  async deleteAll(): Promise<void> { return this.inner.deleteAll() }
}

describe('quantum job persistence (migration 006)', () => {
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
    quantum.statusSequence = []
    quantum.statusHang = false
    quantum.resetQuantumPersistence()
    quantumRepo.deleteAll()
  })

  async function run(request: ReturnType<typeof makeRunRequest>, svc = service()): Promise<OptimizationJob> {
    await forecastRepo.save(makeForecast())
    const job = await svc.createJob(request, 'operator')
    return svc.waitForTerminal(job.id)
  }

  it('persists a submitted + completed quantum job and its normalized result', async () => {
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1, 'exactly one quantum_jobs row for a single successful submission')
    const row = rows[0]
    assert.equal(row.id, 'jb-1', 'row id is the quantum service job id')
    assert.equal(row.optimizationJobId, job.id)
    assert.equal(row.algorithm, 'qaoa')
    assert.equal(row.executionMode, 'simulator')
    assert.equal(row.backend, 'qflare_simulator_statevector')
    assert.equal(row.status, 'completed')
    assert.equal(row.qubits, 6)
    assert.equal(row.shots, 1024)
    assert.equal(row.layers, 2)
    assert.ok(row.submittedAt)
    assert.ok(row.startedAt)
    assert.ok(row.completedAt)
    assert.equal(row.errorCode, null)
    assert.equal(row.errorMessage, null)
    assert.equal(row.submittedAt, row.createdAt, 'identity timestamps preserved across queued → completed')

    const result = await quantumRepo.findResult('jb-1')
    assert.ok(result, 'a completed quantum job must have a persistence-layer result row')
    assert.equal(result!.id, `jb-1-R1`)
    assert.equal(result!.quantumJobId, 'jb-1')
    assert.equal(result!.bitstring, job.result!.bitstring)
    assert.deepEqual(result!.counts, { [job.result!.bitstring]: 728 })
    assert.equal(result!.objectiveValue, -1.42)
    assert.equal(result!.runtimeMs, 4)
    assert.equal(result!.rawMetadataReference, null)
  })

  it('recovers the job id from the result when the submission does not carry it', async () => {
    quantum.jobIdFromOptimize = false
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'completed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1, 'no queued row when the submit response lacks a job id')
    assert.equal(rows[0].id, 'jb-1')
    assert.equal(rows[0].status, 'completed')
    assert.ok(await quantumRepo.findResult('jb-1'))
  })

  it('persists a failed row (no result) when the executor fails after accepting', async () => {
    quantum.failResult('simulator')
    const job = await run(makeRunRequest({ executionMode: 'simulator' }), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1)
    assert.equal(rows[0].status, 'failed')
    assert.equal(rows[0].executionMode, 'simulator')
    assert.equal(rows[0].errorCode, 'AER_EXECUTION_FAILED')
    assert.ok(rows[0].errorMessage)
    assert.ok(rows[0].startedAt)
    assert.ok(rows[0].completedAt)
    assert.equal(await quantumRepo.findResult('jb-1'), null, 'failed jobs never persist a result row')
  })

  it('records an honest failed hardware row + completed simulator row on the retry ladder', async () => {
    quantum.failResult('ibm_hardware')
    const job = await run(makeRunRequest({ executionMode: 'ibm_hardware', hardwareEnabled: true, backend: 'ibm_kyiv' }))
    assert.equal(job.status, 'completed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 2, 'one honest row per attempt: failed hardware + completed simulator')
    const [hardware, simulator] = rows
    assert.equal(hardware.id, 'jb-1')
    assert.equal(hardware.executionMode, 'ibm_hardware')
    assert.equal(hardware.backend, 'ibm_kyiv')
    assert.equal(hardware.status, 'failed')
    assert.equal(hardware.errorCode, 'HARDWARE_EXECUTION_FAILED')
    assert.equal(simulator.id, 'jb-2')
    assert.equal(simulator.executionMode, 'simulator')
    assert.equal(simulator.status, 'completed')
    assert.equal(simulator.errorCode, null)
    assert.equal(await quantumRepo.findResult('jb-1'), null)
    assert.ok(await quantumRepo.findResult('jb-2'), 'only the completed simulator submission gets a result row')
  })

  it('persists nothing when the submission itself fails (no row for an unsubmitted job)', async () => {
    quantum.failMode('simulator')
    const job = await run(makeRunRequest())
    assert.equal(job.status, 'failed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 0, 'optimize-level failure means the platform never submitted a quantum job')
  })

  it('persists a cancelled row (EXECUTION_CANCELLED) when the service cancels a running job', async () => {
    quantum.statusSequence = ['cancelled']
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')
    assert.equal(job.error!.code, 'QAOA_EXECUTION_FAILED')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1)
    assert.equal(rows[0].status, 'cancelled')
    assert.equal(rows[0].errorCode, 'EXECUTION_CANCELLED')
    assert.ok(rows[0].errorMessage)
    assert.ok(rows[0].startedAt)
    assert.ok(rows[0].completedAt)
    assert.equal(await quantumRepo.findResult('jb-1'), null, 'a cancelled job never persists a result row')
  })

  it('persists an invalid row (INVALID_EXECUTION_RESULT) for an invalid binary result', async () => {
    quantum.statusSequence = ['invalid']
    const job = await run(makeRunRequest(), service({ fallbackPolicy: 'error' }))
    assert.equal(job.status, 'failed')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1)
    assert.equal(rows[0].status, 'invalid')
    assert.equal(rows[0].errorCode, 'INVALID_EXECUTION_RESULT')
    assert.ok(rows[0].completedAt)
    assert.equal(await quantumRepo.findResult('jb-1'), null, 'invalid jobs never persist a result row')
  })

  it('polls queued → running → completed before reading the result (polling stops at terminal)', async () => {
    quantum.statusSequence = ['running', 'running', 'completed']
    const job = await run(makeRunRequest(), service({ statusPollIntervalMs: 1 }))
    assert.equal(job.status, 'completed')
    assert.ok(quantum.getStatusCalls >= 3, 'the orchestrator traces the transient lifecycle, not just the end state')
    assert.equal(quantum.getStatusCalls, 3, 'polling stops the moment the job reaches a terminal state')

    const rows = await quantumRepo.findJobsByOptimizationJobId(job.id)
    assert.equal(rows.length, 1)
    assert.equal(rows[0].status, 'completed')
    assert.ok(await quantumRepo.findResult('jb-1'))
  })

  it('never lets a persistence store failure take the pipeline down', async () => {
    const broken = service({ quantumJobRepo: new ThrowingQuantumJobRepo(quantumRepo) })
    const job = await run(makeRunRequest(), broken)
    assert.equal(job.status, 'completed', 'best-effort persistence must not break optimization')
  })

  it('enforces the same result-id and FK rules the Postgres migration enforces', async () => {
    await assert.rejects(
      quantumRepo.saveResult({
        id: 'jb-9-R1',
        quantumJobId: 'jb-9',
        bitstring: '000000',
        counts: { '000000': 1 },
        objectiveValue: null,
        runtimeMs: 1,
        rawMetadataReference: null,
        createdAt: new Date().toISOString(),
      }),
      (error) => error instanceof AppError && /unknown quantum job/.test(error.message),
      'a result row may only reference an existing quantum job',
    )
    await quantumRepo.saveJob({
      id: 'jb-7',
      optimizationJobId: 'job-1',
      algorithm: 'qaoa',
      backend: 'qflare_simulator_statevector',
      executionMode: 'simulator',
      qubits: null,
      shots: 1024,
      layers: 2,
      status: 'queued',
      submittedAt: new Date().toISOString(),
      startedAt: null,
      completedAt: null,
      errorCode: null,
      errorMessage: null,
      createdAt: new Date().toISOString(),
    })
    await assert.rejects(
      quantumRepo.saveResult({
        id: 'jb-7-WRONG',
        quantumJobId: 'jb-7',
        bitstring: null,
        counts: {},
        objectiveValue: null,
        runtimeMs: 1,
        rawMetadataReference: null,
        createdAt: new Date().toISOString(),
      }),
      (error) => error instanceof AppError && /does not match/.test(error.message),
      'the result id must be <quantumJobId>-R1',
    )
  })

  it('round-trips lifecycle updates through the memory repository', async () => {
    const submittedAt = new Date().toISOString()
    await quantumRepo.saveJob({
      id: 'jb-5',
      optimizationJobId: 'job-5',
      algorithm: 'qaoa',
      backend: 'qflare_simulator_statevector',
      executionMode: 'simulator',
      qubits: null,
      shots: 1024,
      layers: 2,
      status: 'queued',
      submittedAt,
      startedAt: null,
      completedAt: null,
      errorCode: null,
      errorMessage: null,
      createdAt: submittedAt,
    })
    await quantumRepo.saveJob({
      ...(await quantumRepo.findJobById('jb-5'))!,
      qubits: 6,
      status: 'completed',
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
    })
    const rows = await quantumRepo.findJobsByOptimizationJobId('job-5')
    assert.equal(rows.length, 1, 'upsert updates the row, never duplicates it')
    assert.equal(rows[0].status, 'completed')
    assert.equal(rows[0].qubits, 6)
    assert.equal(rows[0].submittedAt, submittedAt, 'identity timestamps survive the transition')
    assert.equal(rows[0].createdAt, submittedAt)
  })
})