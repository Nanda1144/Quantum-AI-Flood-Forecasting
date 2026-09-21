/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: These fixtures are realistic test data for the frontend suite only —
 * they are never shipped as production predictions and make no claim about the
 * real forecasting model's output.
 */

import type { AISnapshot, AIServiceHealth, RiskAnalytics } from '../types/ai'

export function buildRiskAnalytics(overrides: Partial<RiskAnalytics> = {}): RiskAnalytics {
  return {
    riskTrend: [
      { timestamp: '2026-09-20T08:00:00.000Z', value: 0.5 },
      { timestamp: '2026-09-20T10:00:00.000Z', value: 0.6 },
      { timestamp: '2026-09-20T12:00:00.000Z', value: 0.74 },
    ],
    probabilityTrend: [
      { timestamp: '2026-09-20T08:00:00.000Z', value: 0.6 },
      { timestamp: '2026-09-20T10:00:00.000Z', value: 0.66 },
      { timestamp: '2026-09-20T12:00:00.000Z', value: 0.74 },
    ],
    distribution: [
      { riskLevel: 'LOW', count: 12 },
      { riskLevel: 'HIGH', count: 4 },
    ],
    summary: { high: 4, medium: 6, low: 12, critical: 1 },
    overallTrend: 'up',
    ...overrides,
  }
}

export function buildSystemHealth(overrides: Partial<AIServiceHealth> = {}): AIServiceHealth {
  return {
    status: 'online',
    apiLatencyMs: 42,
    lastSuccessfulPrediction: '2026-09-21T08:00:00.000Z',
    dataFreshness: '90s',
    ...overrides,
  }
}

export function buildSnapshot(overrides: Partial<AISnapshot> = {}): AISnapshot {
  return {
    forecast: {
      forecastId: 'FC-20260921-0001',
      floodProbability: 0.74,
      riskLevel: 'HIGH',
      predictedWaterLevel: 7.82,
      forecastHorizon: '24h',
      modelId: 'MODEL001',
      modelVersion: 'v1.14.0',
      createdAt: '2026-09-21T08:00:00.000Z',
      priority: 'high',
    },
    forecastSeries: [
      { timestamp: '2026-09-20T08:00:00.000Z', predictedWaterLevel: 7.4, observedWaterLevel: 7.1, floodProbability: 0.6 },
      { timestamp: '2026-09-20T10:00:00.000Z', predictedWaterLevel: 7.6, observedWaterLevel: 7.3, floodProbability: 0.66 },
      { timestamp: '2026-09-20T12:00:00.000Z', predictedWaterLevel: 7.82, observedWaterLevel: 7.5, floodProbability: 0.74 },
    ],
    thresholds: { thresholdLevel: 8.0, label: 'Flood stage reference' },
    riskAnalytics: buildRiskAnalytics(),
    activeModel: {
      modelId: 'MODEL001',
      name: 'GRU FloodNet Ensemble',
      version: 'v1.14.0',
      algorithm: 'Gated Recurrent Unit ensemble + Bayesian calibration',
      lastTrainedAt: '2026-09-18T08:00:00.000Z',
      lastEvaluatedAt: '2026-09-21T06:00:00.000Z',
      status: 'ready',
      metrics: { rmse: 0.231, mae: 0.174, nse: 0.912, accuracy: 0.894 },
    },
    recentPredictions: [
      { forecastId: 'FC-20260921-0001', timestamp: '2026-09-21T08:00:00.000Z', probability: 0.74, riskLevel: 'HIGH', waterLevel: 7.82, modelId: 'MODEL001', status: 'completed' },
    ],
    optimizationReadiness: {
      forecastId: 'FC-20260921-0001',
      riskScore: 0.74,
      priority: 'high',
      candidateLocationsAvailable: true,
      resourceConstraintsAvailable: true,
      ready: true,
    },
    systemHealth: buildSystemHealth(),
    updatedAt: '2026-09-21T08:01:00.000Z',
    ...overrides,
  }
}