/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Optimization source fakes + request/forecast builders shared by the
 * orchestrator unit tests and the optimization API integration tests.
 */

import type { CandidateLocation, CoverageRequirement, ResourceConstraintsInput, RunOptimizationRequest } from '../../src/types/optimization.ts'
import type { CandidateStore, ConstraintsSource } from '../../src/services/gis/candidate-store.ts'
import { generateCandidates } from '../../src/services/gis/candidate-store.ts'
import type { Forecast } from '../../src/types/domain.ts'

/** Deterministic candidate set (mirror the frontend simulator geometry). */
export function candidateSet(count = 6, reference = 'gis://candidates/dev'): CandidateLocation[] {
  return generateCandidates(count, reference)
}

export class StubCandidateStore implements CandidateStore {
  constructor(private readonly rows: CandidateLocation[]) {}
  async getCandidates(): Promise<CandidateLocation[]> {
    return this.rows
  }
}

export class EmptyCandidateStore implements CandidateStore {
  async getCandidates(): Promise<CandidateLocation[]> {
    return []
  }
}

export class StubConstraintsSource implements ConstraintsSource {
  constructor(private readonly overrides: Partial<ResourceConstraintsInput> = {}) {}
  async getConstraints(request: {
    maxSensors: number
    budgetK: number | null
    coverageRequirements: CoverageRequirement[]
    candidateCount: number
  }): Promise<ResourceConstraintsInput> {
    return {
      maxSensors: request.maxSensors,
      budgetK: request.budgetK,
      coverageRequirements: [],
      ...this.overrides,
    }
  }
}

export function makeForecast(overrides: Partial<Forecast> = {}): Forecast {
  return {
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
    ...overrides,
  }
}

export function makeRunRequest(overrides: Partial<RunOptimizationRequest> = {}): RunOptimizationRequest {
  return {
    problemType: 'sensor_placement',
    candidateCount: 6,
    maxSensors: 3,
    budgetK: null,
    forecastReference: 'FC-20260916-0001',
    executionMode: 'simulator',
    hardwareEnabled: false,
    backend: 'qflare_simulator_statevector',
    shots: 1024,
    layers: 2,
    weights: {
      risk: 0.3,
      populationCoverage: 0.3,
      infrastructureCoverage: 0.2,
      communication: 0.1,
      cost: 0.1,
      redundancy: 0,
    },
    normalizeWeights: true,
    coverageRequirements: [],
    ...overrides,
  }
}