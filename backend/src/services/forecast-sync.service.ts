/**
 * Syncs the latest forecast from the AI service into PostgreSQL
 * (and seeds the model registry if empty). The analytics service depends on
 * this rather than calling the AI client directly.
 */

import type { ForecastClient } from '../clients/ai-service.client.ts'
import type { ForecastRepository, ModelRepository } from '../repositories/repositories.ts'
import type { Forecast } from '../types/domain.ts'
import type { ForecastContract } from '../types/contract.ts'

function priorityForRisk(risk: ForecastContract['risk_level']): Forecast['priority'] {
  switch (risk) {
    case 'CRITICAL':
      return 'critical'
    case 'HIGH':
      return 'high'
    case 'MEDIUM':
      return 'medium'
    default:
      return 'low'
  }
}

export class ForecastSyncService {
  constructor(
    private readonly client: ForecastClient,
    private readonly forecastRepo: ForecastRepository,
    private readonly modelRepo: ModelRepository,
  ) {}

  /**
   * Fetch the latest forecast from the AI service, persist it, and upsert
   * the model registry. Returns the persisted forecast. Throws if the AI
   * service is unavailable AND the DB is empty.
   */
  async fetchAndPersist(horizonHours = 24): Promise<{ forecast: Forecast; source: 'ai' | 'db' }> {
    // Always try the AI client first.
    try {
      const contract = await this.client.getLatestForecast(horizonHours)
      const models = await this.client.getModels()
      const model = models.find((m) => m.model_id === contract.model_id)
      const forecast: Forecast = {
        forecastId: contract.forecast_id,
        floodProbability: contract.flood_probability,
        riskLevel: contract.risk_level,
        predictedWaterLevel: contract.predicted_water_level,
        forecastHorizon: contract.forecast_horizon,
        modelId: contract.model_id,
        modelName: model?.name ?? contract.model_id,
        modelVersion: contract.model_version,
        predictionTimestamp: contract.prediction_timestamp,
        status: contract.status,
        priority: priorityForRisk(contract.risk_level),
        createdAt: new Date().toISOString(),
      }
      await this.forecastRepo.save(forecast)
      for (const m of models) await this.modelRepo.upsert(m)
      return { forecast, source: 'ai' }
    } catch (error) {
      // AI service unreachable — fall back to DB.
      const cached = await this.forecastRepo.getLatest()
      if (cached) return { forecast: cached, source: 'db' }
      throw error
    }
  }

  /**
   * Fetch the latest forecast but do NOT persist or error if the AI service
   * is unreachable — used for the status probe (best-effort).
   */
  async probe(): Promise<{ available: boolean; latencyMs: number | null }> {
    try {
      const result = await this.client.health()
      return { available: result.health.status === 'online', latencyMs: result.latencyMs }
    } catch {
      return { available: false, latencyMs: null }
    }
  }
}