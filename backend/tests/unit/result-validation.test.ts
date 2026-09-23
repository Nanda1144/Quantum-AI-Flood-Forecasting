/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These tests verify the stored-result integrity audit. A completed
 * job's record must re-derive from its stored inputs alone; tampering with the
 * bitstring, the selected ids, or the objective must flip the audit to invalid
 * so the result is never presented as an operational recommendation.
 */

import assert from 'node:assert/strict'
import { describe, it, before, afterEach } from 'node:test'
import { OptimizationJobService } from '../../src/services/optimization-orchestrator.service.ts'
import { MemoryForecastRepository, MemoryOptimizationJobRepository } from '../../src/repositories/memory/repositories.ts'
import { ServerCandidateStore, ServerConstraintsSource } from '../../src/services/gis/candidate-store.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { candidateSet, makeForecast, makeRunRequest } from '../helpers/optimization-sources.ts'
import { auditOptimizationResult } from '../../src/lib/optimization/result-validation.ts'
import type { OptimizationJob } from '../../src/types/optimization.ts'

const sourceCandidates = candidateSet(6, 'gis://candidates/6')

describe('auditOptimizationResult', () => {
  let forecastRepo: MemoryForecastRepository
  let jobRepo: MemoryOptimizationJobRepository
  let quantum: FakeQuantumServiceClient

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

  async function completedJob(): Promise<OptimizationJob> {
    const service = new OptimizationJobService(
      jobRepo,
      forecastRepo,
      new ServerCandidateStore(),
      new ServerConstraintsSource(),
      quantum,
      { fallbackPolicy: 'retry_simulator', exhaustiveLimit: 18, executionTimeoutMs: 5000, quboInlineLimit: 12 },
    )
    await forecastRepo.save(makeForecast())
    const job = await service.createJob(makeRunRequest({ candidateCount: 6, maxSensors: 3 }), 'operator')
    return service.waitForTerminal(job.id)
  }

  it('attests a completed job whose stored result matches its inputs', async () => {
    const job = await completedJob()
    assert.equal(job.status, 'completed')
    assert.equal(job.validationStatus, 'valid')

    const report = auditOptimizationResult(job, sourceCandidates)
    assert.equal(report.valid, true)
    assert.deepEqual(report.failed, [])
    assert.ok(report.summary.includes('All backend integrity checks passed'))
  })

  it('fails closed when the candidate source cannot be reproduced', async () => {
    const job = await completedJob()
    const report = auditOptimizationResult(job, null, 'candidate service unreachable')
    assert.equal(report.valid, false)
    assert.ok(report.failed.includes('candidate_source'))
  })

  it('detects a tampered bitstring that no longer decodes to the stored selection', async () => {
    const job = await completedJob()
    const original = job.result!.bitstring
    const tampered = original.replace(/^./, '0') === original ? '1' + original.slice(1) : '0' + original.slice(1)
    job.result!.bitstring = tampered

    const report = auditOptimizationResult(job, sourceCandidates)
    assert.equal(report.valid, false)
    assert.ok(report.failed.includes('selected_candidates_exist'))
  })

  it('rejects a selection id that is not a known candidate', async () => {
    const job = await completedJob()
    job.result!.selectedLocations = [
      ...job.result!.selectedLocations,
      { id: 'SIT-FORGED', name: 'Forged', zone: 'X', sensorCostK: 1, floodRisk: 1, populationCovered: 1, infrastructureCovered: 1 },
    ]

    const report = auditOptimizationResult(job, sourceCandidates)
    assert.equal(report.valid, false)
    assert.ok(report.failed.includes('selected_candidates_exist'))
  })

  it('rejects an objective that no longer matches the decoded solution', async () => {
    const job = await completedJob()
    job.result!.objectiveValue = job.result!.objectiveValue + 0.05

    const report = auditOptimizationResult(job, sourceCandidates)
    assert.equal(report.valid, false)
    assert.ok(report.failed.includes('objective_consistent'))
  })
})