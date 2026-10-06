/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * `NavyaForecastService` — the forecast + risk service behind the B3 routes.
 *
 * The route → service → repository/client → canonical hydro contract pipeline:
 *
 *     route (validation)
 *       → NavyaForecastService
 *         → ForecastClient (the team's ONLY backend→ai-service bridge)
 *         → ForecastRepository (team abstraction; memory or PostgreSQL)
 *         → canonical contract (`src/types/contract.ts`)
 *
 * ## Serving-boundary errors are never swallowed
 *
 * `createForecast` calls the team's `ForecastClient.getLatestForecast`, which
 * brokers the configured hydro engine through the FastAPI contract. A blocked
 * engine (dependency_blocked / artifact_unavailable / artifact_missing) reaches
 * the backend as `EnvelopeError('FORECAST_ENGINE_ERROR', <engine message>)`;
 * an unreachable service as `EnvelopeError('AI_SERVICE_UNAVAILABLE', ...)`.
 * `mapServingError` converts those into canonical `AppError`s **preserving the
 * engine's message verbatim** — a dependency-blocked learned model is never
 * converted into a successful baseline result, and an error never becomes an
 * HTTP 200 with fake data.
 *
 * ## Persistence is what the schema can hold
 *
 * The forecasts table (migration 001) has no station FK and no units column,
 * so only the `Forecast` domain fields are persisted through the existing
 * repository. Threshold values and provenance live in the response metadata,
 * never pretended to be stored as station_id/units on the forecasts row.
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
 * The Navya forecast surface payload.
 *
 * This is the canonical `ForecastContract` plus the two nullable threshold
 * fields the frontend normalizer (`frontend/src/navya/forecasting/
 * navyaForecastService.ts` → `RawForecastPayload`) already reads. The key set
 * is pinned in tests so the surface cannot drift into a parallel contract.
 */
export interface NavyaForecastResponse extends ForecastContract {
  threshold_level: number | null
  threshold_label: string | null
}

/**
 * Map a serving-boundary failure onto the canonical error envelope.
 *
 * `FORECAST_ENGINE_ERROR` mirrors the code the AI service itself emits when the
 * active engine refuses to serve (hydro: dependency blocked, artifact
 * unavailable/missing). `AI_SERVICE_UNAVAILABLE` is the transport-level state.
 * Anything unexpected from the client is still a serving-boundary failure —
 * never a success, never a fabricated fallback.
 */
export function mapServingError(error: unknown): AppError {
  if (error instanceof AppError) return error
  if (error instanceof EnvelopeError) {
    if (error.code === 'AI_SERVICE_UNAVAILABLE') {
      return new AppError(503, ErrorCodes.AI_SERVICE_UNAVAILABLE, error.message)
    }
    // Engine refusal (or any other AI-service envelope failure): preserve the
    // code and the engine's own message so dependency_blocked /
    // artifact_unavailable states survive the backend envelope untouched.
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
): NavyaForecastResponse {
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

export class NavyaForecastService {
  constructor(
    private readonly client: ForecastClient,
    private readonly forecastRepo: ForecastRepository,
  ) {}

  /**
   * POST /api/forecast — serve a forecast through the canonical boundary, then
   * persist what the schema can hold. Returns the canonical envelope payload.
   */
  async createForecast(horizonHours = 24): Promise<NavyaForecastResponse> {
    let contract: ForecastContract
    try {
      contract = await this.client.getLatestForecast(horizonHours)
    } catch (error) {
      // No DB-cache fallback here: an explicit creation request must surface a
      // blocked engine, never silently replay something previously stored.
      throw mapServingError(error)
    }

    // Best-effort enrichment, mirroring NavyaForecastAdapter.latest(): a failed
    // risk-analytics call degrades thresholds to null (pending policy), never
    // fails the forecast; a failed models call keeps modelName == model_id, the
    // same fallback the team's ForecastSyncService applies.
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

    return toForecastResponse(forecast, {
      threshold_level: analytics?.threshold_level ?? null,
      threshold_label: analytics?.threshold_label ?? null,
    })
  }

  /** GET /api/forecast/:id — the persisted row, or `null` (→ 404 by the route). */
  async getForecast(forecastId: string): Promise<NavyaForecastResponse | null> {
    const forecast = await this.forecastRepo.findByForecastId(forecastId)
    if (forecast === null) return null
    // The forecasts table stores no threshold columns — honest nulls on read.
    return toForecastResponse(forecast)
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