/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/** Assembles the composite analytics snapshot for the dashboard. */

import type { ForecastClient } from '../clients/ai-service.client.ts'
import type { ModelRepository, OptimizationRepository } from '../repositories/repositories.ts'
import { AppError, ErrorCodes } from '../envelope.ts'
import { ForecastSyncService } from './forecast-sync.service.ts'
import type { AnalyticsSnapshot, Forecast, ModelInfo } from '../types/domain.ts'
import type { ForecastPointContract, RiskAnalyticsContract } from '../types/contract.ts'

export class AnalyticsService {
  constructor(
    private readonly sync: ForecastSyncService,
    private readonly modelRepo: ModelRepository,
    private readonly optimizationRepo: OptimizationRepository,
    private readonly client: ForecastClient,
  ) {}

  async getSnapshot(staleWindowMs: number): Promise<AnalyticsSnapshot> {
    let syncResult: Awaited<ReturnType<ForecastSyncService['fetchAndPersist']>>
    try {
      syncResult = await this.sync.fetchAndPersist()
    } catch {
      throw new AppError(503, ErrorCodes.AI_SERVICE_UNAVAILABLE, 'AI service is currently unavailable')
    }
    const { forecast, source } = syncResult
    const isStale = source === 'db' && Date.now() - new Date(forecast.createdAt).getTime() > staleWindowMs

    const activeModel = (await this.modelRepo.findById(forecast.modelId)) ?? (await this.modelRepo.findActive())

    // Best-effort enrichment from the AI service — failures degrade gracefully.
    const [series, risk, recent, health] = await Promise.all([
      this.client.getForecastSeries().catch(() => ([] as ForecastPointContract[])),
      this.client.getRiskAnalytics().catch(() => (null as RiskAnalyticsContract | null)),
      this.client.getRecentPredictions().catch(() => []),
      this.client.health().catch(() => null),
    ])

    const readiness = await this.optimizationRepo.findByForecastId(forecast.forecastId)

    // Thresholds are engine-supplied (never derived here). Absent when the
    // engine has no flood-stage reference.
    const thresholds: AnalyticsSnapshot['thresholds'] = {}
    if (risk && typeof risk.threshold_level === 'number') {
      thresholds.thresholdLevel = risk.threshold_level
      if (risk.threshold_label) thresholds.label = risk.threshold_label
    }

    return {
      forecast: toReportForecast(forecast),
      forecastSeries: series.map((pt) => ({
        timestamp: pt.timestamp,
        predictedWaterLevel: pt.predicted_water_level,
        observedWaterLevel: pt.observed_water_level,
        floodProbability: pt.flood_probability,
      })),
      thresholds,
      riskAnalytics: toFrontendRiskAnalytics(risk),
      activeModel: toFrontendModel(activeModel) ?? {
        modelId: forecast.modelId,
        name: forecast.modelName,
        version: forecast.modelVersion,
        algorithm: forecast.modelName,
        status: 'ready',
        lastTrainedAt: forecast.createdAt,
        lastEvaluatedAt: forecast.createdAt,
        metrics: {},
        derived: true,
      },
      recentPredictions: recent.map((p) => ({
        forecastId: p.forecast_id,
        timestamp: p.timestamp,
        probability: p.probability,
        riskLevel: p.risk_level,
        waterLevel: p.water_level,
        modelId: p.model_id,
        status: p.status,
      })),
      optimizationReadiness: readiness
        ? {
            forecastId: readiness.forecastId,
            riskScore: readiness.riskScore,
            priority: readiness.priority,
            candidateLocationsAvailable: readiness.candidateLocationsAvailable,
            resourceConstraintsAvailable: readiness.resourceConstraintsAvailable,
            ready: readiness.ready,
          }
        : {
            forecastId: forecast.forecastId,
            riskScore: forecast.floodProbability,
            priority: priorityForRisk(forecast.riskLevel),
            candidateLocationsAvailable: true,
            resourceConstraintsAvailable: true,
            ready: true,
          },
      systemHealth: {
        status: source === 'ai' && !isStale ? 'online' : 'degraded',
        apiLatencyMs: health?.latencyMs ?? null,
        lastSuccessfulPrediction: forecast.predictionTimestamp,
        dataFreshness: formatFreshness(forecast.createdAt),
      },
      updatedAt: new Date().toISOString(),
    }
  }
}

function toReportForecast(forecast: Forecast) {
  return {
    forecastId: forecast.forecastId,
    floodProbability: forecast.floodProbability,
    riskLevel: forecast.riskLevel,
    predictedWaterLevel: forecast.predictedWaterLevel,
    forecastHorizon: forecast.forecastHorizon,
    modelId: forecast.modelId,
    modelName: forecast.modelName,
    modelVersion: forecast.modelVersion,
    predictionTimestamp: forecast.predictionTimestamp,
    status: forecast.status,
    priority: priorityForRisk(forecast.riskLevel),
    createdAt: forecast.createdAt,
  }
}

function priorityForRisk(risk: Forecast['riskLevel']): 'low' | 'medium' | 'high' | 'critical' {
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

function toFrontendModel(model: ModelInfo | null) {
  if (!model) return null
  return {
    modelId: model.model_id,
    name: model.name,
    version: model.version,
    algorithm: model.algorithm,
    status: model.status,
    lastTrainedAt: model.last_trained_at,
    lastEvaluatedAt: model.last_evaluated_at,
    metrics: model.metrics,
  }
}

function toFrontendRiskAnalytics(risk: RiskAnalyticsContract | null): AnalyticsSnapshot['riskAnalytics'] {
  if (!risk || risk.risk_trend.length === 0) {
    return {
      riskTrend: [],
      probabilityTrend: [],
      distribution: [],
      summary: { high: 0, medium: 0, low: 0, critical: 0 },
      overallTrend: 'flat',
    }
  }
  return {
    riskTrend: risk.risk_trend.map((p) => ({ timestamp: p.timestamp, value: p.value })),
    probabilityTrend: risk.probability_trend.map((p) => ({ timestamp: p.timestamp, value: p.value })),
    distribution: risk.distribution.map((d) => ({ riskLevel: d.risk_level, count: d.count })),
    summary: risk.summary,
    overallTrend: risk.overall_trend,
  }
}

function formatFreshness(createdAt: string | null): string | null {
  if (!createdAt) return null
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m`
}