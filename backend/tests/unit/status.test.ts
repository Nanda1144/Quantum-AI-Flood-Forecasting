import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { MemoryForecastRepository } from '../../src/repositories/memory/repositories.ts'
import { StatusService } from '../../src/services/status.service.ts'
import { FakeForecastClient } from '../helpers/fake-ai-client.ts'
import type { Forecast } from '../../src/types/domain.ts'

describe('StatusService', () => {
  function seed(repo: MemoryForecastRepository, createdAt = new Date().toISOString()) {
    const forecast: Forecast = {
      forecastId: 'FC-20260916-0001',
      floodProbability: 0.74,
      riskLevel: 'HIGH',
      predictedWaterLevel: 3.42,
      forecastHorizon: '24h',
      modelId: 'xgboost-v1',
      modelName: 'XGBoost baseline',
      modelVersion: '1.0.0',
      predictionTimestamp: '2026-09-16T09:00:00.000Z',
      status: 'completed',
      priority: 'high',
      createdAt,
    }
    void repo.save(forecast)
  }

  it('reports online when AI is healthy and fresh data exists', async () => {
    const repo = new MemoryForecastRepository()
    seed(repo)
    const svc = new StatusService(repo, new FakeForecastClient())
    const health = await svc.getHealth()
    assert.equal(health.status, 'online')
    assert.ok(typeof health.apiLatencyMs === 'number')
    assert.equal(health.lastSuccessfulPrediction, '2026-09-16T09:00:00.000Z')
    assert.ok(typeof health.dataFreshness === 'string')
  })

  it('reports degraded when AI is down but cached data exists', async () => {
    const repo = new MemoryForecastRepository()
    seed(repo, new Date(Date.now() - 600_000).toISOString())
    const client = new FakeForecastClient()
    client.failAll = true
    const svc = new StatusService(repo, client)
    const health = await svc.getHealth()
    assert.equal(health.status, 'degraded')
    assert.equal(health.apiLatencyMs, null)
  })

  it('reports unavailable when AI is down and no data exists', async () => {
    const client = new FakeForecastClient()
    client.failAll = true
    const svc = new StatusService(new MemoryForecastRepository(), client)
    const health = await svc.getHealth()
    assert.equal(health.status, 'unavailable')
    assert.equal(health.lastSuccessfulPrediction, null)
    assert.equal(health.dataFreshness, null)
  })
})