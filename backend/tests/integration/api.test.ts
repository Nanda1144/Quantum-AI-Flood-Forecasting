import '../helpers/env.js'
import assert from 'node:assert/strict'
import { describe, it, before } from 'node:test'
import request from 'supertest'
import { createApp } from '../../src/app.ts'
import { buildContainer, type Container } from '../../src/container.ts'
import { FakeForecastClient, FAKE_FORECAST, FAKE_MODEL } from '../helpers/fake-ai-client.ts'
import { MemoryModelComparisonRepository } from '../../src/repositories/memory/repositories.ts'
import type { ModelComparisonRow, ModelMetricsHistoryItem } from '../../src/types/domain.ts'
import type { Forecast } from '../../src/types/domain.ts'
import type { Express } from 'express'

function comparisonRow(overrides: Partial<ModelComparisonRow> & { name: string }): ModelComparisonRow {
  return {
    modelId: overrides.modelId ?? `cid-${overrides.name}`,
    name: overrides.name,
    version: overrides.version ?? 'v1.0',
    algorithm: overrides.algorithm ?? 'GRU',
    status: overrides.status ?? 'active',
    dataset: 'dev://comparison/training/panama-basin-2026',
    artifactReference: '',
    metrics: overrides.metrics ?? { rmse: 0.4, mae: 0.3, r2: 0.9 },
    evaluatedAt: overrides.evaluatedAt ?? '2026-08-01T10:00:00.000Z',
    evaluationDataset: 'dev://comparison/eval/gatun-basin-2026',
    ...(overrides.trainingTimeMs !== undefined && { trainingTimeMs: overrides.trainingTimeMs }),
    ...(overrides.inferenceTimeMs !== undefined && { inferenceTimeMs: overrides.inferenceTimeMs }),
  }
}

const COMPARISON_ROWS: ModelComparisonRow[] = [
  comparisonRow({ name: 'GRU-FloodNet', status: 'retired', metrics: { rmse: 0.42, mae: 0.31, r2: 0.86 }, inferenceTimeMs: 9, evaluatedAt: '2026-08-12T10:00:00.000Z' }),
  comparisonRow({ name: 'Deep-Transformer', status: 'active', metrics: { rmse: 0.17, mae: 0.13, r2: 0.97 }, inferenceTimeMs: 4, evaluatedAt: '2026-08-21T10:00:00.000Z' }),
  comparisonRow({ name: 'QEnhanced-LSTM', status: 'development', version: 'v1.1-dev', metrics: { rmse: 0.14, mae: 0.10, r2: 0.97 }, inferenceTimeMs: 10, evaluatedAt: '2026-09-10T10:00:00.000Z' }),
  comparisonRow({ name: 'Unscored', status: 'development', metrics: {}, evaluatedAt: '' }),
]

let app: Express
let container: Container
let client: FakeForecastClient

function makeForecast(overrides: Partial<Forecast> = {}): Forecast {
  return {
    forecastId: overrides.forecastId ?? 'FC-20260916-0001',
    floodProbability: overrides.floodProbability ?? 0.74,
    riskLevel: overrides.riskLevel ?? 'HIGH',
    predictedWaterLevel: overrides.predictedWaterLevel ?? 3.42,
    forecastHorizon: overrides.forecastHorizon ?? '24h',
    modelId: overrides.modelId ?? 'xgboost-v1',
    modelName: overrides.modelName ?? 'XGBoost baseline',
    modelVersion: overrides.modelVersion ?? '1.0.0',
    predictionTimestamp: overrides.predictionTimestamp ?? '2026-09-16T09:00:00.000Z',
    status: overrides.status ?? 'completed',
    priority: overrides.priority ?? 'high',
    createdAt: overrides.createdAt ?? new Date().toISOString(),
  }
}

