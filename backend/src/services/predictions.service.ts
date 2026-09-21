/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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