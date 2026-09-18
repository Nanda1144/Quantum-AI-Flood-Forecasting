/**
 * Fake AI FastAPI client used by tests — controllable responses/failures so we
 * never need a live Python service or a database.
 */

import type { ForecastClient } from '../../src/clients/ai-service.client.ts'
import type {
  AIHealthContract,
  ForecastContract,
  ForecastPointContract,
  ModelInfoContract,
  PredictionRecordContract,
  RiskAnalyticsContract,
} from '../../src/types/contract.ts'

export const FAKE_HEALTH: AIHealthContract = {
  service: 'ai-service',
  version: '0.1.0',
  engine: 'reference',
  status: 'online',
}

export const FAKE_MODEL: ModelInfoContract = {
  model_id: 'xgboost-v1',
  name: 'XGBoost baseline',
  version: '1.0.0',
  algorithm: 'xgboost',
  status: 'ready',
  last_trained_at: '2026-09-01T00:00:00.000Z',
  last_evaluated_at: '2026-09-10T00:00:00.000Z',
  metrics: { rmse: 0.31, accuracy: 0.88 },
}

export const FAKE_FORECAST: ForecastContract = {
  forecast_id: 'FC-20260916-0001',
  flood_probability: 0.74,
  risk_level: 'HIGH',
  predicted_water_level: 3.42,
  forecast_horizon: '24h',
  model_id: 'xgboost-v1',
  model_version: '1.0.0',
  prediction_timestamp: '2026-09-16T09:00:00.000Z',
  status: 'completed',
}

export const FAKE_SERIES: ForecastPointContract[] = [
  { timestamp: '2026-09-16T08:00:00.000Z', predicted_water_level: 2.9, observed_water_level: 2.7, flood_probability: 0.31 },
  { timestamp: '2026-09-16T09:00:00.000Z', predicted_water_level: 3.42, flood_probability: 0.74 },
]

export const FAKE_RISK: RiskAnalyticsContract = {
  risk_trend: [{ timestamp: '2026-09-16T07:00:00.000Z', value: 0.4 }],
  probability_trend: [{ timestamp: '2026-09-16T08:00:00.000Z', value: 0.55 }],
  distribution: [
    { risk_level: 'LOW', count: 12 },
    { risk_level: 'HIGH', count: 4 },
  ],
  summary: { high: 4, medium: 6, low: 12, critical: 1 },
  overall_trend: 'up',
}

export const FAKE_PREDICTIONS: PredictionRecordContract[] = [
  {
    forecast_id: 'FC-20260916-0001',
    timestamp: '2026-09-16T09:00:00.000Z',
    probability: 0.74,
    risk_level: 'HIGH',
    water_level: 3.42,
    model_id: 'xgboost-v1',
    status: 'completed',
  },
]

export class FakeForecastClient implements ForecastClient {
  failAll = false
  health: ForecastClient['health'] = async () => {
    if (this.failAll) throw new Error('AI service unreachable')
    return { health: FAKE_HEALTH, latencyMs: 42 }
  }

  getLatestForecast = async (): Promise<ForecastContract> => {
    if (this.failAll) throw new Error('AI service unreachable')
    return FAKE_FORECAST
  }

  getForecastSeries = async (): Promise<ForecastPointContract[]> => {
    if (this.failAll) throw new Error('AI service unreachable')
    return FAKE_SERIES
  }

  getRiskAnalytics = async (): Promise<RiskAnalyticsContract> => {
    if (this.failAll) throw new Error('AI service unreachable')
    return FAKE_RISK
  }

  getModels = async (): Promise<ModelInfoContract[]> => {
    if (this.failAll) throw new Error('AI service unreachable')
    return [FAKE_MODEL]
  }

  getRecentPredictions = async (): Promise<PredictionRecordContract[]> => {
    if (this.failAll) throw new Error('AI service unreachable')
    return FAKE_PREDICTIONS
  }
}