describe('integration: API', () => {
  before(async () => {
    client = new FakeForecastClient()
    container = await buildContainer({ aiClient: client })
    app = await createApp(container)
  })

  describe('POST /api/auth/login', () => {
    it('returns a JWT for valid credentials', async () => {
      const res = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
        .expect(200)
      assert.equal(res.body.success, true)
      assert.ok(typeof res.body.data.token === 'string')
      assert.equal(res.body.data.user.role, 'admin')
    })

    it('rejects invalid credentials', async () => {
      await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'wrong' })
        .expect(401)
    })
  })

  describe('authentication & authorization', () => {
    it('rejects unauthenticated requests with 401', async () => {
      const res = await request(app).get('/api/ai/analytics').expect(401)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'UNAUTHORIZED')
    })

    it('rejects viewer from optimization with 403', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'viewer', password: 'qflare-viewer' })
      const token = login.body.data.token

      // Seed a forecast so the handoff request body validates.
      await container.forecastRepo.save(makeForecast())

      const res = await request(app)
        .post('/api/optimization/from-forecast')
        .set('Authorization', `Bearer ${token}`)
        .send({ forecast_id: 'FC-20260916-0001' })
        .expect(403)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'FORBIDDEN')
    })
  })

  describe('GET /api/ai/analytics', () => {
    it('returns 200 with snapshot on success', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const res = await request(app)
        .get('/api/ai/analytics')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)

      assert.equal(res.body.success, true)
      const snapshot = res.body.data
      assert.equal(snapshot.forecast.forecastId, FAKE_FORECAST.forecast_id)
      assert.equal(snapshot.forecast.floodProbability, FAKE_FORECAST.flood_probability)
      assert.equal(snapshot.forecast.riskLevel, FAKE_FORECAST.risk_level)
      assert.equal(snapshot.forecast.status, FAKE_FORECAST.status)
      assert.equal(snapshot.forecast.priority, 'high')
      assert.ok(Array.isArray(snapshot.forecastSeries))
      assert.equal(snapshot.forecastSeries.length, 2)
      assert.equal(snapshot.recentPredictions.length, 1)
      assert.equal(snapshot.recentPredictions[0].forecastId, FAKE_FORECAST.forecast_id)
      assert.equal(snapshot.activeModel.modelId, FAKE_MODEL.model_id)
      assert.equal(snapshot.systemHealth.status, 'online')
      assert.equal(snapshot.optimizationReadiness.ready, true)
    })
  })

  describe('validation (422)', () => {
    it('rejects invalid forecast_id with 422 VALIDATION_ERROR', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const res = await request(app)
        .post('/api/optimization/from-forecast')
        .set('Authorization', `Bearer ${token}`)
        .send({ forecast_id: 'bad-id' })
        .expect(422)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
    })

    it('rejects page=0 with 422', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      await request(app)
        .get('/api/ai/predictions?page=0')
        .set('Authorization', `Bearer ${token}`)
        .expect(422)
    })
  })

  describe('missing model', () => {
    it('returns 404 MODEL_NOT_FOUND for unknown numeric registry id', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const res = await request(app)
        .get('/api/ai/models/999999/metrics')
        .set('Authorization', `Bearer ${token}`)
        .expect(404)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'MODEL_NOT_FOUND')
    })

    it('rejects a non-numeric registry id with 422', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const res = await request(app)
        .get('/api/ai/models/nonexistent/metrics')
        .set('Authorization', `Bearer ${token}`)
        .expect(422)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'VALIDATION_ERROR')
    })
  })

  describe('AI service unavailable', () => {
    it('returns 503 when no cached forecast and AI client fails', async () => {
      client.failAll = true
      const freshContainer = await buildContainer({ aiClient: client })
      const freshApp = await createApp(freshContainer)

      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const res = await request(freshApp)
        .get('/api/ai/analytics')
        .set('Authorization', `Bearer ${token}`)
        .expect(503)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'AI_SERVICE_UNAVAILABLE')

      client.failAll = false
    })
  })

  describe('stale data', () => {
    it('reports degraded status when cached forecast is old and AI fails', async () => {
      client.failAll = true
      const staleContainer = await buildContainer({ aiClient: client })
      const staleApp = await createApp(staleContainer)

      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      // Seed a forecast 10 minutes ago (stale window is 90s in test env).
      const old = new Date(Date.now() - 600_000).toISOString()
      await staleContainer.forecastRepo.save(makeForecast({ createdAt: old }))

      const analytics = await request(staleApp)
        .get('/api/ai/analytics')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      assert.equal(analytics.body.data.systemHealth.status, 'degraded')

      const status = await request(staleApp)
        .get('/api/ai/status')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      assert.equal(status.body.data.status, 'degraded')

      client.failAll = false
    })
  })

  describe('pagination', () => {
    it('returns paginated results with total counts and filters', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      // Seed 8 forecasts to test pagination and filtering.
      await container.forecastRepo.deleteAll()
      for (let i = 1; i <= 8; i++) {
        const risk = i <= 3 ? 'HIGH' : 'LOW'
        await container.forecastRepo.save(
          makeForecast({
            forecastId: `FC-20260916-${String(i).padStart(4, '0')}`,
            floodProbability: i / 10,
            riskLevel: risk,
            predictionTimestamp: `2026-09-16T${String(8 + i).padStart(2, '0')}:00:00.000Z`,
          }),
        )
      }

      // Page 1 of 3 (limit=3)
      const p1 = await request(app)
        .get('/api/ai/predictions?page=1&limit=3')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      assert.equal(p1.body.data.items.length, 3)
      assert.equal(p1.body.data.total, 8)
      assert.equal(p1.body.data.totalPages, 3)
      assert.equal(p1.body.data.page, 1)

      // Page 2
      const p2 = await request(app)
        .get('/api/ai/predictions?page=2&limit=3')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      assert.equal(p2.body.data.items.length, 3)

      // Filter HIGH only
      const high = await request(app)
        .get('/api/ai/predictions?risk=HIGH')
        .set('Authorization', `Bearer ${token}`)
        .expect(200)
      assert.equal(high.body.data.total, 3)
      assert.ok(high.body.data.items.every((p: { risk_level: string }) => p.risk_level === 'HIGH'))
    })
  })

  describe('GET /api/ai/models/comparison', () => {
    let compApp: Express

    before(async () => {
      const compContainer = await buildContainer({
        aiClient: new FakeForecastClient(),
        comparisonRepo: new MemoryModelComparisonRepository(COMPARISON_ROWS),
      })
      compApp = await createApp(compContainer)
    })

    async function adminToken(): Promise<string> {
      const login = await request(compApp)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      return login.body.data.token
    }

    it('returns registry rows sorted by newest evaluation first', async () => {
      const res = await request(compApp)
        .get('/api/ai/models/comparison')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.success, true)
      const data = res.body.data
      assert.equal(data.items.length, 4)
      assert.equal(data.items[0].name, 'QEnhanced-LSTM')
      assert.equal(data.evaluatedRange.to, '2026-09-10T10:00:00.000Z')
      assert.deepEqual(data.evaluationDatasets, ['dev://comparison/eval/gatun-basin-2026'])
    })

    it('sorts by rmse ascending with unscored rows last', async () => {
      const res = await request(compApp)
        .get('/api/ai/models/comparison?sort=rmse&direction=asc')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      const names = res.body.data.items.map((item: { name: string }) => item.name)
      assert.deepEqual(names, ['QEnhanced-LSTM', 'Deep-Transformer', 'GRU-FloodNet', 'Unscored'])
    })

    it('filters by registry status', async () => {
      const res = await request(compApp)
        .get('/api/ai/models/comparison?status=development')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      const names = res.body.data.items.map((item: { name: string }) => item.name)
      assert.deepEqual(names, ['QEnhanced-LSTM', 'Unscored'])
    })

    it('rejects an unknown sort key with 422', async () => {
      await request(compApp)
        .get('/api/ai/models/comparison?sort=f1')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })

    it('rejects unauthenticated requests with 401', async () => {
      await request(compApp).get('/api/ai/models/comparison').expect(401)
    })
  })

  describe('POST /api/optimization/from-forecast', () => {
    it('creates an optimization reference for a valid forecast', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'operator', password: 'qflare-operator' })
      const token = login.body.data.token

      await container.forecastRepo.save(makeForecast())

      const res = await request(app)
        .post('/api/optimization/from-forecast')
        .set('Authorization', `Bearer ${token}`)
        .send({ forecast_id: 'FC-20260916-0001' })
        .expect(200)
      assert.equal(res.body.success, true)
      assert.equal(res.body.data.forecastId, 'FC-20260916-0001')
      assert.equal(res.body.data.ready, true)
      assert.equal(res.body.data.priority, 'high')
      assert.ok(typeof res.body.data.id === 'string')
    })

    it('returns the same reference on idempotent call', async () => {
      const login = await request(app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'qflare-admin' })
      const token = login.body.data.token

      const first = await request(app)
        .post('/api/optimization/from-forecast')
        .set('Authorization', `Bearer ${token}`)
        .send({ forecast_id: 'FC-20260916-0001' })

      const second = await request(app)
        .post('/api/optimization/from-forecast')
        .set('Authorization', `Bearer ${token}`)
        .send({ forecast_id: 'FC-20260916-0001' })
        .expect(200)

      assert.equal(second.body.data.id, first.body.data.id)
    })
  })
})

