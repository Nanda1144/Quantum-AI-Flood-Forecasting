import '../helpers/env.js'
import assert from 'node:assert/strict'
import { describe, it, before, after } from 'node:test'
import request from 'supertest'
import { createApp } from '../../src/app.ts'
import { buildContainer, type Container } from '../../src/container.ts'
import { FakeForecastClient } from '../helpers/fake-ai-client.ts'
import { FakeQuantumServiceClient } from '../helpers/fake-quantum-client.ts'
import { makeForecast } from '../helpers/optimization-sources.ts'
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

  function login(username: string, password: string): Promise<string> {
    return request(app)
      .post('/api/auth/login')
      .send({ username, password })
      .then((res: LoginResponse) => res.body.data.token)
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

  async function runAndAwait(body: Record<string, unknown> = validBody, token = operatorToken): Promise<string> {
    const res = await request(app).post('/api/optimization/run').set('Authorization', `Bearer ${token}`).send(body).expect(202)
    assert.equal(res.body.success, true)
    const jobId = res.body.data.jobId as string
    assert.ok(jobId.startsWith('QOP-'))
    assert.equal(res.body.data.id, jobId)

    const deadline = Date.now() + 8000
    for (;;) {
      const poll = await request(app).get(`/api/optimization/${jobId}`).set('Authorization', `Bearer ${token}`).expect(200)
      const status = poll.body.data.status as string
      if (status === 'completed' || status === 'failed' || status === 'timed_out') return jobId
      assert.ok(Date.now() < deadline, `job ${jobId} did not reach a terminal state (status ${status})`)
      await new Promise((resolve) => setTimeout(resolve, 25))
    }
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
})