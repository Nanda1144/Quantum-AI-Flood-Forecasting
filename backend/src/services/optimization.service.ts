/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { randomUUID } from 'node:crypto'
import { AppError, ErrorCodes } from '../envelope.ts'
import type { ForecastRepository, OptimizationRepository } from '../repositories/repositories.ts'
import type { OptimizationReference } from '../types/domain.ts'

export interface OptimizationHandoffPayload {
  forecast_id: string
  risk_score?: number
  priority?: OptimizationReference['priority']
  candidate_locations_available?: boolean
  resource_constraints_available?: boolean
}

export class OptimizationService {
  constructor(
    private readonly optimizationRepo: OptimizationRepository,
    private readonly forecastRepo: ForecastRepository,
  ) {}

  async createFromForecast(payload: OptimizationHandoffPayload): Promise<OptimizationReference> {
    const forecast = await this.forecastRepo.findByForecastId(payload.forecast_id)
    if (!forecast) throw new AppError(404, ErrorCodes.FORECAST_NOT_FOUND, `Forecast '${payload.forecast_id}' not found`)

    const riskScore = payload.risk_score ?? forecast.floodProbability
    const priority = payload.priority ?? (forecast.riskLevel === 'CRITICAL' ? 'critical' : forecast.riskLevel === 'HIGH' ? 'high' : forecast.riskLevel === 'MEDIUM' ? 'medium' : 'low')

    const existing = await this.optimizationRepo.findByForecastId(payload.forecast_id)
    if (existing) return existing

    const reference: OptimizationReference = {
      id: randomUUID(),
      forecastId: payload.forecast_id,
      riskScore,
      priority,
      candidateLocationsAvailable: payload.candidate_locations_available ?? true,
      resourceConstraintsAvailable: payload.resource_constraints_available ?? true,
      ready: true,
      createdAt: new Date().toISOString(),
    }
    return this.optimizationRepo.save(reference)
  }
}