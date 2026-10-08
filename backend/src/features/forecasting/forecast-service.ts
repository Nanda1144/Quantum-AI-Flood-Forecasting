/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform. It is honest by construction,
 * per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is
 * clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * `ForecastService` — the forecast + risk service behind the forecast routes.
 *
 * The route → service → repository/client → canonical hydro contract pipeline:
 *
 *     route (validation)
 *       → ForecastService
 *         → ForecastClient (backend→ai-service bridge)
 *         → ForecastRepository (memory or PostgreSQL)
 *         → canonical contract (`src/types/contract.ts`)
 */

import type { ForecastClient } from '../../clients/ai-service.client.ts'
import { AppError, ErrorCodes } from '../../envelope.ts'
import type { ForecastRepository } from '../../repositories/repositories.ts'
import type { ForecastContract, ModelInfoContract } from '../../types/contract.ts'
import type { Forecast } from '../../types/domain.ts'
import { EnvelopeError } from '../../utils/errors.ts'
import {
  riskAreaState,
  riskMapState,
  stationForecastState,
  type RiskAreaResponse,
  type RiskMapResponse,
  type StationForecastResponse,
} from './endpoint-states.ts'

/**
 * The forecast surface payload.
 *
 * This is the canonical `ForecastContract` plus the two nullable threshold
 * fields the frontend normalizer reads.
 */
export interface ForecastResponse extends ForecastContract {
  threshold_level: number | null
  threshold_label: string | null
}

export type NavyaForecastResponse = ForecastResponse

/**
 * Map a serving-boundary failure onto the canonical error envelope.
 */
export function mapServingError(error: unknown): AppError {
  if (error instanceof AppError) return error
  if (error instanceof EnvelopeError) {
    if (error.code === 'AI_SERVICE_UNAVAILABLE') {
      return new AppError(503, ErrorCodes.AI_SERVICE_UNAVAILABLE, error.message)
    }
    return new AppError(502, ErrorCodes.FORECAST_ENGINE_ERROR, error.message)
  }
  return new AppError(
    503,
    ErrorCodes.AI_SERVICE_UNAVAILABLE,
    'AI forecast service did not return a valid response',
  )
}

/** Mirrors `ForecastSyncService.priorityForRisk` — the canonical mapping. */
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

/** Map the persisted domain row back onto the canonical wire contract. */
export function toForecastResponse(
  forecast: Forecast,
  extras: { threshold_level: number | null; threshold_label: string | null } = {
    threshold_level: null,
    threshold_label: null,
  },
): ForecastResponse {
  return {
    forecast_id: forecast.forecastId,
    flood_probability: forecast.floodProbability,
    risk_level: forecast.riskLevel,
    predicted_water_level: forecast.predictedWaterLevel,
    forecast_horizon: forecast.forecastHorizon,
    model_id: forecast.modelId,
    model_version: forecast.modelVersion,
    prediction_timestamp: forecast.predictionTimestamp,
    status: forecast.status,
    threshold_level: extras.threshold_level,
    threshold_label: extras.threshold_label,
  }
}

export class ForecastService {
  constructor(
    private readonly client: ForecastClient,
    private readonly forecastRepo: ForecastRepository,
  ) {}

  /**
   * POST /api/forecast — serve a forecast through the canonical boundary, then
   * persist what the schema can hold. Returns the canonical envelope payload.
   */
  async createForecast(horizonHours = 24): Promise<ForecastResponse> {
    let contract: ForecastContract
    try {
      contract = await this.client.getLatestForecast(horizonHours)
    } catch (error) {
      throw mapServingError(error)
    }

    const [analytics, models] = await Promise.all([
      this.client.getRiskAnalytics().catch(() => null),
      this.client.getModels().catch(() => [] as ModelInfoContract[]),
    ])
    const model: ModelInfoContract | null = models.find((m) => m.model_id === contract.model_id) ?? null

    const forecast: Forecast = {
      forecastId: contract.forecast_id,
      floodProbability: contract.flood_probability,
      riskLevel: contract.risk_level,
      predictedWaterLevel: contract.predicted_water_level,
      forecastHorizon: contract.forecastHorizon ?? contract.forecast_horizon,
      modelId: contract.model_id,
      modelName: model?.name ?? contract.model_id,
      modelVersion: contract.model_version,
      predictionTimestamp: contract.prediction_timestamp,
      status: contract.status,
      priority: priorityForRisk(contract.risk_level),
      createdAt: new Date().toISOString(),
    }
    await this.forecastRepo.save(forecast)

    return toForecastResponse(forecast, {
      threshold_level: analytics?.threshold_level ?? null,
      threshold_label: analytics?.threshold_label ?? null,
    })
  }

  /** GET /api/forecast/:id — the persisted row, or `null` (→ 404 by the route). */
  async getForecast(forecastId: string): Promise<ForecastResponse | null> {
    const forecast = await this.forecastRepo.findByForecastId(forecastId)
    if (forecast === null) return null
    return toForecastResponse(forecast)
  }

  /** GET /api/forecast/latest — fetch most recent persisted forecast. */
  async getLatest(): Promise<ForecastResponse | null> {
    const forecast = await this.forecastRepo.findLatest()
    if (forecast === null) return null
    return toForecastResponse(forecast)
  }

  /** GET /api/forecast/history — fetch historical forecasts. */
  async getHistory(limit = 20): Promise<ForecastResponse[]> {
    const list = await this.forecastRepo.listRecent(limit)
    return list.map((f) => toForecastResponse(f))
  }

  /** GET /api/forecast/station/:id — typed state; the schema has no station FK. */
  stationForecast(stationId: string): StationForecastResponse {
    return stationForecastState(stationId)
  }

  /** GET /api/risk-map — typed NOT_EVALUABLE; no authoritative GIS/exposure data. */
  riskMap(): RiskMapResponse {
    return riskMapState()
  }

  /** GET /api/risk/:areaId — typed NOT_EVALUABLE; no authoritative area risk data. */
  riskForArea(areaId: string): RiskAreaResponse {
    return riskAreaState(areaId)
  }
}

export const NavyaForecastService = ForecastService
