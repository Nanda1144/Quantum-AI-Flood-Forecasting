import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { MemoryForecastRepository, MemoryModelRepository } from '../../src/repositories/memory/repositories.ts'
import { ForecastSyncService } from '../../src/services/forecast-sync.service.ts'
import { FakeForecastClient, FAKE_FORECAST, FAKE_MODEL } from '../helpers/fake-ai-client.ts'

describe('ForecastSyncService', () => {
  it('persists a fresh forecast and seeds models when AI is available', async () => {
    const client = new FakeForecastClient()
    const forecastRepo = new MemoryForecastRepository()
    const modelRepo = new MemoryModelRepository()
    const sync = new ForecastSyncService(client, forecastRepo, modelRepo)

    const { forecast, source } = await sync.fetchAndPersist()

    assert.equal(source, 'ai')
    assert.equal(forecast.forecastId, FAKE_FORECAST.forecast_id)
    assert.equal(forecast.floodProbability, FAKE_FORECAST.flood_probability)
    assert.equal(forecast.priority, 'high')
    assert.ok((await forecastRepo.findByForecastId(FAKE_FORECAST.forecast_id)) !== null)
    assert.ok((await modelRepo.findById(FAKE_MODEL.model_id)) !== null)
  })

  it('falls back to the database when the AI service is unavailable', async () => {
    const client = new FakeForecastClient()
    const forecastRepo = new MemoryForecastRepository()
    const modelRepo = new MemoryModelRepository()

    // Seed a cached forecast first.
    const { forecast } = await new ForecastSyncService(client, forecastRepo, modelRepo).fetchAndPersist()

    // Simulate AI down by throwing — the service must NOT throw and must return DB copy.
    client.failAll = true
    const fallback = await new ForecastSyncService(client, forecastRepo, modelRepo).fetchAndPersist()
    assert.equal(fallback.source, 'db')
    assert.equal(fallback.forecast.forecastId, forecast.forecastId)
  })

  it('rethrows when AI is unavailable and the database is empty', async () => {
    const client = new FakeForecastClient()
    client.failAll = true
    const sync = new ForecastSyncService(client, new MemoryForecastRepository(), new MemoryModelRepository())
    await assert.rejects(() => sync.fetchAndPersist())
  })

  it('probe reports availability and latency', async () => {
    const sync = new ForecastSyncService(new FakeForecastClient(), new MemoryForecastRepository(), new MemoryModelRepository())
    const result = await sync.probe()
    assert.equal(result.available, true)
    assert.equal(typeof result.latencyMs, 'number')
  })

  it('probe degrades gracefully when AI is down', async () => {
    const client = new FakeForecastClient()
    client.failAll = true
    const sync = new ForecastSyncService(client, new MemoryForecastRepository(), new MemoryModelRepository())
    const result = await sync.probe()
    assert.equal(result.available, false)
    assert.equal(result.latencyMs, null)
  })
})