describe('integration: Registry APIs', () => {
  let regApp: Express
  let regContainer: Container

  const REGISTRY_ROWS: ModelComparisonRow[] = [
    { modelId: '1', name: 'GRU-FloodNet', version: 'v1.0', algorithm: 'GRU', status: 'retired', dataset: 'dev://comparison/training/panama-basin-2026', artifactReference: '', metrics: { rmse: 0.42, mae: 0.31, r2: 0.86 }, evaluatedAt: '2026-08-12T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026', inferenceTimeMs: 9 },
    { modelId: '2', name: 'Deep-Transformer', version: 'v1.0', algorithm: 'Transformer', status: 'active', dataset: 'dev://comparison/training/panama-basin-2026', artifactReference: '', metrics: { rmse: 0.17, mae: 0.13, r2: 0.97 }, evaluatedAt: '2026-08-21T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026', inferenceTimeMs: 4 },
    { modelId: '3', name: 'QEnhanced-LSTM', version: 'v1.1-dev', algorithm: 'LSTM', status: 'development', dataset: 'dev://comparison/training/panama-basin-2026', artifactReference: '', metrics: { rmse: 0.14, mae: 0.10, r2: 0.97 }, evaluatedAt: '2026-09-10T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026', inferenceTimeMs: 10 },
    { modelId: '4', name: 'CNN-Rainfall', version: 'v0.1', algorithm: 'CNN', status: 'development', dataset: 'dev://comparison/training/panama-basin-2026', artifactReference: '', metrics: {}, evaluatedAt: '', evaluationDataset: '' },
    { modelId: '5', name: 'SARIMA-Baseline', version: 'v2.0', algorithm: 'SARIMA', status: 'retired', dataset: 'dev://comparison/training/gatun-basin-2026', artifactReference: '', metrics: { rmse: 0.50, mae: 0.39, r2: 0.80 }, evaluatedAt: '2026-07-20T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026', inferenceTimeMs: 15 },
  ]

  const HISTORY_MAP: Map<string, ModelMetricsHistoryItem[]> = new Map([
    [
      '3',
      [
        { modelVersionId: 3, metrics: { rmse: 0.18, mae: 0.13, r2: 0.93 }, inferenceTimeMs: 11, evaluatedAt: '2026-08-15T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026' },
        { modelVersionId: 3, metrics: { rmse: 0.14, mae: 0.10, r2: 0.97 }, inferenceTimeMs: 10, evaluatedAt: '2026-09-10T10:00:00.000Z', evaluationDataset: 'dev://comparison/eval/gatun-basin-2026' },
      ],
    ],
  ])

  before(async () => {
    const repo = new MemoryModelComparisonRepository(REGISTRY_ROWS, HISTORY_MAP)
    regContainer = await buildContainer({ aiClient: new FakeForecastClient(), comparisonRepo: repo })
    regApp = await createApp(regContainer)
  })

  async function adminToken(): Promise<string> {
    const login = await request(regApp)
      .post('/api/auth/login')
      .send({ username: 'admin', password: 'qflare-admin' })
    return login.body.data.token
  }

  async function viewerToken(): Promise<string> {
    const login = await request(regApp)
      .post('/api/auth/login')
      .send({ username: 'viewer', password: 'qflare-viewer' })
    return login.body.data.token
  }

  describe('GET /api/ai/models', () => {
    it('returns paginated list sorted by name ascending', async () => {
      const res = await request(regApp)
        .get('/api/ai/models')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.success, true)
      const { items, total, totalPages, page, limit } = res.body.data
      assert.equal(items.length, 5)
      assert.equal(total, 5)
      assert.equal(totalPages, 1)
      assert.equal(page, 1)
      assert.equal(limit, 20)
      const names = items.map((m: { name: string }) => m.name)
      assert.deepEqual(names, [...names].sort())
    })

    it('filters by status', async () => {
      const res = await request(regApp)
        .get('/api/ai/models?status=development')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.data.total, 2)
      const names = res.body.data.items.map((m: { name: string }) => m.name)
      assert.ok(names.includes('QEnhanced-LSTM'))
      assert.ok(names.includes('CNN-Rainfall'))
    })

    it('filters by algorithm (case-insensitive contains)', async () => {
      const res = await request(regApp)
        .get('/api/ai/models?algorithm=lstm')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.data.total, 1)
      assert.equal(res.body.data.items[0].modelId, '3')
    })

    it('filters by dataset (case-insensitive contains)', async () => {
      const res = await request(regApp)
        .get('/api/ai/models?dataset=gatun')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.data.total, 1)
      assert.equal(res.body.data.items[0].modelId, '5')
    })

    it('paginates correctly across pages', async () => {
      const p1 = await request(regApp)
        .get('/api/ai/models?page=1&limit=2')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(p1.body.data.items.length, 2)
      assert.equal(p1.body.data.total, 5)
      assert.equal(p1.body.data.totalPages, 3)

      const p3 = await request(regApp)
        .get('/api/ai/models?page=3&limit=2')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(p3.body.data.items.length, 1)
      assert.equal(p3.body.data.page, 3)
    })

    it('returns empty items for a non-matching filter', async () => {
      const res = await request(regApp)
        .get('/api/ai/models?dataset=nomatch')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.data.total, 0)
      assert.deepEqual(res.body.data.items, [])
    })

    it('rejects page=0 with 422', async () => {
      await request(regApp)
        .get('/api/ai/models?page=0')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })

    it('rejects limit=101 with 422', async () => {
      await request(regApp)
        .get('/api/ai/models?limit=101')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })

    it('rejects unknown status with 422', async () => {
      await request(regApp)
        .get('/api/ai/models?status=bogus')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })
  })

  describe('POST /api/ai/models/compare', () => {
    it('compares two models and selects the best by policy', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['2', '1'] })
        .expect(200)
      assert.equal(res.body.success, true)
      const data = res.body.data
      assert.equal(data.models.length, 2)
      assert.equal(data.models[0].modelId, '2')
      assert.equal(data.models[1].modelId, '1')
      assert.equal(data.bestModel.modelId, '2')
      assert.equal(data.bestModel.metric, 'r2')
      assert.equal(data.bestModel.score, 0.97)
      assert.ok(data.bestModel.rationale.includes('R²'))
      assert.ok(data.bestModel.rationale.includes('0.970'))
      assert.equal(data.policy.primaryMetric, 'r2')
      assert.equal(data.policy.higherIsBetter, true)
      assert.equal(data.policy.minCandidates, 2)
    })

    it('compares multiple models and picks the best across all', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['1', '2', '3', '5'] })
        .expect(200)
      assert.equal(res.body.data.models.length, 4)
      // r2: id2=0.97, id3=0.97 (tie), id1=0.86, id5=0.80
      // Tie-break: rmse id2=0.17 < id3=0.14 → id3 wins
      assert.equal(res.body.data.bestModel.modelId, '3')
    })

    it('returns null bestModel when fewer than minCandidates are scored', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['1', '4'] })
        .expect(200)
      assert.equal(res.body.data.bestModel, null)
      assert.equal(res.body.data.models.length, 2)
    })

    it('deduplicates model ids and preserves request order', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['3', '1', '3'] })
        .expect(200)
      assert.deepEqual(res.body.data.models.map((m: { modelId: string }) => m.modelId), ['3', '1'])
    })

    it('returns 404 when an id is not found', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['1', '999'] })
        .expect(404)
      assert.equal(res.body.success, false)
      assert.equal(res.body.error.code, 'MODEL_NOT_FOUND')
      assert.deepEqual(res.body.error.details.missingModelIds, ['999'])
    })

    it('rejects non-numeric ids with 422', async () => {
      await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['abc'] })
        .expect(422)
    })

    it('rejects id "0" with 422', async () => {
      await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: ['0'] })
        .expect(422)
    })

    it('rejects empty model_ids with 422', async () => {
      await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({ model_ids: [] })
        .expect(422)
    })

    it('rejects missing model_ids field with 422', async () => {
      await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .send({})
        .expect(422)
    })
  })

  describe('GET /api/ai/models/:id', () => {
    it('returns complete metadata for a numeric id', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/2')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.success, true)
      const m = res.body.data
      assert.equal(m.modelId, '2')
      assert.equal(m.name, 'Deep-Transformer')
      assert.equal(m.status, 'active')
      assert.equal(m.algorithm, 'Transformer')
      assert.equal(m.dataset, 'dev://comparison/training/panama-basin-2026')
      assert.equal(m.metrics.rmse, 0.17)
      assert.ok(m.evaluatedAt)
    })

    it('returns 404 for an unknown numeric id', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/99999')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(404)
      assert.equal(res.body.error.code, 'MODEL_NOT_FOUND')
    })

    it('rejects a non-numeric id with 422', async () => {
      await request(regApp)
        .get('/api/ai/models/abc')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })

    it('rejects id "0" with 422', async () => {
      await request(regApp)
        .get('/api/ai/models/0')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })
  })

  describe('GET /api/ai/models/:id/metrics', () => {
    it('returns metrics history sorted newest first', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/3/metrics')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.equal(res.body.success, true)
      assert.equal(res.body.data.length, 2)
      assert.equal(res.body.data[0].evaluatedAt, '2026-09-10T10:00:00.000Z')
      assert.equal(res.body.data[0].metrics.rmse, 0.14)
      assert.equal(res.body.data[1].evaluatedAt, '2026-08-15T10:00:00.000Z')
    })

    it('returns empty items for a model with no history', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/4/metrics')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.deepEqual(res.body.data, [])
    })

    it('returns empty items for a model with no seeded history', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/1/metrics')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(200)
      assert.deepEqual(res.body.data, [])
    })

    it('returns 404 for an unknown numeric id', async () => {
      const res = await request(regApp)
        .get('/api/ai/models/99999/metrics')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(404)
      assert.equal(res.body.error.code, 'MODEL_NOT_FOUND')
    })

    it('rejects a non-numeric id with 422', async () => {
      await request(regApp)
        .get('/api/ai/models/nonexistent/metrics')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(422)
    })
  })

  describe('RBAC & auth', () => {
    it('allows viewer to read models list', async () => {
      const res = await request(regApp)
        .get('/api/ai/models')
        .set('Authorization', `Bearer ${await viewerToken()}`)
        .expect(200)
      assert.equal(res.body.data.total, 5)
    })

    it('allows viewer to read model compare', async () => {
      const res = await request(regApp)
        .post('/api/ai/models/compare')
        .set('Authorization', `Bearer ${await viewerToken()}`)
        .send({ model_ids: ['1', '2'] })
        .expect(200)
      assert.equal(res.body.data.bestModel.modelId, '2')
    })

    it('allows viewer to read model detail', async () => {
      await request(regApp)
        .get('/api/ai/models/1')
        .set('Authorization', `Bearer ${await viewerToken()}`)
        .expect(200)
    })

    it('allows viewer to read model history', async () => {
      await request(regApp)
        .get('/api/ai/models/3/metrics')
        .set('Authorization', `Bearer ${await viewerToken()}`)
        .expect(200)
    })

    it('rejects unauthenticated requests with 401', async () => {
      await request(regApp).get('/api/ai/models').expect(401)
      await request(regApp).post('/api/ai/models/compare').expect(401)
      await request(regApp).get('/api/ai/models/1').expect(401)
      await request(regApp).get('/api/ai/models/1/metrics').expect(401)
    })
  })

  describe('deployment-change prevention', () => {
    it('returns 404 for nonexistent mutation endpoints', async () => {
      await request(regApp)
        .patch('/api/ai/models/2/status')
        .set('Authorization', `Bearer ${await adminToken()}`)
        .expect(404)
    })
  })
})