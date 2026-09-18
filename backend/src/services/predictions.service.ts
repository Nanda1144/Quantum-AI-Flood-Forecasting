/** Paginated prediction query service. */

import type { ForecastRepository } from '../repositories/repositories.ts'
import type { Paginated, PredictionQuery } from '../types/domain.ts'
import type { PredictionRecordContract } from '../types/contract.ts'

export class PredictionsService {
  constructor(private readonly forecastRepo: ForecastRepository) {}

  async query(query: PredictionQuery): Promise<Paginated<PredictionRecordContract>> {
    const result = await this.forecastRepo.queryPredictions(query)
    return {
      ...result,
      items: result.items.map((f) => ({
        forecast_id: f.forecastId,
        timestamp: f.predictionTimestamp,
        probability: f.floodProbability,
        risk_level: f.riskLevel,
        water_level: f.predictedWaterLevel,
        model_id: f.modelId,
        status: f.status,
      })),
    }
  }
}