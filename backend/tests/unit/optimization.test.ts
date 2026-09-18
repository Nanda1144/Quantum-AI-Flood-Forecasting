import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { MemoryForecastRepository, MemoryOptimizationRepository } from '../../src/repositories/memory/repositories.ts'
import { OptimizationService } from '../../src/services/optimization.service.ts'
import { AppError, ErrorCodes } from '../../src/envelope.ts'

describe('OptimizationService', () => {
  function makeForecast(repo: MemoryForecastRepository) {
    return repo.save({
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
      createdAt: new Date().toISOString(),
    })
  }

  it('creates a ready reference for an existing forecast', async () => {
    const forecastRepo = new MemoryForecastRepository()
    const optRepo = new MemoryOptimizationRepository()
    await makeForecast(forecastRepo)

    const svc = new OptimizationService(optRepo, forecastRepo)
    const ref = await svc.createFromForecast({ forecast_id: 'FC-20260916-0001' })

    assert.equal(ref.forecastId, 'FC-20260916-0001')
    assert.equal(ref.riskScore, 0.74)
    assert.equal(ref.priority, 'high')
    assert.equal(ref.ready, true)
    assert.equal(ref.candidateLocationsAvailable, true)
    assert.ok(typeof ref.id === 'string')
  })

  it('is idempotent — returns the same reference for the same forecast', async () => {
    const forecastRepo = new MemoryForecastRepository()
    const optRepo = new MemoryOptimizationRepository()
    await makeForecast(forecastRepo)

    const svc = new OptimizationService(optRepo, forecastRepo)
    const first = await svc.createFromForecast({ forecast_id: 'FC-20260916-0001' })
    const second = await svc.createFromForecast({ forecast_id: 'FC-20260916-0001' })
    assert.equal(second.id, first.id)
  })

  it('throws FORECAST_NOT_FOUND for an unknown forecast', async () => {
    const svc = new OptimizationService(new MemoryOptimizationRepository(), new MemoryForecastRepository())
    await assert.rejects(
      () => svc.createFromForecast({ forecast_id: 'FC-20260916-9999' }),
      (err: AppError) => err.code === ErrorCodes.FORECAST_NOT_FOUND && err.status === 404,
    )
  })

  it('honours explicit overrides in the payload', async () => {
    const forecastRepo = new MemoryForecastRepository()
    const optRepo = new MemoryOptimizationRepository()
    await makeForecast(forecastRepo)

    const svc = new OptimizationService(optRepo, forecastRepo)
    const ref = await svc.createFromForecast({
      forecast_id: 'FC-20260916-0001',
      risk_score: 0.31,
      priority: 'low',
      candidate_locations_available: false,
    })
    assert.equal(ref.riskScore, 0.31)
    assert.equal(ref.priority, 'low')
    assert.equal(ref.candidateLocationsAvailable, false)
    assert.equal(ref.resourceConstraintsAvailable, true)
  })
})