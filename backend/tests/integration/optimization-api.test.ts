/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import '../helpers/env.js'
import assert from 'node:assert/strict'
import { describe, it, before, after } from 'node:test'
import request from 'supertest'
import { createApp } from '../../src/app.ts'
import { buildContainer, type Container } from '../../src/container.ts'
import { FakeForecastClient } from '../helpers/fake-ai-client.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { makeForecast } from '../helpers/optimization-sources.ts'
import type { OptimizationJob } from '../../src/types/optimization.ts'
import type { Express } from 'express'

interface LoginResponse {
  body: { data: { token: string; user: { username: string; role: string } } }
}

describe('integration: optimization orchestration API', () => {
  let app: Express
  let container: Container
  let quantum: FakeQuantumServiceClient
  let operatorToken: string
  let viewerToken: string
  let adminToken: string

  function loginOn(target: Express, username: string, password: string): Promise<string> {
    return request(target)
      .post('/api/auth/login')
      .send({ username, password })
      .then((res: LoginResponse) => res.body.data.token)
  }

  function login(username: string, password: string): Promise<string> {
    return loginOn(app, username, password)
  }

  before(async () => {
    quantum = new FakeQuantumServiceClient()
    container = await buildContainer({
      aiClient: new FakeForecastClient(),
      optimization: { quantumClient: quantum },
    })
    app = await createApp(container)
    await container.forecastRepo.save(makeForecast())
    operatorToken = await login('operator', 'qflare-operator')
    viewerToken = await login('viewer', 'qflare-viewer')
    adminToken = await login('admin', 'qflare-admin')
  })

  after(async () => {
    await container.forecastRepo.deleteAll()
  })

  const validBody = {
    problem_type: 'sensor_placement',
    candidate_count: 6,
    max_sensors: 3,
    budget_k: null,
    forecast_reference: 'FC-20260916-0001',
    execution_mode: 'simulator',
    hardware_enabled: false,
    backend: 'qflare_simulator_statevector',
    shots: 1024,
    layers: 2,
    weights: { risk: 0.5, populationCoverage: 0.5, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 },
    normalize_weights: true,
    coverage_requirements: [],
  }

  async function runAndAwaitOn(target: Express, token: string, body: Record<string, unknown> = validBody): Promise<string> {
    const res = await request(target).post('/api/optimization/run').set('Authorization', `Bearer ${token}`).send(body).expect(202)
    assert.equal(res.body.success, true)
    const jobId = res.body.data.jobId as string
    assert.ok(jobId.startsWith('QOP-'))
    assert.equal(res.body.data.id, jobId)

    const deadline = Date.now() + 8000
    for (;;) {
      const poll = await request(target).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${token}`).expect(200)
      const status = poll.body.data.status as string
      if (status === 'completed' || status === 'failed' || status === 'timed_out') return jobId
      assert.ok(Date.now() < deadline, `job ${jobId} did not reach a terminal state (status ${status})`)
      await new Promise((resolve) => setTimeout(resolve, 25))
    }
  }

  async function runAndAwait(body: Record<string, unknown> = validBody, token = operatorToken): Promise<string> {
    return runAndAwaitOn(app, token, body)
  }

  describe('POST /api/optimization/run', () => {
    it('returns 401 without a token', async () => {
      await request(app).post('/api/optimization/run').send(validBody).expect(401)
    })

    it('returns 403 for viewers (operator action)', async () => {
      await request(app).post('/api/optimization/run').set('Authorization', `Bearer ${viewerToken}`).send(validBody).expect(403)
    })

    it('202-queues a job and the pipeline completes with a valid result', async () => {
      const jobId = await runAndAwait()
      const res = await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${operatorToken}`).expect(200)
      const summary = res.body.data
      assert.equal(summary.status, 'completed')
      assert.equal(summary.jobId, jobId)
      assert.equal(summary.algorithm, 'qaoa')
      assert.equal(summary.executionModeUsed, 'simulator')
      assert.equal(summary.backend, 'qflare_simulator_statevector')
      assert.equal(summary.qubitCount, 6)
      assert.equal(summary.validationStatus, 'valid')
      assert.equal(summary.fallbackApplied, false)
      assert.equal(summary.resultSummary.selectedCount, 3)
      assert.ok(summary.resultSummary.objectiveValue > 0)
    })

    it('rejects an over-limit cardinality with 422 VALIDATION_ERROR', async () => {
      const res = await request(app)
        .post('/api/optimization/run')
        .set('Authorization', `Bearer ${operatorToken}`)
        .send({ ...validBody, max_sensors: 6, candidate_count: 5 })
        .expect(422)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
      assert.match(JSON.stringify(res.body.error.details), /max_sensors/)
    })

    it('rejects all-zero weights with 422 VALIDATION_ERROR', async () => {
      const res = await request(app)
        .post('/api/optimization/run')
        .set('Authorization', `Bearer ${operatorToken}`)
        .send({
          ...validBody,
          weights: { risk: 0, populationCoverage: 0, infrastructureCoverage: 0, communication: 0, cost: 0, redundancy: 0 },
        })
        .expect(422)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
    })

    it('rejects an out-of-range problem type with 422 VALIDATION_ERROR', async () => {
      const res = await request(app)
        .post('/api/optimization/run')
        .set('Authorization', `Bearer ${operatorToken}`)
        .send({ ...validBody, problem_type: 'rust_propagation' })
        .expect(422)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
    })
  })

  describe('GET /api/optimization/inputs', () => {
    it('serves federated candidates + constraints to any authenticated user', async () => {
      const res = await request(app)
        .get('/api/optimization/inputs?candidateCount=8&forecast=FC-20260916-0001')
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(200)
      assert.equal(res.body.success, true)
      const data = res.body.data
      assert.equal(data.candidates.length, 8)
      assert.ok(data.candidates.every((candidate: { id: string }) => candidate.id.startsWith('SIT-')))
      assert.equal(typeof data.constraints.maxSensors, 'number')
      assert.deepEqual(data.constraints.coverageRequirements, [])
      assert.equal(data.providedBy.candidateLocations, 'GIS module (reference)')
    })

    it('rejects out-of-range candidate counts', async () => {
      await request(app)
        .get('/api/optimization/inputs?candidateCount=1')
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(422)
    })
  })

  describe('ownership scoping', () => {
    it("does not leak another tenant's job (404 for a non-owner)", async () => {
      const jobId = await runAndAwait()
      const res = await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${viewerToken}`).expect(404)
      assert.equal(res.body.error.code, 'JOB_NOT_FOUND')
    })

    it('admin can read any job', async () => {
      const jobId = await runAndAwait()
      await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${adminToken}`).expect(200)
    })

    it('scopes the fine-grained subresources too', async () => {
      const jobId = await runAndAwait()
      await request(app)
        .get(`/api/optimization/jobs/${jobId}/result`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)
    })

    it('404s unknown job ids', async () => {
      const res = await request(app)
        .get('/api/optimization/QOP-DOES-NOT-EXIST')
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(404)
      assert.equal(res.body.error.code, 'JOB_NOT_FOUND')
    })
  })

  describe('GET /api/optimization/jobs/:id subresources', () => {
    it('serves the aggregated pipeline stages', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/pipeline`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const pipeline = res.body.data
      assert.equal(pipeline.jobId, jobId)
      assert.equal(pipeline.completed, true)
      assert.ok(pipeline.stages.length >= 4)
      for (const stage of pipeline.stages) {
        assert.equal(stage.status, 'done')
        assert.ok(stage.label.length > 0)
      }
    })

    it('serves the result document', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const result = res.body.data
      assert.equal(result.jobId, jobId)
      assert.equal(result.quantumAdvantageClaimed, false)
      assert.equal(result.selectedLocations.length, 3)
      assert.ok(result.classicalComparison.objectiveValue > 0)
      assert.deepEqual(result.constraintViolations, [])
      assert.equal(result.validationStatus, 'valid')
    })

    it('serves the QUBO document', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/qubo`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const qubo = res.body.data
      assert.equal(qubo.variableCount, 6)
      assert.equal(qubo.variables.length, 6)
      assert.ok(qubo.expression.length > 0)
    })

    it('serves the full QUBO formulation for the visualization page (inline build)', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/qubo`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const qubo = res.body.data
      assert.equal(qubo.jobId, jobId)
      assert.equal(qubo.available, 'valid')
      assert.equal(qubo.storage, 'inline')
      assert.equal(qubo.inline, true)
      assert.equal(qubo.problemType, 'sensor_placement')
      assert.equal(qubo.status, 'completed')
      assert.ok(qubo.createdAt.length > 0)

      // Backend is the source of truth: full build shipped, nothing derived in React.
      assert.equal(qubo.linear.length, 6)
      assert.equal(qubo.quadratic.length, 6)
      assert.ok(qubo.quadratic.every((row: number[]) => row.length === 6))
      assert.equal(typeof qubo.penaltyScale, 'number')
      assert.ok(qubo.penaltyScale > 0)
      // Stored doc convention: N rows × 2N columns (quadratic row + linear vector).
      assert.equal(qubo.matrix.length, 6)
      assert.ok(qubo.matrix.every((row: number[]) => row.length === 12))

      assert.deepEqual(
        {
          variables: qubo.summary.variables,
          linearTerms: qubo.summary.linearTerms,
          constraints: qubo.summary.constraints,
          penaltyStrength: qubo.summary.penaltyStrength,
        },
        {
          variables: 6,
          linearTerms: qubo.linear.filter((v: number) => Math.abs(v) > 1e-9).length,
          constraints: qubo.constraints.length,
          penaltyStrength: qubo.penaltyScale,
        },
      )
      assert.ok(qubo.summary.quadraticTerms > 0)
      assert.equal(typeof qubo.summary.quadraticTerms, 'number')

      // Constraint rows carry limits, penalty scale, and solution status.
      assert.ok(qubo.constraints.length >= 1)
      const sensorLimit = qubo.constraints.find((row: { key: string }) => row.key === 'sensor_limit')
      assert.ok(sensorLimit)
      assert.equal(sensorLimit.configuredLimit, 3)
      assert.equal(sensorLimit.penalty, qubo.penaltyScale)
      assert.equal(sensorLimit.status, 'satisfied')

      const coverage = qubo.constraints.find((row: { key: string }) => row.key === 'coverage_POPULATION')
      assert.equal(coverage, undefined)

      // Candidate semantics + selected state per variable.
      assert.equal(qubo.variablesDetail.length, 6)
      assert.ok(qubo.variablesDetail.every((v: { candidateId: string; name: string; zone: string; semantic: string }) => v.candidateId.startsWith('SIT-') && v.name !== null && v.zone !== null && v.semantic.length > 0))
      assert.equal(qubo.variablesDetail.filter((v: { selected: boolean }) => v.selected).length, 3)
      assert.equal(qubo.selectedVariableIds.length, 3)
      assert.equal(qubo.hasResult, true)

      // Penalty structure description.
      assert.ok(qubo.penalties.some((p: { key: string }) => p.key === 'cardinality'))
      assert.equal(qubo.penalties[0].formula, 'P·(Σxᵢ − M)²')

      // Objective description is served, never re-derived client-side.
      assert.equal(typeof qubo.objective.explanation, 'string')
      assert.ok(qubo.objective.explanation.length > 0)
    })

    it('serves the full QUBO formulation for artifact-stored builds', async () => {
      // Force large-build artifact storage (inline limit below the candidate count).
      const smallInline = new FakeQuantumServiceClient()
      const artifactContainer = await buildContainer({
        aiClient: new FakeForecastClient(),
        optimization: {
          quantumClient: smallInline,
          options: { quboInlineLimit: 3 },
        },
      })
      const artifactApp = await createApp(artifactContainer)
      await artifactContainer.forecastRepo.save(makeForecast())
      const token = await loginOn(artifactApp, 'operator', 'qflare-operator')

      const jobId = await runAndAwaitOn(artifactApp, token)
      const res = await request(artifactApp)
        .get(`/api/optimization/jobs/${jobId}/qubo`)
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      const qubo = res.body.data
      assert.equal(qubo.available, 'valid')
      assert.equal(qubo.storage, 'artifact')
      assert.equal(qubo.inline, false)
      assert.match(qubo.artifactReference, /qflare:\/\/qubo\//)
      assert.equal(qubo.variableCount, 6)
      // Stored doc convention: N rows × 2N columns (quadratic row + linear vector).
      assert.equal(qubo.matrix.length, 6)
      assert.ok(qubo.matrix.every((row: number[]) => row.length === 12))
      assert.equal(qubo.linear.length, 6)
      assert.equal(qubo.quadratic.length, 6)
      assert.equal(qubo.penaltyScale, qubo.summary.penaltyStrength)

      await artifactContainer.forecastRepo.deleteAll()
    })

    it('serves the persisted classical reference', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/classical`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const classical = res.body.data
      assert.equal(classical.method, 'exhaustive')
      assert.ok(classical.objectiveValue > 0)
      assert.equal(typeof classical.executionTimeMs, 'number')
    })

    it('serves the auditable export document', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/export`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const exportDoc = res.body.data
      assert.equal(exportDoc.jobId, jobId)
      assert.equal(exportDoc.summary.jobId, jobId)
      assert.match(exportDoc.benchmarkDisclaimer, /No quantum speedup/)
      assert.equal(exportDoc.quantumAdvantageClaimed, false)
    })
  })

  describe('fallback through the API', () => {
    it('a failed quantum QUBO still completes the job against the local QUBO', async () => {
      quantum.quboError = new Error('qubo builder down')
      const jobId = await runAndAwait()
      quantum.quboError = null
      const res = await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${operatorToken}`).expect(200)
      const summary = res.body.data
      assert.equal(summary.status, 'completed')
      assert.equal(summary.fallbackApplied, true)
      assert.match(summary.fallbackReason, /quantum_qubo_unavailable/)
    })
  })

  describe('optimization persistence + delete protection', () => {
    it('persists a normalized result row readable at /jobs/:id/results', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/results`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const record = res.body.data
      assert.equal(record.optimizationJobId, jobId)
      assert.equal(record.id, `${jobId}-R1`)
      assert.equal(typeof record.bitstring, 'string')
      assert.equal(record.bitstring.length, 6)
      assert.equal(record.selectedLocationIds.length, 3)
      assert.equal(record.validationStatus, 'valid')
      assert.deepEqual(record.constraintViolations, [])
      assert.ok(record.objectiveValue > 0)
      assert.ok(record.runtimeMs > 0)
      assert.equal(record.quantumObjective, record.classicalObjective)
      assert.equal(record.approximationQuality, 1)
      // Migration 007 classical benchmark reference snapshot (write-once).
      assert.equal(record.classicalSolver, 'exhaustive')
      assert.ok(record.classicalRuntimeMs > 0)
      assert.equal(record.approximationRatio, 1)
      assert.equal(record.approximationBasis, 'exact_optimal')
      assert.equal(record.approximationInvalidReason, null)
      assert.ok(Number.isInteger(record.randomSeed))
    })

    it('scopes /jobs/:id/results and /jobs/:id/audit by ownership', async () => {
      const jobId = await runAndAwait()
      await request(app)
        .get(`/api/optimization/jobs/${jobId}/results`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)
      await request(app)
        .get(`/api/optimization/jobs/${jobId}/audit`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)
    })

    it('404s /jobs/:id/results when a job never produced a result row', async () => {
      const jobId = await runAndAwait({ ...validBody, budget_k: 20 })
      const res = await request(app)
        .get(`/api/optimization/jobs/${jobId}/results`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(404)
      assert.equal(res.body.error.code, 'RESULT_NOT_FOUND')
    })

    it('blocks non-admin deletion of a completed result (403 DELETE_PROTECTED)', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .delete(`/api/optimization/jobs/${jobId}`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .send({ reason: 'cleanup test' })
        .expect(403)
      assert.equal(res.body.error.code, 'DELETE_PROTECTED')

      const audit = await request(app)
        .get(`/api/optimization/jobs/${jobId}/audit`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.deepEqual(audit.body.data, [])
    })

    it('admin soft-deletes a completed result with a reason + audit trail (no hard delete)', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .delete(`/api/optimization/jobs/${jobId}`)
        .set('Authorization', `Bearer ${adminToken}`)
        .send({ reason: 'approved research cleanup' })
        .expect(200)
      assert.equal(res.body.data.status, 'deleted')
      assert.equal(res.body.data.softDelete.deletedBy, 'admin')
      assert.equal(res.body.data.softDelete.deleteReason, 'approved research cleanup')
      assert.ok(res.body.data.softDelete.deletedAt)

      const audit = await request(app)
        .get(`/api/optimization/jobs/${jobId}/audit`)
        .set('Authorization', `Bearer ${adminToken}`)
        .expect(200)
      assert.equal(audit.body.data.length, 1)
      assert.equal(audit.body.data[0].action, 'soft_deleted')
      assert.equal(audit.body.data[0].actor, 'admin')
      assert.equal(audit.body.data[0].reason, 'approved research cleanup')

      // Soft-delete preserves the record: the summary is still readable and the
      // normalized result row survives.
      const summary = await request(app)
        .get(`/api/optimization/${jobId}`)
        .set('Authorization', `Bearer ${adminToken}`)
        .expect(200)
      assert.equal(summary.body.data.status, 'completed')
      await request(app)
        .get(`/api/optimization/jobs/${jobId}/results`)
        .set('Authorization', `Bearer ${adminToken}`)
        .expect(200)
    })

    it('requires an auditable reason (422 without one)', async () => {
      const jobId = await runAndAwait()
      await request(app)
        .delete(`/api/optimization/jobs/${jobId}`)
        .set('Authorization', `Bearer ${adminToken}`)
        .send({})
        .expect(422)
    })

    it('lets the owner delete a failed job (no research result to protect)', async () => {
      const jobId = await runAndAwait({ ...validBody, budget_k: 20 })
      const res = await request(app)
        .delete(`/api/optimization/jobs/${jobId}`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .send({ reason: 'cleanup of a failed run' })
        .expect(200)
      assert.equal(res.body.data.softDelete.deletedBy, 'operator')
    })
  })

  describe('benchmark API', () => {
    it('GET /api/optimization/:id/benchmark returns the stored classical reference (raw measurements)', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data
      assert.equal(doc.jobId, jobId)
      assert.equal(doc.status, 'completed')

      // problem size
      assert.equal(doc.problem.type, 'sensor_placement')
      assert.equal(doc.problem.size.candidates, 6)

      // classical reference
      assert.equal(doc.classical.solver, 'exhaustive')
      assert.equal(doc.classical.optimal, true)
      assert.ok(doc.classical.objectiveValue > 0)
      assert.ok(doc.classical.runtimeMs > 0)

      // quantum outcome
      assert.equal(doc.quantum.algorithm, 'qaoa')
      assert.ok(doc.quantum.objectiveValue > 0)
      assert.equal(doc.quantum.runtimeMs, 4)
      assert.equal(doc.quantum.runtimeSource, 'quantum_results.runtime_ms')

      // constraint violations + ratio + reproducibility
      assert.deepEqual(doc.constraintViolations, [])
      assert.equal(doc.validation.status, 'valid')
      assert.equal(doc.approximationRatio.direction, 'maximize')
      assert.equal(doc.approximationRatio.basis, 'exact_optimal')
      assert.equal(doc.approximationRatio.value, 1)
      assert.equal(doc.approximationRatio.invalidReason, null)
      assert.ok(Number.isInteger(doc.reproducibility.seed))
      assert.equal(doc.reproducibility.qaoa.layers, 2)
      assert.equal(doc.reproducibility.qaoa.shots, 1024)
      assert.equal(doc.reproducibility.qaoa.angles, null)
      assert.equal(doc.quantumAdvantageClaimed, false)
      assert.match(doc.disclaimer, /No quantum speedup is claimed/)
    })

    it('POST /api/optimization/:id/benchmark is the idempotent execute-or-retrieve', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .post(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(res.body.data.jobId, jobId)
      assert.equal(res.body.data.classical.solver, 'exhaustive')
      assert.equal(res.body.data.quantum.runtimeMs, 4)
    })

    it('GET returns 404 and POST returns 409 when no benchmark exists (job failed before a result)', async () => {
      const jobId = await runAndAwait({ ...validBody, budget_k: 20 })
      assert.equal((await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${operatorToken}`).expect(200)).body.data.status, 'failed')

      const missing = await request(app)
        .get(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(404)
      assert.equal(missing.body.error.code, 'RESULT_NOT_FOUND')

      const notComplete = await request(app)
        .post(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(409)
      assert.equal(notComplete.body.error.code, 'JOB_NOT_COMPLETE')
    })

    it('scopes the benchmark read to the owner and hides soft-deleted jobs', async () => {
      const jobId = await runAndAwait()
      await request(app)
        .get(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)

      await request(app)
        .delete(`/api/optimization/jobs/${jobId}`)
        .set('Authorization', `Bearer ${adminToken}`)
        .send({ reason: 'clean up benchmark test job' })
        .expect(200)
      await request(app)
        .get(`/api/optimization/${jobId}/benchmark`)
        .set('Authorization', `Bearer ${adminToken}`)
        .expect(404)
    })

    it('GET /api/optimization/benchmarks lists completed experiments and honours filters', async () => {
      const jobId = await runAndAwait()
      const rows = await request(app)
        .get('/api/optimization/benchmarks')
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)

      const hits = rows.body.data.filter((row: { jobId: string }) => row.jobId === jobId)
      assert.equal(hits.length, 1)
      assert.equal(hits[0].problemType, 'sensor_placement')
      assert.equal(hits[0].algorithm, 'qaoa')
      assert.equal(hits[0].classical.optimal, true)
      assert.equal(hits[0].validated, true)
      assert.ok(typeof hits[0].approximationRatio.value === 'number')

      const filtered = await request(app)
        .get('/api/optimization/benchmarks')
        .query({ problem_type: 'sensor_placement', algorithm: 'qaoa', execution_mode: 'simulator' })
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.ok(filtered.body.data.some((row: { jobId: string }) => row.jobId === jobId))

      const none = await request(app)
        .get('/api/optimization/benchmarks')
        .query({ execution_mode: 'ibm_hardware' })
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(none.body.data.length, 0)
    })
  })

  describe('final optimization result API', () => {
    async function tamperResult(jobId: string, mutate: (job: OptimizationJob) => void): Promise<void> {
      const job = await container.jobRepo.findById(jobId)
      assert.ok(job, `job ${jobId} must exist`)
      mutate(job)
      await container.jobRepo.save(job)
    }

    it('GET /api/optimization/:id/result serves the integrity-audited result model', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data

      // Stored measurements, served verbatim.
      assert.equal(doc.jobId, jobId)
      assert.equal(doc.bitstring.length, 6)
      assert.equal(doc.selectedLocations.length, 3)
      assert.ok(doc.objectiveValue > 0)
      assert.deepEqual(doc.constraintViolations, [])
      assert.equal(doc.validationStatus, 'valid')
      assert.equal(typeof doc.executionTimeMs, 'number')

      // Classical + quantum comparison and the direction-aware ratio.
      assert.equal(doc.classicalComparison.method, 'exhaustive')
      assert.ok(doc.classicalComparison.objectiveValue > 0)
      assert.equal(doc.quantumComparison.algorithm, 'qaoa')
      assert.equal(doc.quantumComparison.runtimeMs, 4)
      assert.equal(doc.approximationRatio.direction, 'maximize')
      assert.equal(doc.approximationRatio.value, 1)

      // Experiment metadata (exact configuration, never fabricated).
      assert.equal(doc.experiment.problemType, 'sensor_placement')
      assert.equal(doc.experiment.algorithm, 'qaoa')
      assert.equal(doc.experiment.executionModeUsed, 'simulator')
      assert.equal(doc.experiment.variablesCount, 6)
      assert.equal(doc.experiment.shots, 1024)
      assert.equal(doc.experiment.layers, 2)
      assert.ok(Number.isInteger(doc.experiment.reproducibility.seed))
      assert.equal(doc.experiment.owner, 'operator')

      // Backend integrity audit + recommendation gate.
      assert.equal(doc.integrity.valid, true)
      assert.deepEqual(doc.integrity.failed, [])
      assert.equal(doc.integrity.checks.length, 6)
      assert.equal(doc.recommendation.eligible, true)
      assert.equal(doc.recommendation.reason, null)
      assert.equal(doc.quantumAdvantageClaimed, false)

      // Sensitive result access is audited.
      const audit = await request(app)
        .get(`/api/optimization/jobs/${jobId}/audit`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.ok(audit.body.data.some((entry: { action: string }) => entry.action === 'result_viewed'))
    })

    it('GET /api/optimization/:id includes the audited result', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/${jobId}`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(res.body.data.status, 'completed')
      assert.equal(res.body.data.result.jobId, jobId)
      assert.equal(res.body.data.result.integrity.valid, true)
      assert.equal(res.body.data.result.recommendation.eligible, true)
    })

    it('a tampered bitstring is marked invalid and preserved, never recommended', async () => {
      const jobId = await runAndAwait()
      await tamperResult(jobId, (job) => {
        job.result!.bitstring = `${job.result!.bitstring}1`
      })
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data
      assert.equal(doc.integrity.valid, false)
      assert.ok(doc.integrity.failed.includes('bitstring_maps_to_variables'))
      assert.equal(doc.recommendation.eligible, false)
      assert.match(doc.recommendation.reason, /integrity audit failed/)
      // Preserved for debugging/research — the raw stored value is still returned.
      assert.equal(doc.bitstring.length, 7)
    })

    it('a selected location that is not a known candidate is rejected', async () => {
      const jobId = await runAndAwait()
      await tamperResult(jobId, (job) => {
        job.result!.selectedLocations = [
          { ...job.result!.selectedLocations[0], id: 'SIT-999' },
          ...job.result!.selectedLocations.slice(1),
        ]
      })
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(res.body.data.integrity.valid, false)
      assert.ok(res.body.data.integrity.failed.includes('selected_candidates_exist'))
      assert.equal(res.body.data.recommendation.eligible, false)
    })

    it('a decoded solution that violates constraints is rejected even when the row hides it', async () => {
      const jobId = await runAndAwait()
      const candidates = await container.candidates.getCandidates({ reference: 'gis://candidates/6', count: 6 })
      await tamperResult(jobId, (job) => {
        job.result!.bitstring = '1'.repeat(6)
        job.result!.selectedLocations = candidates.map((site) => ({
          id: site.id,
          name: site.name,
          zone: site.zone,
          sensorCostK: site.sensorCostK,
          floodRisk: site.floodRisk,
          populationCovered: site.populationExposure,
          infrastructureCovered: site.infrastructureCriticality,
        }))
      })
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(res.body.data.integrity.valid, false)
      assert.ok(res.body.data.integrity.failed.includes('constraints_satisfied'))
      assert.equal(res.body.data.recommendation.eligible, false)
    })

    it('a stored objective inconsistent with the decoded solution is rejected', async () => {
      const jobId = await runAndAwait()
      const job = await container.jobRepo.findById(jobId)
      assert.ok(job?.result, `job ${jobId} must have a result`)
      const tamperedObjective = job.result.objectiveValue + 1000
      await tamperResult(jobId, (row) => {
        row.result!.objectiveValue = tamperedObjective
      })
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data
      assert.equal(doc.integrity.valid, false)
      assert.deepEqual(doc.integrity.failed, ['objective_consistent'])
      assert.equal(doc.recommendation.eligible, false)
      assert.match(doc.recommendation.reason, /integrity audit failed/)
      // Preserved for debugging/research — the raw tampered objective is returned.
      assert.equal(doc.objectiveValue, tamperedObjective)
    })

    it('a pending-validation result is preserved but never recommended', async () => {
      const jobId = await runAndAwait()
      await tamperResult(jobId, (job) => {
        job.result!.validationStatus = 'pending_validation'
        job.validationStatus = 'pending_validation'
      })
      const res = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data
      assert.equal(doc.validationStatus, 'pending_validation')
      assert.equal(doc.integrity.valid, false)
      assert.ok(doc.integrity.failed.includes('result_status'))
      assert.equal(doc.recommendation.eligible, false)
      assert.match(doc.recommendation.reason, /integrity audit failed/)
      // Preserved for debugging/research — the raw stored result is still served.
      assert.equal(doc.jobId, jobId)
    })

    it('returns 404 RESULT_NOT_FOUND and a null result when no benchmark/result exists', async () => {
      const jobId = await runAndAwait({ ...validBody, budget_k: 20 })
      const missing = await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(404)
      assert.equal(missing.body.error.code, 'RESULT_NOT_FOUND')

      const detail = await request(app)
        .get(`/api/optimization/${jobId}`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.equal(detail.body.data.status, 'failed')
      assert.equal(detail.body.data.result, null)
    })

    it('scopes result + export to the owner (404 for a non-owner, 401 unauthenticated)', async () => {
      const jobId = await runAndAwait()
      await request(app)
        .get(`/api/optimization/${jobId}/result`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)
      await request(app)
        .get(`/api/optimization/${jobId}/export`)
        .set('Authorization', `Bearer ${viewerToken}`)
        .expect(404)
      await request(app).get(`/api/optimization/${jobId}/result`).expect(401)
      await request(app).get(`/api/optimization/${jobId}/export`).expect(401)
    })

    it('GET /api/optimization/:id/export returns the structured export and audits it', async () => {
      const jobId = await runAndAwait()
      const res = await request(app)
        .get(`/api/optimization/${jobId}/export`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      const doc = res.body.data
      assert.equal(doc.jobId, jobId)
      assert.equal(doc.summary.jobId, jobId)
      assert.equal(doc.result.jobId, jobId)
      assert.equal(doc.integrity.valid, true)
      assert.equal(doc.recommendation.eligible, true)
      assert.equal(doc.experiment.problemType, 'sensor_placement')
      assert.equal(doc.quantumAdvantageClaimed, false)
      assert.match(doc.benchmarkDisclaimer, /No quantum speedup/)
      assert.ok(doc.exportedAt)

      const audit = await request(app)
        .get(`/api/optimization/jobs/${jobId}/audit`)
        .set('Authorization', `Bearer ${operatorToken}`)
        .expect(200)
      assert.ok(audit.body.data.some((entry: { action: string }) => entry.action === 'result_exported'))
    })
  })
})